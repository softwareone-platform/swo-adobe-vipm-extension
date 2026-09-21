"""
Candidate flexible discounts for the normal order flow (NEW and upsize lines).

Retrieval and filtering of the codes the Airtable discount store offers a
line, per the "Improve flex discounts in normal order flow" design: the
candidate set is the store shortlist matched to the line SKU (open, closed
and reusable codes, the reusable codes the customer already holds included),
gated on order type, category, validity window, country and the
once-per-customer rule, then pre-filtered against the customer's commitment.

Every gate keeps a code whose data is absent (the subsystem's asymmetry
rule): an over-permissive set shows a code Adobe's preview later rejects,
which is recoverable, while an over-restrictive one hides a code the
customer was entitled to, with no backstop. Rows still pending enrichment
are therefore kept too: their uncurated order types and commitment flags
constrain nothing.

The ranking by net price and the preview cascade are not part of this module.
"""

import datetime as dt
import logging
import re
from dataclasses import dataclass
from enum import StrEnum

from adobe_vipm.adobe.constants import ThreeYearCommitmentStatus
from adobe_vipm.airtable.models import (
    DISCOUNT_CATEGORY_INTRO,
    DISCOUNT_OFFER_IDS_SEPARATOR,
    DISCOUNT_ORDER_TYPE_NEW,
    DISCOUNT_SOURCE_OPEN,
    get_customer_discount_redemptions,
    get_discount_values,
    get_visible_discount_codes,
)
from adobe_vipm.flows.constants import Param
from adobe_vipm.utils import get_3yc_commitment

logger = logging.getLogger(__name__)

# Commitment statuses under which the customer's lines are priced as 3YC.
THREE_YC_COMMITMENT_STATUSES = frozenset((
    ThreeYearCommitmentStatus.COMMITTED,
    ThreeYearCommitmentStatus.ACTIVE,
    ThreeYearCommitmentStatus.REQUESTED,
    ThreeYearCommitmentStatus.ACCEPTED,
))
THREE_YC_CHECKED = ("Yes",)
DEPLOYMENT_COUNTRY_PATTERN = "{} ?- ?([A-Z]{{2,}})"
DEPLOYMENTS_SEPARATOR = ","


class CommitmentType(StrEnum):
    """The customer's commitment term the candidates are matched against."""

    ANNUAL = "ANNUAL"
    THREE_YC = "THREE_YC"
    UNKNOWN = "UNKNOWN"


class LineType(StrEnum):
    """The kind of order line a candidate is assembled for."""

    NEW = "NEW"
    UPSIZE = "UPSIZE"


@dataclass(frozen=True)
class FlexDiscountCandidate:
    """A store code eligible for a line, with what the later ranking needs."""

    code: str
    source: str
    category: str
    discount_type: str
    adobe_discount_id: str
    reusable: bool
    supports_annual: bool
    supports_three_yc: bool
    held: bool
    amount: float | None
    currency: str | None

    @property
    def is_closed(self) -> bool:
        """Whether the code is a closed (customer-specific) one."""
        return self.source != DISCOUNT_SOURCE_OPEN


def get_discount_country(customer_data: dict) -> str:
    """
    Return the country the discounts are looked up for.

    The customer address country, overridden by the deployment country when
    the order targets a deployment (existing behaviour of the Adobe lookup).

    Args:
        customer_data: Context customer data (address, deploymentId, deployments).

    Returns:
        str: ISO country code.
    """
    country = customer_data["address"]["country"]
    deployment_id = customer_data.get(Param.DEPLOYMENT_ID.value)
    if deployment_id:
        deployment_country = _get_deployment_country(
            deployment_id,
            customer_data.get(Param.DEPLOYMENTS.value) or "",
        )
        if deployment_country:
            country = deployment_country
            logger.info(
                "Flex discounts: using deployment %s country override %s",
                deployment_id,
                country,
            )
    return country


def _get_deployment_country(deployment_id: str, deployments: str) -> str | None:
    """
    Reads the country of the deployment from the deployments parameter.

    The parameter holds one "<deployment id> - <country>" entry per comma
    separated deployment, so every entry is matched in turn: the targeted
    deployment is not necessarily the first one.
    """
    pattern = DEPLOYMENT_COUNTRY_PATTERN.format(re.escape(deployment_id))
    for entry in deployments.split(DEPLOYMENTS_SEPARATOR):
        match = re.fullmatch(pattern, entry.strip(), re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def get_commitment_type(adobe_customer: dict | None, customer_data: dict) -> CommitmentType:
    """
    Return the customer's commitment term for the 3YC pre-filter.

    THREE_YC when the Adobe customer holds or has requested a three-year
    commitment, or when the order requests one (3YC checkbox); ANNUAL when the
    customer is known and neither holds nor requests one; UNKNOWN when the
    Adobe customer is not available yet, so that no code is excluded.

    Args:
        adobe_customer: Adobe customer, None when not retrieved yet.
        customer_data: Context customer data (3YC checkbox).

    Returns:
        CommitmentType: The commitment term.
    """
    if tuple(customer_data.get(Param.THREE_YC.value) or ()) == THREE_YC_CHECKED:
        return CommitmentType.THREE_YC
    if adobe_customer is None:
        return CommitmentType.UNKNOWN
    status = get_3yc_commitment(adobe_customer).get("status")
    if status in THREE_YC_COMMITMENT_STATUSES:
        return CommitmentType.THREE_YC
    return CommitmentType.ANNUAL


def get_flex_discount_candidates(  # noqa: WPS211
    *,
    market_segment: str,
    customer_id: str | None,
    country: str,
    commitment: CommitmentType,
    new_lines: list[dict],
    upsize_lines: list[dict],
    owned_partial_skus: set[str] | None = None,
) -> dict[str, list[FlexDiscountCandidate]]:
    """
    Retrieve and filter the candidate codes of every NEW and upsize line.

    Reads the store once for the order (visible codes, their values and the
    customer's redemptions of them) and applies the per-line gates.

    Args:
        market_segment: Adobe market segment (COM, GOV, EDU).
        customer_id: Adobe customer id, None when the customer does not exist yet.
        country: Country the discounts are looked up for (see get_discount_country).
        commitment: The customer's commitment term (see get_commitment_type).
        new_lines: MPT order lines purchased as new.
        upsize_lines: MPT order lines increased in quantity.
        owned_partial_skus: Partial SKUs the customer already owns, None when unknown.

    Returns:
        dict: Candidates per MPT line id, unranked; lines without candidates are absent.
    """
    if not new_lines and not upsize_lines:
        return {}
    discount_codes = get_visible_discount_codes(market_segment, customer_id)
    codes = [row.code for row in discount_codes]
    discount_values = get_discount_values(codes, market_segment)
    redemptions = get_customer_discount_redemptions(customer_id, codes)
    logger.info(
        "Flex discounts: %s visible code(s) for segment %s and customer %s: %s",
        len(codes),
        market_segment,
        customer_id or "-",
        ", ".join(codes),
    )
    candidates_by_line = {}
    typed_lines = [(line, LineType.NEW) for line in new_lines]
    typed_lines.extend((line, LineType.UPSIZE) for line in upsize_lines)
    for line, line_type in typed_lines:
        candidates = filter_candidates(
            discount_codes,
            discount_values,
            redemptions,
            line_partial_sku=line["item"]["externalIds"]["vendor"],
            line_type=line_type,
            country=country,
            commitment=commitment,
            owned_partial_skus=owned_partial_skus,
        )
        if candidates:
            candidates_by_line[line["id"]] = candidates
    return candidates_by_line


def filter_candidates(  # noqa: WPS211
    discount_codes: list,
    discount_values: list,
    redemptions: list,
    *,
    line_partial_sku: str,
    line_type: LineType,
    country: str,
    commitment: CommitmentType,
    owned_partial_skus: set[str] | None = None,
    today: dt.date | None = None,
) -> list[FlexDiscountCandidate]:
    """
    Keep the store codes a line can carry, in store order (unranked).

    Args:
        discount_codes: DiscountCode rows visible to the customer.
        discount_values: DiscountValue rows of those codes.
        redemptions: DiscountRedemption rows of the customer for those codes.
        line_partial_sku: The line's 10-char partial SKU.
        line_type: NEW or UPSIZE.
        country: Country the discounts are looked up for.
        commitment: The customer's commitment term.
        owned_partial_skus: Partial SKUs the customer already owns, None when unknown.
        today: Reference date for the validity window, defaults to today (UTC).

    Returns:
        list[FlexDiscountCandidate]: The eligible codes.
    """
    today = today or dt.datetime.now(tz=dt.UTC).date()
    redeemed_codes = {redemption.code for redemption in redemptions}
    amounts_by_code = _group_amounts_by_code(discount_values)
    candidates = []
    for row in discount_codes:
        amounts = amounts_by_code.get(row.code, [])
        if not _is_eligible(
            row,
            amounts,
            line_partial_sku=line_partial_sku,
            line_type=line_type,
            country=country,
            commitment=commitment,
            owned_partial_skus=owned_partial_skus,
            redeemed=row.code in redeemed_codes,
            today=today,
        ):
            continue
        candidates.append(_to_candidate(row, _select_amount(amounts, country), redeemed_codes))
    return candidates


def _is_eligible(  # noqa: WPS211
    row,
    amounts: list,
    *,
    line_partial_sku: str,
    line_type: LineType,
    country: str,
    commitment: CommitmentType,
    owned_partial_skus: set[str] | None,
    redeemed: bool,
    today: dt.date,
) -> bool:
    gates = (
        matches_target_sku(row, line_partial_sku),
        matches_qualifying_skus(row, owned_partial_skus),
        allows_order_type(row),
        allows_category(row, line_type),
        is_within_window(row, today),
        is_offered_in_country(amounts, country),
        is_redeemable(row, redeemed=redeemed),
        matches_commitment(row, commitment),
    )
    return all(gates)


def matches_target_sku(row, line_partial_sku: str) -> bool:
    """Keep a code whose target offers cover the line SKU (an empty set is any)."""
    targets = _split_skus(row.target_offer_ids)
    return not targets or line_partial_sku in targets


def matches_qualifying_skus(row, owned_partial_skus: set[str] | None) -> bool:
    """Keep a code whose prerequisite offers the customer owns, or when ownership is unknown."""
    qualifying = _split_skus(row.qualifying_offer_ids)
    if not qualifying or owned_partial_skus is None:
        return True
    return bool(qualifying & owned_partial_skus)


def allows_order_type(row) -> bool:
    """Keep a code applicable to NEW orders (an empty list is any order type)."""
    applicable = row.applicable_order_types or []
    return not applicable or DISCOUNT_ORDER_TYPE_NEW in applicable


def allows_category(row, line_type: LineType) -> bool:
    """Keep INTRO codes on net-new lines only, never on upsize lines."""
    return row.category != DISCOUNT_CATEGORY_INTRO or line_type is LineType.NEW


def is_within_window(row, today: dt.date) -> bool:
    """
    Keep a code whose usable window contains today.

    The window closes at end_date, extended to discount_lock_end_date for a
    reusable code (the lock keeps a held code applicable past its end date).
    A missing bound leaves that side of the window open.
    """
    start_date = _to_date(row.start_date)
    usable_until = _to_date(row.discount_lock_end_date if row.reusable else row.end_date)
    if start_date and today < start_date:
        return False
    return usable_until is None or today <= usable_until


def is_offered_in_country(amounts: list, country: str) -> bool:
    """
    Keep a code priced in the country.

    A code is offered in a country when it has a value row for it or a
    country-agnostic (percentage) row. A code with no value rows is kept:
    it cannot be priced locally, but the data gap must not hide it.
    """
    return not amounts or any(_is_amount_for_country(amount, country) for amount in amounts)


def is_redeemable(row, *, redeemed: bool) -> bool:
    """Drop a single-use code the customer already redeemed; a reusable one stays valid."""
    return bool(row.reusable) or not redeemed


def matches_commitment(row, commitment: CommitmentType) -> bool:
    """
    Exclude a code only on a positive contradiction with the commitment.

    A code supporting 3YC only is excluded for an annual customer, one
    supporting annual only for a 3YC customer. A code supporting both, or
    declaring neither, stays; so does every code when the commitment is unknown.
    """
    supports_annual = bool(row.supports_annual)
    supports_three_yc = bool(row.supports_3yc)
    if commitment is CommitmentType.UNKNOWN or supports_annual == supports_three_yc:
        return True
    if commitment is CommitmentType.THREE_YC:
        return supports_three_yc
    return supports_annual


def _to_candidate(row, amount, redeemed_codes: set[str]) -> FlexDiscountCandidate:
    return FlexDiscountCandidate(
        code=row.code,
        source=row.source or "",
        category=row.category or "",
        discount_type=row.discount_type or "",
        adobe_discount_id=row.adobe_discount_id or "",
        reusable=bool(row.reusable),
        supports_annual=bool(row.supports_annual),
        supports_three_yc=bool(row.supports_3yc),
        held=bool(row.reusable) and row.code in redeemed_codes,
        amount=None if amount is None else amount.value,
        currency=None if amount is None else (amount.currency or None),
    )


def _group_amounts_by_code(discount_values: list) -> dict[str, list]:
    amounts_by_code: dict[str, list] = {}
    for amount in discount_values:
        amounts_by_code.setdefault(amount.code, []).append(amount)
    return amounts_by_code


def _select_amount(amounts: list, country: str):
    """Pick the country row of a fixed code, or the country-less row of a percentage one."""
    country_amounts = [amount for amount in amounts if amount.country == country]
    if country_amounts:
        return country_amounts[0]
    return next((amount for amount in amounts if not amount.country), None)


def _is_amount_for_country(amount, country: str) -> bool:
    return not amount.country or amount.country == country


def _split_skus(csv: str | None) -> set[str]:
    skus = (sku.strip() for sku in (csv or "").split(DISCOUNT_OFFER_IDS_SEPARATOR))
    return {sku for sku in skus if sku}


def _to_date(raw_date) -> dt.date | None:
    if raw_date is None:
        return None
    if isinstance(raw_date, dt.datetime):
        return raw_date.date()
    if isinstance(raw_date, dt.date):
        return raw_date
    return dt.date.fromisoformat(str(raw_date)[:10])
