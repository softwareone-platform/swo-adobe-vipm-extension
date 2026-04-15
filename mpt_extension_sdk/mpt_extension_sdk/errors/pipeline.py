class PipelineError(Exception):
    """Base pipeline exception."""


class CancelError(PipelineError):
    """Raised when processing should be canceled."""


class DeferError(PipelineError):
    """Raised when processing should be deferred."""

    def __init__(self, message: str = "", delay_seconds: int = 300) -> None:
        """Initialize a defer error.

        Args:
            message: Human-readable defer reason.
            delay_seconds: Retry delay in seconds.
        """
        super().__init__(message)
        self.delay_seconds = delay_seconds


class FailError(PipelineError):
    """Raised when processing fails with non-retriable semantics."""
