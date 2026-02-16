import pytest

from adobe_vipm.adobe.constants import (
    ThreeYearCommitmentStatus,
)
from adobe_vipm.flows.constants import Param
from adobe_vipm.flows.mpt import (
    get_agreements_by_3yc_commitment_request_invitation,
    get_agreements_by_3yc_commitment_request_status,
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
        f"eq(externalId,'{param_external_id}'),"
        f"in(displayValue,({ThreeYearCommitmentStatus.REQUESTED.value},{ThreeYearCommitmentStatus.ACCEPTED.value}))"
        ")"
        ")"
    )
    request_3yc_condition = (
        f"any(parameters.{request_type_param_phase},and("
        f"eq(externalId,'{request_type_param_ext_id}'),"
        "like(displayValue,*Yes*)"
        ")"
        ")"
    )
    status_condition = "eq(status,'Active')"
    product_condition = f"in(product.id,({','.join(settings.MPT_PRODUCTS_IDS)}))"
    rql_query = (
        f"and({status_condition},{enroll_status_condition}"
        f",{request_3yc_condition},{product_condition})&select=parameters"
    )
    mocked_get_by_query = mocker.patch(
        "adobe_vipm.flows.mpt.get_agreements_by_query", return_value=[{"id": "AGR-0001"}]
    )
    mocked_client = mocker.MagicMock()

    result = get_agreements_by_3yc_commitment_request_status(
        mocked_client, is_recommitment=is_recommitment
    )

    assert result == [{"id": "AGR-0001"}]
    mocked_get_by_query.assert_called_once_with(mocked_client, rql_query)


@pytest.mark.parametrize("status", ["Active", "processing"])
def test_get_agreements_by_3yc_commitment_request_invitation(
    mock_mpt_client, mock_mpt_get_agreements_by_query, status
):
    rql_query = (
        f"and(eq(status,'{status}'),any(parameters.fulfillment,and(eq(externalId,'3YCCommitmentRequestStatus'),"
        "in(displayValue,(REQUESTED,ACCEPTED)))))"
        "&select=lines,parameters,assets,subscriptions,product,listing"
    )

    get_agreements_by_3yc_commitment_request_invitation(
        mock_mpt_client, ("REQUESTED", "ACCEPTED"), status=status
    )  # act

    mock_mpt_get_agreements_by_query.assert_called_once_with(mock_mpt_client, rql_query)
