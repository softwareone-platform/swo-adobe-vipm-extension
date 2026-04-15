class ExtRuntimeError(Exception):
    """Base runtime exception for SDK errors."""


class ConfigError(ExtRuntimeError):
    """Raised when runtime or metadata configuration is invalid."""


class ValidationError(ExtRuntimeError):
    """Raised when a validation error occurs."""
