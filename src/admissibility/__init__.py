"""TARTAR-style admissibility checking utilities."""

from .tartar_admissibility import (
    AdmissibilityConfig,
    AdmissibilityResult,
    EnvironmentReport,
    check_admissibility,
    check_environment,
    compare_transition_systems,
)

__all__ = [
    "AdmissibilityConfig",
    "AdmissibilityResult",
    "EnvironmentReport",
    "check_admissibility",
    "check_environment",
    "compare_transition_systems",
]
