import os
from dataclasses import dataclass

from mpt_extension_sdk_v6.settings.runtime import RuntimeSettings


@dataclass(frozen=True)
class ObservabilityConfig:
    """Resolved observability settings derived from env vars."""

    enabled: bool
    exporters: tuple[str, ...]
    service_name: str

    @classmethod
    def from_runtime_settings(cls, runtime_settings: RuntimeSettings) -> "ObservabilityConfig":
        """Build observability settings from the runtime configuration."""
        configured_exporters = tuple(
            exporter.strip().lower()
            for exporter in os.getenv("SDK_OTEL_EXPORTERS", "otlp").split(",")
            if exporter.strip()
        )

        return cls(
            enabled=runtime_settings.observability_enabled,
            exporters=configured_exporters or ("otlp",),
            service_name=runtime_settings.app_module,
        )
