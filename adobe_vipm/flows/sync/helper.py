from mpt_extension_sdk.core.utils import MPTClient
from mpt_extension_sdk.mpt_http import mpt


def check_adobe_subscription_id(subscription_id: str, adobe_subscription: dict) -> bool:
    """Compares the subscription ID with the subscription ID from the Adobe subscription data."""
    return adobe_subscription.get("subscriptionId", "") == subscription_id


def manage_missing_prices_skus(
    agreement: dict,
    mpt_client: MPTClient,
    prices: dict,
    missing_prices_skus: list[str],
    line: dict,
    actual_sku: str,
) -> bool:
    """Manage missing prices SKUs."""
    if actual_sku not in prices:
        pricelist_id = agreement["listing"]["priceList"]["id"]
        prices_mpt = mpt.get_item_prices_by_pricelist_id(
            mpt_client, pricelist_id, line["item"]["id"]
        )
        if prices_mpt:
            prices[actual_sku] = prices_mpt[0]["unitPP"]
            missing_prices_skus.append(actual_sku)
        else:
            missing_prices_skus.append(actual_sku)
            return False

    return True
