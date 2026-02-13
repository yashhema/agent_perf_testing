"""Pre-flight validation engine.

Runs before test execution starts (state: validating).
Fail fast with clear error messages per ORCHESTRATOR_DATABASE_SCHEMA.md Section 7.
"""

import logging
from dataclasses import dataclass, field
from typing import List

from sqlalchemy.orm import Session

from orchestrator.config.credentials import CredentialsStore
from orchestrator.infra.emulator_client import EmulatorClient
from orchestrator.infra.hypervisor import create_hypervisor_provider
from orchestrator.infra.remote_executor import create_executor
from orchestrator.models.orm import (
    BaselineORM,
    LabORM,
    ServerORM,
    TestRunLoadProfileORM,
    TestRunORM,
    TestRunTargetORM,
)
from orchestrator.services.package_manager import PackageResolver

logger = logging.getLogger(__name__)


@dataclass
class ValidationError:
    check: str
    message: str


@dataclass
class ValidationResult:
    passed: bool
    errors: List[ValidationError] = field(default_factory=list)


class PreFlightValidator:
    """Runs all pre-flight validation checks for a test run."""

    def __init__(self, credentials: CredentialsStore, emulator_port: int = 8080):
        self._credentials = credentials
        self._emulator_port = emulator_port
        self._resolver = PackageResolver()

    def validate(self, session: Session, test_run: TestRunORM) -> ValidationResult:
        """Run all validation checks. Collects all errors rather than failing on first."""
        errors: List[ValidationError] = []

        lab = session.get(LabORM, test_run.lab_id)
        targets = session.query(TestRunTargetORM).filter(
            TestRunTargetORM.test_run_id == test_run.id
        ).all()
        load_profiles = session.query(TestRunLoadProfileORM).filter(
            TestRunLoadProfileORM.test_run_id == test_run.id
        ).all()

        # Check: load profiles selected
        if not load_profiles:
            errors.append(ValidationError(
                check="load_profiles",
                message="No load profiles selected for test run",
            ))

        # Check: targets exist
        if not targets:
            errors.append(ValidationError(
                check="targets",
                message="No targets configured for test run",
            ))

        # Check: hypervisor credentials
        hyp_cred = self._credentials.get_hypervisor_credential(lab.hypervisor_type.value)
        if not hyp_cred:
            errors.append(ValidationError(
                check="hypervisor_credentials",
                message=f"No {lab.hypervisor_type.value} credentials in credentials file",
            ))

        scenario = session.get(type(test_run.scenario), test_run.scenario_id) if test_run.scenario_id else None
        if scenario is None:
            from orchestrator.models.orm import ScenarioORM
            scenario = session.get(ScenarioORM, test_run.scenario_id)

        for target_config in targets:
            server = session.get(ServerORM, target_config.target_id)
            loadgen = session.get(ServerORM, target_config.loadgenerator_id)

            # Check: server credentials
            for srv, label in [(server, "target"), (loadgen, "loadgen")]:
                cred = self._credentials.get_server_credential(srv.id, srv.os_family.value)
                if not cred:
                    errors.append(ValidationError(
                        check="server_credentials",
                        message=f"No credentials found for {label} server {srv.id} or OS {srv.os_family.value}",
                    ))
                    continue

                # Check: server reachable
                try:
                    executor = create_executor(
                        os_family=srv.os_family.value,
                        host=srv.ip_address,
                        username=cred.username,
                        password=cred.password,
                    )
                    executor.close()
                except Exception as e:
                    errors.append(ValidationError(
                        check="server_reachable",
                        message=f"Cannot connect to {label} server {srv.hostname} ({srv.ip_address}): {e}",
                    ))

            # Check: snapshots exist
            if hyp_cred:
                try:
                    provider = create_hypervisor_provider(
                        hypervisor_type=lab.hypervisor_type.value,
                        url=lab.hypervisor_manager_url,
                        port=lab.hypervisor_manager_port,
                        credential=hyp_cred,
                    )
                    for snap_id, snap_label in [
                        (target_config.base_snapshot_id, "base"),
                        (target_config.initial_snapshot_id, "initial"),
                    ]:
                        baseline = session.get(BaselineORM, snap_id)
                        if baseline:
                            snap_name = baseline.provider_ref.get("snapshot_name", "")
                            if snap_name and not provider.snapshot_exists(baseline.provider_ref, snap_name):
                                errors.append(ValidationError(
                                    check="snapshot_exists",
                                    message=f"Snapshot '{baseline.name}' not found on hypervisor ({snap_label})",
                                ))
                except Exception as e:
                    errors.append(ValidationError(
                        check="hypervisor_connection",
                        message=f"Cannot connect to hypervisor: {e}",
                    ))

            # Check: package-to-OS matching
            if scenario:
                base_snap = session.get(BaselineORM, target_config.base_snapshot_id)
                if base_snap:
                    try:
                        self._resolver.resolve_for_phase(session, scenario, base_snap, "base")
                    except ValueError as e:
                        errors.append(ValidationError(
                            check="package_os_match",
                            message=str(e),
                        ))
                    try:
                        self._resolver.resolve_for_phase(session, scenario, base_snap, "initial")
                    except ValueError as e:
                        errors.append(ValidationError(
                            check="package_os_match",
                            message=str(e),
                        ))

            # Check: DB connection (if has_dbtest)
            if scenario and scenario.has_dbtest:
                if not server.db_type or not server.db_port or not server.db_name:
                    errors.append(ValidationError(
                        check="db_connection",
                        message=f"Database fields incomplete on server {server.hostname}",
                    ))

            # Check: service monitor patterns (if set)
            if target_config.service_monitor_patterns:
                cred = self._credentials.get_server_credential(server.id, server.os_family.value)
                if cred:
                    try:
                        executor = create_executor(
                            os_family=server.os_family.value,
                            host=server.ip_address,
                            username=cred.username,
                            password=cred.password,
                        )
                        for pattern in target_config.service_monitor_patterns:
                            if server.os_family.value == "linux":
                                result = executor.execute(f"pgrep -f '{pattern}'")
                            else:
                                result = executor.execute(f'tasklist /FI "IMAGENAME eq {pattern}"')
                            if not result.success:
                                errors.append(ValidationError(
                                    check="service_monitor",
                                    message=f"Agent process matching '{pattern}' not found on server {server.hostname}",
                                ))
                        executor.close()
                    except Exception as e:
                        errors.append(ValidationError(
                            check="service_monitor",
                            message=f"Cannot check agent processes on {server.hostname}: {e}",
                        ))

        return ValidationResult(passed=len(errors) == 0, errors=errors)
