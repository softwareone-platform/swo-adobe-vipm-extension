from mpt_extension_sdk.extension_app import ExtensionApp

from adobe_vipm.api.v2.api import api_router
from adobe_vipm.api.v2.orders import orders_router
from adobe_vipm.services.mpt.api_service import ExtensionMPTAPIService

ext_app = ExtensionApp(prefix="/api/v2", mpt_api_service_type=ExtensionMPTAPIService)
ext_app.include_router(orders_router)
ext_app.include_router(api_router)
