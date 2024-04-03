from django.apps import AppConfig
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


class DjAppConfig(AppConfig):
    name = "swo.mpt.extensions.runtime.djapp"

    def ready(self):
        if not hasattr(settings, 'MPT_PRODUCTS_IDS') or not settings.MPT_PRODUCTS_IDS:
            raise ImproperlyConfigured(f"Extension {self.verbose_name} is not properly configured. MPT_PRODUCTS_IDS is missing or empty.")

        self.extension_ready()

    def extension_ready(self):
        pass
