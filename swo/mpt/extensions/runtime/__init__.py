from importlib.metadata import version

try:
    __version__ = version("swo-runtime")
except Exception:  # pragma: no cover
    __version__ = "0.0.0"


def get_version():
    return __version__
