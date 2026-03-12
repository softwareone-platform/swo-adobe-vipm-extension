class StepError(Exception):
    """Base step exception."""


class SkipStepError(StepError):
    """Raised when a step should be skipped."""


class StopStepError(StepError):
    """Raised when a pipeline should stop and cancel processing."""


class DeferStepError(StepError):
    """Raised when a pipeline should stop and defer processing."""

    def __init__(self, message: str = "", delay_seconds: int = 300) -> None:
        """Initialize a defer error."""
        self.delay_seconds = delay_seconds
        super().__init__(message)
