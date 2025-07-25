import logging
from datetime import date, timedelta
from enum import Enum

from django.conf import settings
from mpt_extension_sdk.mpt_http.base import MPTClient
from mpt_extension_sdk.mpt_http.mpt import get_agreements_by_query
from mpt_extension_sdk.mpt_http.wrap_http_error import wrap_mpt_http_error

from adobe_vipm.adobe.constants import (
    ThreeYearCommitmentStatus,
)
from adobe_vipm.flows.constants import Param

logger = logging.getLogger(__name__)


def get_agreements_by_3yc_commitment_request_status(mpt_client, is_recommitment=False):
    param_external_id = (
        Param.THREE_YC_COMMITMENT_REQUEST_STATUS
        if not is_recommitment
        else Param.THREE_YC_RECOMMITMENT_REQUEST_STATUS
    )
    request_type_param_ext_id = (
        Param.THREE_YC if not is_recommitment else Param.THREE_YC_RECOMMITMENT
    )
    request_type_param_phase = (
        Param.PHASE_ORDERING if not is_recommitment else Param.PHASE_FULFILLMENT
    )

    enroll_status_condition = (
        "any(parameters.fulfillment,and("
        f"eq(externalId,{param_external_id}),"
        f"in(displayValue,({ThreeYearCommitmentStatus.REQUESTED},{ThreeYearCommitmentStatus.ACCEPTED}))"
        ")"
        ")"
    )
    request_3yc_condition = (
        f"any(parameters.{request_type_param_phase},and("
        f"eq(externalId,{request_type_param_ext_id}),"
        "like(displayValue,*Yes*)"
        ")"
        ")"
    )
    status_condition = "eq(status,Active)"
    product_condition = f"in(product.id,({','.join(settings.MPT_PRODUCTS_IDS)}))"

    rql_query = (
        f"and({status_condition},{enroll_status_condition},"
        f"{request_3yc_condition},{product_condition})&select=parameters"
    )
    return get_agreements_by_query(mpt_client, rql_query)


@wrap_mpt_http_error
def get_agreements_for_3yc_resubmit(mpt_client, is_recommitment=False):
    param_external_id = (
        Param.THREE_YC_COMMITMENT_REQUEST_STATUS
        if not is_recommitment
        else Param.THREE_YC_RECOMMITMENT_REQUEST_STATUS
    )

    request_type_param_ext_id = (
        Param.THREE_YC if not is_recommitment else Param.THREE_YC_RECOMMITMENT
    )
    request_type_param_phase = (
        Param.PHASE_ORDERING if not is_recommitment else Param.PHASE_FULFILLMENT
    )

    error_statuses = [
        ThreeYearCommitmentStatus.DECLINED,
        ThreeYearCommitmentStatus.NONCOMPLIANT,
        ThreeYearCommitmentStatus.EXPIRED,
    ]

    enroll_status_condition = (
        "any(parameters.fulfillment,and("
        f"eq(externalId,{param_external_id}),"
        "or("
        f"in(displayValue,({','.join(error_statuses)})),"
        "eq(displayValue,null())"
        ")"
        ")"
        ")"
    )
    request_3yc_condition = (
        f"any(parameters.{request_type_param_phase},and("
        f"eq(externalId,{request_type_param_ext_id}),"
        "like(displayValue,*Yes*)"
        ")"
        ")"
    )
    status_condition = "eq(status,Active)"
    product_condition = f"in(product.id,({','.join(settings.MPT_PRODUCTS_IDS)}))"

    rql_query = (
        f"and({status_condition},{enroll_status_condition},"
        f"{request_3yc_condition},{product_condition})&select=parameters"
    )
    return get_agreements_by_query(mpt_client, rql_query)


def get_agreements_for_3yc_recommitment(mpt_client):
    today = date.today()
    limit_date = today + timedelta(days=30)
    enroll_status_condition = (
        "any(parameters.fulfillment,and("
        f"eq(externalId,{Param.THREE_YC_ENROLL_STATUS}),"
        f"eq(displayValue,{ThreeYearCommitmentStatus.COMMITTED})"
        ")"
        ")"
    )
    recommitment_condition = (
        "any(parameters.fulfillment,and("
        f"eq(externalId,{Param.THREE_YC_RECOMMITMENT}),"
        "like(displayValue,*Yes*)"
        ")"
        ")"
    )
    enddate_gt_condition = (
        "any(parameters.ordering,and("
        f"eq(externalId,{Param.THREE_YC_END_DATE}),"
        f"gt(displayValue,{limit_date.isoformat()})"
        ")"
        ")"
    )
    enddate_le_condition = (
        "any(parameters.ordering,and("
        f"eq(externalId,{Param.THREE_YC_END_DATE}),"
        f"le(displayValue,{today.isoformat()})"
        ")"
        ")"
    )
    status_condition = "eq(status,Active)"
    product_condition = f"in(product.id,({','.join(settings.MPT_PRODUCTS_IDS)}))"

    all_conditions = (
        enroll_status_condition,
        recommitment_condition,
        enddate_gt_condition,
        enddate_le_condition,
        status_condition,
        product_condition,
    )

    rql_query = f"and({','.join(all_conditions)})&select=parameters"
    return get_agreements_by_query(mpt_client, rql_query)


def get_agreements_by_3yc_enroll_status(
    mpt_client: MPTClient, enroll_statuses: Enum, status: str = "Active"
):
    param_condition = (
        f"any(parameters.fulfillment,"
        f"and(eq(externalId,3YCEnrollStatus),in(displayValue,({','.join(enroll_statuses)}))))"
    )
    status_condition = f"eq(status,{status})"

    rql_query = (
        f"and({status_condition},{param_condition})"
        "&select=lines,parameters,subscriptions,product,listing"
    )
    return get_agreements_by_query(mpt_client, rql_query)
