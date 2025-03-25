from django.contrib import admin
from django.urls import path
from mpt_extension_sdk.runtime.utils import get_extension

urlpatterns = [
    path("admin/", admin.site.urls),
]

if (extension := get_extension(name="app_config", group="swo.mpt.ext")) and (api_urls := extension.api.urls):
    urlpatterns.append(path("api/", api_urls))
