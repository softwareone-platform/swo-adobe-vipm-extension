from pathlib import Path
from typing import Annotated, Any, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from mpt_extension_sdk_v6.errors.runtime import ConfigError


class MetaEvent(BaseModel):
    """MetaEvent model for loading metadata."""

    event: Annotated[str, Field(min_length=1)]
    path: Annotated[str, Field(min_length=1)]
    task: bool
    condition: Annotated[str | None, Field(min_length=1)] = None

    model_config = ConfigDict(extra="forbid")


class MetaConfig(BaseModel):
    """MetaConfig model for loading metadata."""

    version: Annotated[str, Field(min_length=1)]
    openapi: Annotated[str, Field(min_length=1)]
    events: list[MetaEvent]

    model_config = ConfigDict(extra="forbid")

    @classmethod
    def from_file(cls, path: Path) -> Self:
        """Load metadata from a YAML file."""
        if not path.exists():
            raise ConfigError("Metadata file was not found: %s", path)

        with path.open(encoding="utf-8") as metadata_file:
            raw_payload: Any = yaml.safe_load(metadata_file)

        if not isinstance(raw_payload, dict):
            raise ConfigError("Metadata root must be a mapping")
        try:
            return cls.model_validate(raw_payload)
        except ValidationError as error:
            raise ConfigError("Invalid metadata schema: %s", error) from error
