from django.conf import settings

if not settings.configured:
    from adobe_vipm.mrok.config import settings
