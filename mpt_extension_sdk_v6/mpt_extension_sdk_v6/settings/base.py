from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Self

from mpt_extension_sdk_v6.errors.runtime import ConfigError


@dataclass(frozen=True)
class BaseSettings(ABC):
    """Base settings class."""

    @property
    def required_env_vars(self) -> list[tuple[str, ...]]:
        """Required environment variables."""
        return []

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        """Check required environment variables are not missing.

        Raises:
            ConfigError: When a required environment variable is absent or empty.
        """
        errors = [msg for env, msg in self.required_env_vars if not env]
        if not errors:
            return

        error_msg = ", ".join(errors)
        raise ConfigError(f"Missing required environment variables: {error_msg}")

    @classmethod
    @abstractmethod
    def load(cls) -> Self:
        """Load all settings."""
        raise NotImplementedError
