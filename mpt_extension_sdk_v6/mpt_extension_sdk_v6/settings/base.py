import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar, Self

from mpt_extension_sdk_v6.errors.runtime import ConfigError


@dataclass(frozen=True)
class BaseSettings(ABC):
    """Base settings class."""

    TRUE_VALUES: ClassVar[frozenset[str]] = frozenset(("true", "1", "yes"))

    @property
    def required_env_vars(self) -> list[tuple[str, ...]]:
        """Required environment variables."""
        return []

    def __post_init__(self) -> None:
        self.validate()

    @classmethod
    @abstractmethod
    def load(cls) -> Self:
        """Load all settings."""
        raise NotImplementedError

    @classmethod
    def bool_env(cls, env_key: str, *, default: bool) -> bool:
        """Parse a boolean environment variable using shared settings conventions."""
        raw_value = os.getenv(env_key, str(default)).lower()
        return raw_value in cls.TRUE_VALUES

    @classmethod
    def int_env(cls, env_key: str, default: int) -> int:
        """Parse an integer environment variable and raise ConfigError on failure."""
        raw_value = os.getenv(env_key, str(default))
        try:
            return int(raw_value)
        except ValueError as error:
            raise ConfigError(f"Invalid integer in {env_key}: {raw_value}") from error

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
