import os
import socket
import uuid
from dataclasses import dataclass
from functools import lru_cache
from importlib import import_module
from pathlib import Path
from typing import Self, override

from mpt_extension_sdk_v6.errors.runtime import ConfigError
from mpt_extension_sdk_v6.runtime.models import MetaConfig
from mpt_extension_sdk_v6.settings.base import BaseSettings

DEFAULT_LOCAL_PORT = 8080


@dataclass(frozen=True)
class RuntimeSettings(BaseSettings):
    """Runtime settings loaded exclusively from environment variables."""

    app_module: str
    settings_module: str
    ext_api_key: str
    base_url: str
    extension_id: str
    mpt_api_base_url: str
    mpt_api_token: str
    external_id: str
    identity_file_path: Path
    meta_config: MetaConfig
    meta_file_path: Path
    local_host: str
    local_port: int
    local_reload: bool
    local_workers: int
    log_level: str
    observability_enabled: bool
    applicationinsights_connection_string: str
    otel_service_name: str
    ziti_workers: int
    ziti_reload: bool

    @property
    def extension_package(self) -> str:
        """Return the extension package name."""
        return self.app_module.split(".")[0]

    @override
    @property
    def required_env_vars(self) -> list[tuple[str, ...]]:
        return [
            (self.base_url, "SDK extension registration URL is required (SDK_EXTENSION_URL)"),
            (self.ext_api_key, "SDK API key is required (SDK_EXTENSION_API_KEY)"),
            (self.mpt_api_base_url, "MPT API base URL is required (MPT_API_BASE_URL)"),
            (self.mpt_api_token, "MPT API token is required (MPT_API_TOKEN)"),
        ]

    @override
    @classmethod
    def load(cls) -> Self:
        external_id = cls._resolve_external_id()
        root_package = cls._discover_extension_root_package(Path.cwd())
        return cls(
            app_module=f"{root_package}.app",
            settings_module=f"{root_package}.settings",
            ext_api_key=os.getenv("SDK_EXTENSION_API_KEY", ""),
            base_url=os.getenv("SDK_EXTENSION_URL", ""),
            extension_id=os.getenv("SDK_EXTENSION_ID", ""),
            mpt_api_base_url=os.getenv("MPT_API_BASE_URL", ""),
            mpt_api_token=os.getenv("MPT_API_TOKEN", ""),
            external_id=external_id,
            identity_file_path=cls._resolve_identity_file_path(external_id),
            meta_config=cls._load_generated_meta_config(root_package),
            meta_file_path=Path.cwd() / "meta.yaml",
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            observability_enabled=cls.bool_env("SDK_OBSERVABILITY_ENABLED", default=True),
            applicationinsights_connection_string=os.getenv(
                "SDK_APPLICATIONINSIGHTS_CONNECTION_STRING", ""
            ),
            otel_service_name=os.getenv("SDK_OTEL_SERVICE_NAME", ""),
            local_host=os.getenv("SDK_LOCAL_HOST", "0.0.0.0"),  # noqa: S104
            local_port=cls.int_env("SDK_LOCAL_PORT", DEFAULT_LOCAL_PORT),
            local_reload=cls.bool_env("SDK_LOCAL_RELOAD", default=True),
            local_workers=cls.int_env("SDK_LOCAL_WORKERS", 1),
            ziti_workers=cls.int_env("SDK_ZITI_WORKERS", 4),
            ziti_reload=cls.bool_env("SDK_ZITI_RELOAD", default=False),
        )

    @classmethod
    def _resolve_external_id(cls) -> str:
        """Resolve the external ID from env or host metadata."""
        configured_external_id = os.getenv("SDK_EXTENSION_EXTERNAL_ID", "")
        if configured_external_id:
            return configured_external_id

        hostname = socket.gethostname().strip()
        return hostname or f"{uuid.getnode():012x}"  # noqa: WPS237

    @classmethod
    def _resolve_identity_file_path(cls, external_id: str) -> Path:
        """Resolve the identity file path from env or the default runtime location."""
        identity_file_path_env = os.getenv("SDK_IDENTITY_FILE_PATH", "")
        if identity_file_path_env:
            return Path(identity_file_path_env)

        return Path.cwd() / f"{external_id}_identity.json"

    @classmethod
    def _load_generated_meta_config(cls, root_package: str) -> MetaConfig:
        """Build metadata from the configured extension application."""
        module = import_module(f"{root_package}.app")
        extension_app = getattr(module, "ext_app", None)
        if extension_app is None:
            raise ConfigError(f"Extension app module '{root_package}.app' must export 'ext_app'")

        to_meta_config = getattr(extension_app, "to_meta_config", None)
        if not callable(to_meta_config):
            raise ConfigError(
                f"Extension app module '{root_package}.app' does not expose metadata generation"
            )
        meta_config = to_meta_config()
        if not isinstance(meta_config, MetaConfig):
            raise ConfigError("Generated extension metadata must be a MetaConfig instance")
        return meta_config

    @classmethod
    def _discover_extension_root_package(cls, base_path: Path) -> str:
        """Return the single top-level package that exposes app and settings modules."""
        candidates = [
            entry.name
            for entry in base_path.iterdir()
            if entry.is_dir()
            and (entry / "app.py").exists()
            and (entry / "settings.py").exists()
            and not entry.name.startswith(".")
        ]
        if len(candidates) != 1:
            raise ConfigError(
                "Unable to autodiscover the extension package. "
                "Expected exactly one top-level package with app.py and settings.py"
            )
        return candidates[0]


@lru_cache
def get_runtime_settings() -> RuntimeSettings:
    """Return the cached process-wide runtime settings singleton.

    Returns:
        The validated RuntimeSettings singleton.
    """
    return RuntimeSettings.load()
