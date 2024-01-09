from django.apps import AppConfig

from .extension import ext


class ExtensionConfig(AppConfig):
    name = "adobe_vipm"
    extension = ext
