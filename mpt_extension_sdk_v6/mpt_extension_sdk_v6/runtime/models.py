from pathlib import Path
from typing import Annotated, Any, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from mpt_extension_sdk_v6.errors.runtime import ConfigError


class MetaEvent(BaseModel):
    """MetaEvent model for loading metadata."""

    # Keep the order of fields in the model consistent with the order in the metadata file
    event: Annotated[str, Field(min_length=1)]
    condition: Annotated[str | None, Field(min_length=1)] = None
    path: Annotated[str, Field(min_length=1)]
    task: bool

    model_config = ConfigDict(extra="forbid")


class MetaConfig(BaseModel):
    """MetaConfig model for loading metadata."""

    # Keep the order of fields in the model consistent with the order in the metadata file
    version: Annotated[str, Field(min_length=1)]
    openapi: Annotated[str, Field(min_length=1)]

    events: list[MetaEvent]

    model_config = ConfigDict(extra="forbid")

    @classmethod
    def from_file(cls, path: Path) -> Self:
        """Load metadata from a YAML file."""
        if not path.exists():
            raise ConfigError(f"Metadata file was not found: {path}")

        with path.open(encoding="utf-8") as metadata_file:
            raw_payload: Any = yaml.safe_load(metadata_file)

        if not isinstance(raw_payload, dict):
            raise ConfigError("Metadata root must be a mapping")
        try:
            return cls.model_validate(raw_payload)
        except ValidationError as error:
            raise ConfigError(f"Invalid metadata schema: {error}") from error

    def to_file(self, path: Path) -> None:
        """Persist metadata to a YAML file.

        Args:
            path: Destination metadata path.
        """
        path.write_text(
            yaml.safe_dump(
                self.model_dump(exclude_none=True, by_alias=True),
                sort_keys=False,
                allow_unicode=False,
            ),
            encoding="utf-8",
        )
