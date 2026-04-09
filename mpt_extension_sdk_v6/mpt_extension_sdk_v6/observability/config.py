from dataclasses import dataclass
from typing import Self

from mpt_extension_sdk_v6.settings.runtime import RuntimeSettings


@dataclass(frozen=True)
class ObservabilityConfig:
    """Resolved observability settings derived from env vars."""

    enabled: bool
    exporters: tuple[str, ...]
    service_name: str
    applicationinsights_connection_string: str | None = None

    @classmethod
    def from_runtime_settings(cls, runtime_settings: RuntimeSettings) -> Self:
        """Build observability settings from the runtime configuration."""
        configured_exporters = ["otlp"]
        if runtime_settings.applicationinsights_connection_string:
            configured_exporters.append("azure_monitor")

        return cls(
            enabled=runtime_settings.observability_enabled,
            exporters=tuple(configured_exporters),
            service_name=runtime_settings.otel_service_name,
            applicationinsights_connection_string=(
                runtime_settings.applicationinsights_connection_string
            ),
        )
