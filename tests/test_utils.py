from freezegun import freeze_time

from adobe_vipm.adobe.constants import ThreeYearCommitmentStatus
from adobe_vipm.utils import get_commitment_start_date, get_partial_sku, map_by


def test_get_partial_sku():
    partial_sku = "SKU-111111"
    full_sku = f"{partial_sku}-extra_part"
    result = get_partial_sku(full_sku)
    assert result == partial_sku


def test_map_by():
    items = [
        {"id": 1, "value": "value_1"},
        {"id": 2, "value": "value_2"},
        {"id": 3, "value": "value_3"},
    ]

    expected = {
        1: {"id": 1, "value": "value_1"},
        2: {"id": 2, "value": "value_2"},
        3: {"id": 3, "value": "value_3"},
    }

    result = map_by("id", items)

    assert result == expected


@freeze_time("2024-06-01")
def test_get_commitment_start_date(adobe_customer_factory, adobe_commitment_factory):
    start_date = "2024-01-01"
    commitment = adobe_commitment_factory(
        status=ThreeYearCommitmentStatus.COMMITTED.value,
        start_date=start_date,
        end_date="2025-01-01",
    )
    customer = adobe_customer_factory(
        commitment=commitment,
        commitment_request=commitment,
    )

    commitment_start_date = get_commitment_start_date(customer)

    assert start_date == commitment_start_date.isoformat()
