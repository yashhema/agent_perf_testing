"""Package management module.

Provides:
- Package models and measurement records
- Delivery strategies (Direct SSH/PowerShell, MDM via Intune/JAMF)
- Package installation orchestration
- Measurement helpers for comparing expected vs actual
"""

from app.packages.models import (
    PackageInfo,
    PackageInstallResult,
    PackageVerifyResult,
    PackageMeasuredRecord,
    PhasePackageResult,
    InstallStatus,
    VerifyStatus,
)
from app.packages.measurement import (
    build_package_measured_record,
    build_pending_measured_record,
    build_skipped_measured_record,
    build_failed_measured_record,
    build_phase_measured_list,
    check_all_packages_matched,
    check_measured_packages_matched,
    aggregate_phase_result,
    update_measured_record_in_list,
    get_failed_packages,
    get_mismatched_versions,
)
from app.packages.service import PackageInstallationService
from app.packages.delivery import (
    DeliveryMethod,
    DeliveryResult,
    DeliveryStrategy,
    DirectDeliveryStrategy,
    MDMDeliveryStrategy,
    DeliveryStrategyFactory,
)
from app.packages.orchestrator import (
    MatchDecision,
    PackageMatchResult,
    PhaseInstallResult,
    PackageInstallOrchestrator,
)
from app.packages.selection import (
    OSInfo,
    LabPreference,
    SelectedPackage,
    PackageSelectionService,
    build_phase_package_list,
)
from app.packages.resolver import (
    ResolvedPackage,
    PackageResolver,
)

__all__ = [
    # Models
    "PackageInfo",
    "PackageInstallResult",
    "PackageVerifyResult",
    "PackageMeasuredRecord",
    "PhasePackageResult",
    "InstallStatus",
    "VerifyStatus",
    # Measurement helpers
    "build_package_measured_record",
    "build_pending_measured_record",
    "build_skipped_measured_record",
    "build_failed_measured_record",
    "build_phase_measured_list",
    "check_all_packages_matched",
    "check_measured_packages_matched",
    "aggregate_phase_result",
    "update_measured_record_in_list",
    "get_failed_packages",
    "get_mismatched_versions",
    # Service
    "PackageInstallationService",
    # Delivery strategies
    "DeliveryMethod",
    "DeliveryResult",
    "DeliveryStrategy",
    "DirectDeliveryStrategy",
    "MDMDeliveryStrategy",
    "DeliveryStrategyFactory",
    # Orchestrator
    "MatchDecision",
    "PackageMatchResult",
    "PhaseInstallResult",
    "PackageInstallOrchestrator",
    # Selection
    "OSInfo",
    "LabPreference",
    "SelectedPackage",
    "PackageSelectionService",
    "build_phase_package_list",
    # Resolver
    "ResolvedPackage",
    "PackageResolver",
]
