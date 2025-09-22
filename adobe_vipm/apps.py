from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from mpt_extension_sdk.runtime.djapp.apps import DjAppConfig

from adobe_vipm.extension import ext


class ExtensionConfig(DjAppConfig):
    """Django configuration for extension."""

    name = "adobe_vipm"
    verbose_name = "SWO Adobe VIPM Extension"
    extension = ext

    # TODO: why it is here, but not in SDK???
    def extension_ready(self):
        """Check for initial configuration for extension."""
        error_msgs = []

        for product_id in settings.MPT_PRODUCTS_IDS:
            if (
                "WEBHOOKS_SECRETS" not in settings.EXTENSION_CONFIG
                or product_id not in settings.EXTENSION_CONFIG["WEBHOOKS_SECRETS"]
            ):
                msg = (
                    f"The webhook secret for {product_id} is not found. "
                    f"Please, specify it in EXT_WEBHOOKS_SECRETS environment variable."
                )
                error_msgs.append(msg)

        if error_msgs:
            raise ImproperlyConfigured("\n".join(error_msgs))
