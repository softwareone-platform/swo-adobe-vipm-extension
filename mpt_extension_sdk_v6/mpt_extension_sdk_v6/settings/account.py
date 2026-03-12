from dataclasses import dataclass
from typing import Self, override

from mpt_extension_sdk_v6.settings.base import BaseSettings


@dataclass(frozen=True)
class AccountSettings(BaseSettings):
    """Account settings."""

    @override
    @classmethod
    def load(cls) -> Self:
        return cls()
