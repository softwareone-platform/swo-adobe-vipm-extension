import os
import socket
import uuid
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Self, override

from mpt_extension_sdk_v6.errors.runtime import ConfigError
from mpt_extension_sdk_v6.runtime.models import MetaConfig
from mpt_extension_sdk_v6.settings.base import BaseSettings


@dataclass(frozen=True)
class RuntimeSettings(BaseSettings):
    """Runtime settings loaded exclusively from environment variables."""

    ext_api_key: str
    base_url: str
    extension_id: str
    mpt_api_base_url: str
    mpt_api_token: str
    external_id: str
    identity_file_path: Path
    meta_config: MetaConfig
    route_prefix: str
    handlers_modules: list[str]
    local_host: str
    local_port: int
    local_reload: bool
    local_workers: int
    log_level: str
    ziti_workers: int
    ziti_reload: bool

    def __post_init__(self) -> None:
        """Validate settings immediately after construction."""
        self.validate()

    def validate(self) -> None:
        """Raise ConfigError for any missing required setting.

        Raises:
            ConfigError: When a required environment variable is absent or empty.
        """
        required_strings = [
            (self.base_url, "SDK extension registration URL is required (SDK_EXTENSION_URL)"),
            (self.extension_id, "Extension ID is required (SDK_EXTENSION_ID)"),
            (self.ext_api_key, "SDK API key is required (SDK_EXTENSION_API_KEY)"),
            (self.mpt_api_base_url, "MPT API base URL is required (MPT_API_BASE_URL)"),
            (self.mpt_api_token, "MPT API token is required (MPT_API_TOKEN)"),
        ]
        for attr_value, message in required_strings:
            if not attr_value:
                raise ConfigError(message)
        if not self.handlers_modules:
            raise ConfigError("At least one handlers module is required (SDK_HANDLERS_MODULES)")

    @override
    @classmethod
    def load(cls) -> Self:
        configured_external_id = os.getenv("SDK_EXTENSION_EXTERNAL_ID", "")
        if configured_external_id:
            external_id = configured_external_id
        else:
            hostname = socket.gethostname().strip()
            external_id = hostname or f"{uuid.getnode():012x}"  # noqa: WPS237

        identity_file_path_env = os.getenv("SDK_IDENTITY_FILE_PATH", "")
        if identity_file_path_env:
            identity_file_path = Path(identity_file_path_env)
        else:
            identity_file_path = Path.cwd() / f"{external_id}_identity.json"

        sdk_handler_modules = os.getenv("SDK_HANDLERS_MODULES", "").split(",")
        handlers_modules = [module.strip() for module in sdk_handler_modules if module.strip()]

        return cls(
            ext_api_key=os.getenv("SDK_EXTENSION_API_KEY", ""),
            base_url=os.getenv("SDK_EXTENSION_URL", ""),
            extension_id=os.getenv("SDK_EXTENSION_ID", ""),
            mpt_api_base_url=os.getenv("MPT_API_BASE_URL", ""),
            mpt_api_token=os.getenv("MPT_API_TOKEN", ""),
            external_id=external_id,
            identity_file_path=identity_file_path,
            meta_config=MetaConfig.from_file(Path.cwd() / "meta.yaml"),
            route_prefix=os.getenv("SDK_ROUTE_PREFIX", "/api/v2"),
            handlers_modules=handlers_modules,
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            local_host=os.getenv("SDK_LOCAL_HOST", "0.0.0.0"),  # noqa: S104
            local_port=int(os.getenv("SDK_LOCAL_PORT", "8080")),
            local_reload=os.getenv("SDK_LOCAL_RELOAD", "true").lower() in {"true", "1", "yes"},
            local_workers=int(os.getenv("SDK_LOCAL_WORKERS", "1")),
            ziti_workers=int(os.getenv("SDK_ZITI_WORKERS", "1")),
            ziti_reload=os.getenv("SDK_ZITI_RELOAD", "true").lower() in {"true", "1", "yes"},
        )


@lru_cache
def get_runtime_settings() -> RuntimeSettings:
    """Return the cached process-wide runtime settings singleton.

    The instance is created on the first call and reused for the lifetime of
    the process.  In tests, call ``get_runtime_settings.cache_clear()``
    to reset the cache between test cases.

    Returns:
        The validated: class:`RuntimeSettings` singleton.
    """
    return RuntimeSettings.load()
