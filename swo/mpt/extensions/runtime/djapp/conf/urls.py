from django.contrib import admin
from django.urls import path

from swo.mpt.extensions.runtime.utils import get_extension

urlpatterns = [
    path("admin/", admin.site.urls),
]

if (extension := get_extension()) and (api_urls := extension.api.urls):
    urlpatterns.append(path("api/", api_urls))
