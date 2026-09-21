import datetime as dt
from types import SimpleNamespace

import pytest

from adobe_vipm.flows.utils.flex_discounts import (
    CommitmentType,
    FlexDiscountCandidate,
    LineType,
    filter_candidates,
    get_commitment_type,
    get_discount_country,
    get_flex_discount_candidates,
    matches_commitment,
)

TODAY = dt.date(2026, 9, 10)


def make_code(**overrides):
    fields = {
        "code": "OPEN_10",
        "source": "API",
        "category": "STANDARD",
        "discount_type": "PERCENTAGE",
        "adobe_discount_id": "adobe-1",
        "reusable": False,
        "supports_annual": False,
        "supports_3yc": False,
        "start_date": dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        "end_date": dt.datetime(2026, 12, 31, tzinfo=dt.UTC),
        "discount_lock_end_date": None,
        "target_offer_ids": "65304578CA",
        "qualifying_offer_ids": "",
        "applicable_order_types": ["NEW"],
        "target_customer_id": "",
        "enrichment_status": "COMPLETE",
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def make_value(code="OPEN_10", country=None, currency=None, value=10):
    return SimpleNamespace(code=code, country=country, currency=currency, value=value)


def make_redemption(code):
    return SimpleNamespace(code=code, customer_id="P100")


def run_filter(codes, values=(), redemptions=(), **overrides):
    kwargs = {
        "line_partial_sku": "65304578CA",
        "line_type": LineType.NEW,
        "country": "US",
        "commitment": CommitmentType.ANNUAL,
        "today": TODAY,
    }
    kwargs.update(overrides)
    return filter_candidates(list(codes), list(values), list(redemptions), **kwargs)


def test_filter_candidates_returns_candidate_with_percentage_value():
    result = run_filter([make_code()], [make_value(value=15)])  # act

    assert result == [
        FlexDiscountCandidate(
            code="OPEN_10",
            source="API",
            category="STANDARD",
            discount_type="PERCENTAGE",
            adobe_discount_id="adobe-1",
            reusable=False,
            supports_annual=False,
            supports_three_yc=False,
            held=False,
            amount=15,
            currency=None,
        )
    ]
    assert result[0].is_closed is False


@pytest.mark.parametrize(
    ("target_offer_ids", "expected"),
    [
        ("65304578CA", True),
        ("65304578CA,65304579CA", True),
        ("", True),
        (None, True),
        ("65304579CA", False),
    ],
)
def test_filter_candidates_target_sku_gate(target_offer_ids, expected):
    result = run_filter([make_code(target_offer_ids=target_offer_ids)])  # act

    assert bool(result) is expected


@pytest.mark.parametrize(
    ("qualifying_offer_ids", "owned", "expected"),
    [
        ("", {"65304500CA"}, True),
        ("65304500CA", None, True),
        ("65304500CA,65304501CA", {"65304501CA"}, True),
        ("65304500CA", {"65304999CA"}, False),
        ("65304500CA", set(), False),
    ],
)
def test_filter_candidates_qualifying_sku_gate(qualifying_offer_ids, owned, expected):
    result = run_filter(
        [make_code(qualifying_offer_ids=qualifying_offer_ids)], owned_partial_skus=owned
    )  # act

    assert bool(result) is expected


@pytest.mark.parametrize(
    ("applicable_order_types", "expected"),
    [(["NEW"], True), (["NEW", "RENEWAL"], True), ([], True), (None, True), (["RENEWAL"], False)],
)
def test_filter_candidates_order_type_gate(applicable_order_types, expected):
    result = run_filter([make_code(applicable_order_types=applicable_order_types)])  # act

    assert bool(result) is expected


@pytest.mark.parametrize(
    ("category", "line_type", "expected"),
    [
        ("INTRO", LineType.NEW, True),
        ("INTRO", LineType.UPSIZE, False),
        ("STANDARD", LineType.UPSIZE, True),
    ],
)
def test_filter_candidates_intro_gate(category, line_type, expected):
    result = run_filter([make_code(category=category)], line_type=line_type)  # act

    assert bool(result) is expected


@pytest.mark.parametrize(
    ("start_date", "end_date", "reusable", "lock_end_date", "expected"),
    [
        (dt.date(2026, 1, 1), dt.date(2026, 12, 31), False, None, True),
        (dt.date(2026, 9, 10), dt.date(2026, 9, 10), False, None, True),
        (dt.date(2026, 9, 11), dt.date(2026, 12, 31), False, None, False),
        (dt.date(2026, 1, 1), dt.date(2026, 9, 9), False, None, False),
        (dt.date(2026, 1, 1), dt.date(2026, 9, 9), True, dt.date(2031, 12, 31), True),
        (dt.date(2026, 1, 1), dt.date(2026, 12, 31), True, dt.date(2026, 9, 9), False),
        (None, None, False, None, True),
        ("2026-01-01", "2026-12-31", False, None, True),
    ],
)
def test_filter_candidates_window_gate(start_date, end_date, reusable, lock_end_date, expected):
    code = make_code(
        start_date=start_date,
        end_date=end_date,
        reusable=reusable,
        discount_lock_end_date=lock_end_date,
    )

    result = run_filter([code])  # act

    assert bool(result) is expected


def test_filter_candidates_country_gate_keeps_country_and_percentage_rows():
    codes = [
        make_code(code="FIXED_US", discount_type="FIXED_DISCOUNT"),
        make_code(code="FIXED_DE", discount_type="FIXED_DISCOUNT"),
        make_code(code="PERCENT"),
        make_code(code="UNPRICED"),
    ]
    values = [
        make_value("FIXED_US", country="US", currency="USD", value=20),
        make_value("FIXED_DE", country="DE", currency="EUR", value=20),
        make_value("PERCENT", value=10),
    ]

    result = run_filter(codes, values)  # act

    assert [candidate.code for candidate in result] == ["FIXED_US", "PERCENT", "UNPRICED"]
    assert (result[0].amount, result[0].currency) == (20, "USD")
    assert (result[1].amount, result[1].currency) == (10, None)
    assert (result[2].amount, result[2].currency) == (None, None)


def test_filter_candidates_prefers_country_row_over_country_less_row():
    values = [make_value(value=10), make_value(country="US", currency="USD", value=25)]

    result = run_filter([make_code()], values)  # act

    assert (result[0].amount, result[0].currency) == (25, "USD")


def test_filter_candidates_once_per_customer_and_held_reusables():
    codes = [
        make_code(code="SINGLE_USED"),
        make_code(code="SINGLE_NEW"),
        make_code(
            code="HELD_REUSABLE",
            reusable=True,
            end_date=dt.date(2026, 1, 31),
            discount_lock_end_date=dt.date(2031, 12, 31),
        ),
    ]
    redemptions = [make_redemption("SINGLE_USED"), make_redemption("HELD_REUSABLE")]

    result = run_filter(codes, redemptions=redemptions)  # act

    assert [(candidate.code, candidate.held) for candidate in result] == [
        ("SINGLE_NEW", False),
        ("HELD_REUSABLE", True),
    ]


@pytest.mark.parametrize(
    ("supports_annual", "supports_3yc", "commitment", "expected"),
    [
        (False, True, CommitmentType.ANNUAL, False),
        (True, False, CommitmentType.THREE_YC, False),
        (False, True, CommitmentType.THREE_YC, True),
        (True, False, CommitmentType.ANNUAL, True),
        (True, True, CommitmentType.ANNUAL, True),
        (True, True, CommitmentType.THREE_YC, True),
        (False, False, CommitmentType.ANNUAL, True),
        (False, False, CommitmentType.THREE_YC, True),
        (False, True, CommitmentType.UNKNOWN, True),
        (True, False, CommitmentType.UNKNOWN, True),
    ],
)
def test_matches_commitment(supports_annual, supports_3yc, commitment, expected):
    code = make_code(supports_annual=supports_annual, supports_3yc=supports_3yc)

    result = matches_commitment(code, commitment)  # act

    assert result is expected


def test_filter_candidates_applies_commitment_pre_filter():
    codes = [
        make_code(code="THREE_YC_ONLY", supports_3yc=True),
        make_code(code="ANNUAL_ONLY", supports_annual=True),
        make_code(code="BOTH", supports_annual=True, supports_3yc=True),
    ]

    result = run_filter(codes, commitment=CommitmentType.THREE_YC)  # act

    assert [candidate.code for candidate in result] == ["THREE_YC_ONLY", "BOTH"]


def test_filter_candidates_keeps_pending_enrichment_rows():
    result = run_filter([make_code(enrichment_status="PENDING", applicable_order_types=None)])

    assert len(result) == 1


def test_filter_candidates_closed_code():
    code = make_code(code="RETAIN", source="Operations", target_customer_id="P100")

    result = run_filter([code])  # act

    assert result[0].is_closed is True


@pytest.mark.parametrize(
    ("customer_data", "expected"),
    [
        ({"address": {"country": "US"}, "deploymentId": None, "deployments": None}, "US"),
        (
            {
                "address": {"country": "US"},
                "deploymentId": "deployment-1",
                "deployments": "deployment-1 - DE,deployment-2 - FR",
            },
            "DE",
        ),
        (
            {
                "address": {"country": "US"},
                "deploymentId": "deployment-2",
                "deployments": "deployment-1 - DE,deployment-2 - FR",
            },
            "FR",
        ),
        (
            {
                "address": {"country": "US"},
                "deploymentId": "deployment-3",
                "deployments": "deployment-1 - DE,deployment-2 - FR,deployment-3 - ES",
            },
            "ES",
        ),
        (
            {
                "address": {"country": "US"},
                "deploymentId": "deployment-1",
                "deployments": "deployment-10 - DE,deployment-1 - FR",
            },
            "FR",
        ),
        (
            {
                "address": {"country": "US"},
                "deploymentId": "deployment-2",
                "deployments": "deployment-1 - DE",
            },
            "US",
        ),
    ],
)
def test_get_discount_country(customer_data, expected):
    result = get_discount_country(customer_data)  # act

    assert result == expected


@pytest.mark.parametrize(
    ("commitment_status", "three_yc_checkbox", "expected"),
    [
        (None, ["Yes"], CommitmentType.THREE_YC),
        ("COMMITTED", None, CommitmentType.THREE_YC),
        ("ACTIVE", None, CommitmentType.THREE_YC),
        ("REQUESTED", None, CommitmentType.THREE_YC),
        ("ACCEPTED", None, CommitmentType.THREE_YC),
        ("EXPIRED", None, CommitmentType.ANNUAL),
        (None, None, CommitmentType.ANNUAL),
    ],
)
def test_get_commitment_type(
    adobe_customer_factory,
    adobe_commitment_factory,
    commitment_status,
    three_yc_checkbox,
    expected,
):
    commitment = adobe_commitment_factory(status=commitment_status) if commitment_status else None
    customer = adobe_customer_factory(commitment=commitment)

    result = get_commitment_type(customer, {"3YC": three_yc_checkbox})  # act

    assert result is expected


def test_get_commitment_type_without_adobe_customer():
    result = get_commitment_type(None, {"3YC": None})  # act

    assert result is CommitmentType.UNKNOWN


def test_get_flex_discount_candidates(mocker):
    codes = [
        make_code(code="NEW_ONLY", category="INTRO"),
        make_code(code="ANY", target_offer_ids="65304578CA,65304579CA"),
        make_code(code="OTHER_SKU", target_offer_ids="65304999CA"),
    ]
    mocked_codes = mocker.patch(
        "adobe_vipm.flows.utils.flex_discounts.get_visible_discount_codes",
        return_value=codes,
    )
    mocked_values = mocker.patch(
        "adobe_vipm.flows.utils.flex_discounts.get_discount_values",
        return_value=[make_value("ANY", value=5)],
    )
    mocked_redemptions = mocker.patch(
        "adobe_vipm.flows.utils.flex_discounts.get_customer_discount_redemptions",
        return_value=[],
    )
    new_line = {"id": "ALI-1", "item": {"externalIds": {"vendor": "65304578CA"}}}
    upsize_line = {"id": "ALI-2", "item": {"externalIds": {"vendor": "65304579CA"}}}
    no_match_line = {"id": "ALI-3", "item": {"externalIds": {"vendor": "65304000CA"}}}

    result = get_flex_discount_candidates(
        market_segment="COM",
        customer_id="P100",
        country="US",
        commitment=CommitmentType.ANNUAL,
        new_lines=[new_line, no_match_line],
        upsize_lines=[upsize_line],
    )  # act

    assert {line_id: [c.code for c in cands] for line_id, cands in result.items()} == {
        "ALI-1": ["NEW_ONLY", "ANY"],
        "ALI-2": ["ANY"],
    }
    mocked_codes.assert_called_once_with("COM", "P100")
    mocked_values.assert_called_once_with(["NEW_ONLY", "ANY", "OTHER_SKU"], "COM")
    mocked_redemptions.assert_called_once_with("P100", ["NEW_ONLY", "ANY", "OTHER_SKU"])


def test_get_flex_discount_candidates_without_lines(mocker):
    mocked_codes = mocker.patch("adobe_vipm.flows.utils.flex_discounts.get_visible_discount_codes")

    result = get_flex_discount_candidates(
        market_segment="COM",
        customer_id="P100",
        country="US",
        commitment=CommitmentType.ANNUAL,
        new_lines=[],
        upsize_lines=[],
    )  # act

    assert result == {}
    mocked_codes.assert_not_called()
