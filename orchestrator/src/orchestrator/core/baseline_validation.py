"""Pre-flight validation for baseline-compare test runs.

Validates BaselineTestRunORM inputs before execution starts.
Reuses individual check patterns from PreFlightValidator but operates
on baseline-compare data model (SnapshotORM, BaselineTestRunORM).
"""

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Set

from sqlalchemy.orm import Session

from orchestrator.config.credentials import CredentialsStore
from orchestrator.infra.emulator_client import EmulatorClient
from orchestrator.infra.hypervisor import create_hypervisor_provider
from orchestrator.infra.remote_executor import create_executor
from orchestrator.models.enums import BaselineTestType, TemplateType
from orchestrator.models.orm import (
    BaselineTestRunLoadProfileORM,
    BaselineTestRunORM,
    BaselineTestRunTargetORM,
    LabORM,
    LoadProfileORM,
    ScenarioORM,
    ServerORM,
    SnapshotORM,
    SnapshotProfileDataORM,
)

logger = logging.getLogger(__name__)


@dataclass
class ValidationError:
    check: str
    message: str


@dataclass
class ValidationResult:
    passed: bool
    errors: List[ValidationError] = field(default_factory=list)


class BaselinePreFlightValidator:
    """Runs all pre-flight validation checks for a baseline-compare test run."""

    def __init__(self, credentials: CredentialsStore, emulator_port: int = 8080):
        self._credentials = credentials
        self._emulator_port = emulator_port

    def validate(
        self, session: Session, test_run: BaselineTestRunORM,
    ) -> ValidationResult:
        """Run all validation checks across all targets. Collects all errors."""
        errors: List[ValidationError] = []

        lab = session.get(LabORM, test_run.lab_id)
        targets = session.query(BaselineTestRunTargetORM).filter(
            BaselineTestRunTargetORM.baseline_test_run_id == test_run.id,
        ).all()

        if not targets:
            errors.append(ValidationError(
                check="targets",
                message="No targets defined for baseline test run",
            ))
            return ValidationResult(passed=False, errors=errors)

        lp_links = session.query(BaselineTestRunLoadProfileORM).filter(
            BaselineTestRunLoadProfileORM.baseline_test_run_id == test_run.id,
        ).all()
        load_profile_ids = [lpl.load_profile_id for lpl in lp_links]

        if not load_profile_ids:
            errors.append(ValidationError(
                check="load_profiles",
                message="No load profiles selected for baseline test run",
            ))

        # Validate each target
        checked_loadgens: Set[int] = set()
        for target in targets:
            server = session.get(ServerORM, target.target_id)
            loadgen = session.get(ServerORM, target.loadgenerator_id)
            test_snapshot = session.get(SnapshotORM, target.test_snapshot_id)
            compare_snapshot = (
                session.get(SnapshotORM, target.compare_snapshot_id)
                if target.compare_snapshot_id else None
            )
            label = f"[server {server.hostname}]"

            # Check: server reachable
            errors.extend(self._check_server_reachable(server, f"target {server.hostname}"))

            # Check: loadgen reachable (deduplicated)
            if loadgen.id not in checked_loadgens:
                errors.extend(self._check_server_reachable(loadgen, f"loadgen {loadgen.hostname}"))
                checked_loadgens.add(loadgen.id)

            # Check: emulator reachable on target (soft)
            errors.extend(self._check_emulator_reachable(server))

            # Check: test_snapshot
            if test_snapshot:
                if test_snapshot.is_archived:
                    errors.append(ValidationError(
                        check="test_snapshot_archived",
                        message=f"{label} Test snapshot '{test_snapshot.name}' is archived",
                    ))
                else:
                    errors.extend(
                        self._check_snapshot_exists_on_hypervisor(lab, server, test_snapshot)
                    )
            else:
                errors.append(ValidationError(
                    check="test_snapshot",
                    message=f"{label} Test snapshot id={target.test_snapshot_id} not found in DB",
                ))

            # Type-specific checks per target
            test_type = test_run.test_type

            if test_type == BaselineTestType.new_baseline:
                if target.compare_snapshot_id is not None:
                    errors.append(ValidationError(
                        check="new_baseline_no_compare",
                        message=f"{label} new_baseline should not have a compare_snapshot_id",
                    ))

            elif test_type == BaselineTestType.compare:
                if not compare_snapshot:
                    errors.append(ValidationError(
                        check="compare_snapshot_required",
                        message=f"{label} compare test type requires a compare_snapshot_id",
                    ))
                else:
                    errors.extend(self._check_snapshot_hierarchy(
                        session, test_snapshot, compare_snapshot,
                    ))
                    errors.extend(self._check_stored_data(
                        session, compare_snapshot, load_profile_ids,
                    ))

            elif test_type == BaselineTestType.compare_with_new_calibration:
                if not compare_snapshot:
                    errors.append(ValidationError(
                        check="compare_snapshot_required",
                        message=f"{label} compare_with_new_calibration requires a compare_snapshot_id",
                    ))
                else:
                    errors.extend(self._check_stored_data(
                        session, compare_snapshot, load_profile_ids,
                    ))

        # Check: output_folders required for file-heavy scenarios
        scenario = session.get(ScenarioORM, test_run.scenario_id)
        if scenario and scenario.template_type == TemplateType.server_file_heavy:
            for target in targets:
                srv = session.get(ServerORM, target.target_id)
                label = f"[server {srv.hostname}]"
                if not target.output_folders or not target.output_folders.strip():
                    errors.append(ValidationError(
                        check="output_folders_required",
                        message=f"{label} output_folders is required for server-file-heavy scenario",
                    ))

        return ValidationResult(passed=len(errors) == 0, errors=errors)

    def _check_server_reachable(
        self, server: ServerORM, role: str,
    ) -> List[ValidationError]:
        """Check server credentials exist and SSH/WinRM is reachable."""
        errors = []
        try:
            cred = self._credentials.get_server_credential(
                server.id, server.os_family.value,
            )
            if not cred:
                errors.append(ValidationError(
                    check=f"{role}_credentials",
                    message=f"No credentials for {role} server {server.hostname} (id={server.id})",
                ))
                return errors
        except Exception as e:
            errors.append(ValidationError(
                check=f"{role}_credentials",
                message=f"Error getting credentials for {role} {server.hostname}: {e}",
            ))
            return errors

        try:
            executor = create_executor(
                os_family=server.os_family.value,
                host=server.ip_address,
                username=cred.username,
                password=cred.password,
            )
            executor.close()
        except Exception as e:
            errors.append(ValidationError(
                check=f"{role}_reachable",
                message=f"{role.title()} server {server.hostname} ({server.ip_address}) "
                        f"not reachable: {e}",
            ))
        return errors

    def _check_emulator_reachable(self, server: ServerORM) -> List[ValidationError]:
        """Check emulator HTTP health endpoint on target."""
        errors = []
        try:
            client = EmulatorClient(host=server.ip_address, port=self._emulator_port)
            client.health_check()
        except Exception:
            # Emulator may not be running yet (will be deployed during setup).
            # This is a soft check — only warn.
            logger.info(
                "Emulator not reachable on %s:%d (will be deployed during setup)",
                server.ip_address, self._emulator_port,
            )
        return errors

    def _check_snapshot_exists_on_hypervisor(
        self, lab: LabORM, server: ServerORM, snapshot: SnapshotORM,
    ) -> List[ValidationError]:
        """Verify snapshot still exists on the hypervisor."""
        errors = []
        try:
            hyp_cred = self._credentials.get_hypervisor_credential(
                lab.hypervisor_type.value,
            )
            provider = create_hypervisor_provider(
                hypervisor_type=lab.hypervisor_type.value,
                url=lab.hypervisor_manager_url,
                port=lab.hypervisor_manager_port,
                credential=hyp_cred,
            )
            exists = provider.snapshot_exists(
                server.server_infra_ref, snapshot.provider_ref,
            )
            if not exists:
                errors.append(ValidationError(
                    check="snapshot_on_hypervisor",
                    message=f"Snapshot '{snapshot.name}' not found on hypervisor "
                            f"for server {server.hostname}",
                ))
        except Exception as e:
            errors.append(ValidationError(
                check="snapshot_on_hypervisor",
                message=f"Error checking snapshot on hypervisor: {e}",
            ))
        return errors

    def _check_snapshot_hierarchy(
        self,
        session: Session,
        test_snapshot: SnapshotORM,
        compare_snapshot: SnapshotORM,
    ) -> List[ValidationError]:
        """Verify test_snapshot is a descendant of compare_snapshot."""
        errors = []
        current = test_snapshot
        visited: Set[int] = set()

        while current is not None:
            if current.id == compare_snapshot.id:
                return errors  # Found ancestor — valid
            if current.id in visited:
                break  # Cycle protection
            visited.add(current.id)
            if current.parent_id is None:
                break
            current = session.get(SnapshotORM, current.parent_id)

        errors.append(ValidationError(
            check="snapshot_hierarchy",
            message=f"Test snapshot '{test_snapshot.name}' (id={test_snapshot.id}) "
                    f"is not a descendant of compare snapshot "
                    f"'{compare_snapshot.name}' (id={compare_snapshot.id})",
        ))
        return errors

    def _check_stored_data(
        self,
        session: Session,
        compare_snapshot: SnapshotORM,
        load_profile_ids: List[int],
    ) -> List[ValidationError]:
        """Verify compare_snapshot has stored profile data for all selected load profiles."""
        errors = []
        for lp_id in load_profile_ids:
            profile_data = session.query(SnapshotProfileDataORM).filter(
                SnapshotProfileDataORM.snapshot_id == compare_snapshot.id,
                SnapshotProfileDataORM.load_profile_id == lp_id,
            ).first()
            if not profile_data:
                lp = session.get(LoadProfileORM, lp_id)
                lp_name = lp.name if lp else f"id={lp_id}"
                errors.append(ValidationError(
                    check="stored_data",
                    message=f"Compare snapshot '{compare_snapshot.name}' has no stored "
                            f"data for load profile '{lp_name}'",
                ))
            elif not profile_data.stats_data:
                lp = session.get(LoadProfileORM, lp_id)
                lp_name = lp.name if lp else f"id={lp_id}"
                errors.append(ValidationError(
                    check="stored_data_stats",
                    message=f"Compare snapshot '{compare_snapshot.name}' has no stats "
                            f"data for load profile '{lp_name}'",
                ))
        return errors
