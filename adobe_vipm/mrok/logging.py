from logging import config


def get_logging_config() -> dict:
    """Logging configuration."""
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "verbose": {
                "format": "{asctime} {name} {levelname} (pid: {process}) {message}",
                "style": "{",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "verbose",
                "stream": "ext://sys.stderr",
            },
        },
        "root": {
            "handlers": ["console"],
            "level": "INFO",
        },
        "loggers": {
            "mextmock": {
                "handlers": ["console"],
                "level": "INFO",
                "propagate": False,
            },
            "mrok": {
                "handlers": ["console"],
                "level": "INFO",
                "propagate": False,
            },
        },
    }


def setup_logging() -> None:
    """Setup logging."""
    logging_config = get_logging_config()
    config.dictConfig(logging_config)
