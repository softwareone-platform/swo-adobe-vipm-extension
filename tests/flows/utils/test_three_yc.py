import pytest

from adobe_vipm.flows.utils.three_yc import is_3yc_commitment_ending_before_coterm


@pytest.mark.parametrize(
    ("end_date", "coterm_date", "expected"),
    [
        ("2026-06-30", "2026-07-01", True),
        ("2026-07-01", "2026-07-01", False),
        ("2027-01-01", "2026-07-01", False),
    ],
)
def test_is_3yc_commitment_ending_before_coterm(
    adobe_customer_factory, adobe_commitment_factory, end_date, coterm_date, expected
):
    customer = adobe_customer_factory(coterm_date=coterm_date)
    commitment = adobe_commitment_factory(end_date=end_date)

    result = is_3yc_commitment_ending_before_coterm(customer, commitment)  # act

    assert result is expected


def test_is_3yc_commitment_ending_before_coterm_without_coterm_date(
    adobe_customer_factory, adobe_commitment_factory
):
    customer = adobe_customer_factory(coterm_date=None)
    commitment = adobe_commitment_factory(end_date="2020-01-01")

    result = is_3yc_commitment_ending_before_coterm(customer, commitment)  # act

    assert result is False
