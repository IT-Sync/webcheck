"""Compatibility exports for public target validation."""

from bot.core.target_validation import (
    TargetValidationError,
    is_public_address,
    resolve_public_addresses,
    validate_monitoring_target,
)

__all__ = [
    "TargetValidationError",
    "is_public_address",
    "resolve_public_addresses",
    "validate_monitoring_target",
]
