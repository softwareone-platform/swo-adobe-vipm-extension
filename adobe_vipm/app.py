from mpt_extension_sdk.extension_app import ExtensionApp

from adobe_vipm.api.v2.orders import orders_router
from adobe_vipm.flows.context import AdobeOrderContext
from adobe_vipm.services.mpt.api_service import ExtensionMPTAPIService

ext_app = ExtensionApp(
    prefix="/api/v2",
    mpt_api_service_type=ExtensionMPTAPIService,
    order_context_type=AdobeOrderContext,
)
ext_app.include_router(orders_router)
