import os

from mpt_extension_sdk.mpt_http.base import MPTClient

mpt_client = MPTClient(os.getenv("MPT_API_BASE_URL"), os.getenv("MPT_API_TOKEN"))
mpt_o_client = MPTClient(os.getenv("MPT_API_BASE_URL"), os.getenv("MPT_API_TOKEN_OPERATIONS"))
