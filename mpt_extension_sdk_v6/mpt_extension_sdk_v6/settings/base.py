from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Self


@dataclass(frozen=True)
class BaseSettings(ABC):
    """Base settings class."""

    @classmethod
    @abstractmethod
    def load(cls) -> Self:
        """Load all settings.

        Raises:
            ConfigError: When a required environment variable is absent or empty.
        """
        raise NotImplementedError
