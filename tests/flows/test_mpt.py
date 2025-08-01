import pytest
from freezegun import freeze_time

from adobe_vipm.adobe.constants import (
    ThreeYearCommitmentStatus,
)
from adobe_vipm.flows.constants import Param
from adobe_vipm.flows.mpt import (
    get_agreements_by_3yc_commitment_request_status,
    get_agreements_by_3yc_enroll_status,
    get_agreements_for_3yc_recommitment,
    get_agreements_for_3yc_resubmit,
)


@pytest.mark.parametrize("is_recommitment", [True, False])
def test_get_agreements_by_3yc_commitment_request_status(mocker, settings, is_recommitment):
    param_external_id = (
        Param.THREE_YC_COMMITMENT_REQUEST_STATUS.value
        if not is_recommitment
        else Param.THREE_YC_RECOMMITMENT_REQUEST_STATUS.value
    )
    request_type_param_ext_id = (
        Param.THREE_YC.value if not is_recommitment else Param.THREE_YC_RECOMMITMENT.value
    )
    request_type_param_phase = "ordering" if not is_recommitment else "fulfillment"

    enroll_status_condition = (
        "any(parameters.fulfillment,and("
        f"eq(externalId,{param_external_id}),"
        f"in(displayValue,({ThreeYearCommitmentStatus.REQUESTED.value},{ThreeYearCommitmentStatus.ACCEPTED.value}))"
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
        f"and({status_condition},{enroll_status_condition}"
        f",{request_3yc_condition},{product_condition})&select=parameters"
    )

    mocked_get_by_query = mocker.patch(
        "adobe_vipm.flows.mpt.get_agreements_by_query",
        return_value=[{"id": "AGR-0001"}],
    )

    mocked_client = mocker.MagicMock()

    assert get_agreements_by_3yc_commitment_request_status(
        mocked_client, is_recommitment=is_recommitment
    ) == [{"id": "AGR-0001"}]
    mocked_get_by_query.assert_called_once_with(mocked_client, rql_query)


@freeze_time("2024-01-01 03:00:00")
def test_get_agreements_for_3yc_recommitment(mocker, settings):
    enroll_status_condition = (
        "any(parameters.fulfillment,and("
        f"eq(externalId,{Param.THREE_YC_ENROLL_STATUS.value}),"
        f"eq(displayValue,{ThreeYearCommitmentStatus.COMMITTED.value})"
        ")"
        ")"
    )
    recommitment_condition = (
        "any(parameters.fulfillment,and("
        f"eq(externalId,{Param.THREE_YC_RECOMMITMENT.value}),"
        "like(displayValue,*Yes*)"
        ")"
        ")"
    )
    enddate_gt_condition = (
        "any(parameters.ordering,and("
        f"eq(externalId,{Param.THREE_YC_END_DATE.value}),"
        f"gt(displayValue,2024-01-31)"
        ")"
        ")"
    )
    enddate_le_condition = (
        "any(parameters.ordering,and("
        f"eq(externalId,{Param.THREE_YC_END_DATE.value}),"
        f"le(displayValue,2024-01-01)"
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

    mocked_get_by_query = mocker.patch(
        "adobe_vipm.flows.mpt.get_agreements_by_query",
        return_value=[{"id": "AGR-0001"}],
    )

    mocked_client = mocker.MagicMock()

    assert get_agreements_for_3yc_recommitment(mocked_client) == [{"id": "AGR-0001"}]
    mocked_get_by_query.assert_called_once_with(mocked_client, rql_query)


@pytest.mark.parametrize("is_recommitment", [True, False])
def test_get_agreements_for_3yc_resubmit(mocker, settings, is_recommitment):
    param_external_id = (
        Param.THREE_YC_COMMITMENT_REQUEST_STATUS.value
        if not is_recommitment
        else Param.THREE_YC_RECOMMITMENT_REQUEST_STATUS.value
    )

    request_type_param_ext_id = (
        Param.THREE_YC.value if not is_recommitment else Param.THREE_YC_RECOMMITMENT.value
    )
    request_type_param_phase = "ordering" if not is_recommitment else "fulfillment"

    error_statuses = [
        ThreeYearCommitmentStatus.DECLINED.value,
        ThreeYearCommitmentStatus.NONCOMPLIANT.value,
        ThreeYearCommitmentStatus.EXPIRED.value,
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

    get_agreement_by_query = {
        "id": "AGR-0001",
        "$meta": {
            "pagination": {
                "offset": 10,
                "limit": 10,
                "total": 9,
            }
        },
    }

    mocked_get_by_query = mocker.patch(
        "adobe_vipm.flows.mpt.get_agreements_by_query",
        return_value=[get_agreement_by_query],
    )

    mocked_client = mocker.MagicMock()

    assert get_agreements_for_3yc_resubmit(
        mocked_client,
        is_recommitment=is_recommitment,
    ) == [get_agreement_by_query]
    mocked_get_by_query.assert_called_once_with(mocked_client, rql_query)


@pytest.mark.parametrize("status", ["Active", "processing"])
def test_get_agreements_by_3yc_enroll_status(mock_mpt_client, mock_get_agreements_by_query, status):
    rql_query = (
        f"and(eq(status,{status}),any(parameters.fulfillment,and(eq(externalId,3YCEnrollStatus),"
        "in(displayValue,(REQUESTED,ACCEPTED)))))"
        "&select=lines,parameters,subscriptions,product,listing"
    )

    get_agreements_by_3yc_enroll_status(mock_mpt_client, ("REQUESTED", "ACCEPTED"), status=status)

    mock_get_agreements_by_query.assert_called_once_with(mock_mpt_client, rql_query)
