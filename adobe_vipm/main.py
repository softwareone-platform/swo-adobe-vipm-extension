from mrok.agent import ziticorn

from adobe_vipm.mrok.bootstrap import bootstrap_extension_instance
from adobe_vipm.mrok.config import load_runtime_settings
from adobe_vipm.mrok.logging import setup_logging


def run() -> None:
    """Run FastAPI extension app using ziticorn."""
    setup_logging()
    settings = load_runtime_settings()
    bootstrap_extension_instance(settings)
    ziticorn.run("adobe_vipm.mrok.api.app:app", str(settings.identity_file), server_workers=1)


if __name__ == "__main__":
    run()
