from urllib.parse import urljoin

import pytest

from adobe_vipm.adobe.constants import (
    ThreeYearCommitmentStatus,
)
from adobe_vipm.adobe.errors import AdobeAPIError
from adobe_vipm.flows.benefits import check_3yc_commitment_request
from adobe_vipm.flows.constants import Param
from adobe_vipm.flows.utils import get_adobe_customer_id, get_company_name
from adobe_vipm.notifications import Button


@pytest.mark.parametrize("is_recommitment", [False, True])
def test_check_3yc_commitment_request(
    mocker,
    mock_adobe_client,
    mock_mpt_client,
    agreement_factory,
    adobe_customer_factory,
    adobe_commitment_factory,
    is_recommitment,
):
    status_param_ext_id = (
        "3YCCommitmentRequestStatus" if not is_recommitment else "3YCRecommitmentRequestStatus"
    )
    request_type_param_ext_id = "3YC" if not is_recommitment else "3YCRecommitment"
    request_type_param_phase = "ordering" if not is_recommitment else "fulfillment"
    customer_kwargs = {
        "commitment": adobe_commitment_factory(status="COMMITTED"),
    }
    request_type = "commitment_request" if not is_recommitment else "recommitment_request"
    customer_kwargs[request_type] = adobe_commitment_factory(status="COMMITTED")
    agreement = agreement_factory()
    customer = adobe_customer_factory(**customer_kwargs)
    mock_adobe_client.get_customer.return_value = customer
    mocked_get_agreements = mocker.patch(
        "adobe_vipm.flows.benefits.get_agreements_by_3yc_commitment_request_status",
        return_value=[agreement],
    )
    mocked_update_agreement = mocker.patch("adobe_vipm.flows.benefits.update_agreement")
    expected_params = {
        "fulfillment": [
            {"externalId": status_param_ext_id, "value": "COMMITTED"},
        ],
    }
    expected_params.setdefault(request_type_param_phase, [])
    expected_params[request_type_param_phase].append(
        {"externalId": request_type_param_ext_id, "value": None},
    )
    expected_params["fulfillment"].extend([
        {"externalId": "3YCEnrollStatus", "value": "COMMITTED"},
        {"externalId": "3YCStartDate", "value": "2024-01-01"},
        {"externalId": "3YCEndDate", "value": "2025-01-01"},
    ])

    check_3yc_commitment_request(mock_mpt_client, is_recommitment=is_recommitment)

    mocked_get_agreements.assert_called_once_with(mock_mpt_client, is_recommitment=is_recommitment)
    mock_adobe_client.get_customer.assert_called_once_with(
        agreement["authorization"]["id"], get_adobe_customer_id(agreement)
    )
    mocked_update_agreement.assert_called_once_with(
        mock_mpt_client, agreement["id"], parameters=expected_params
    )


@pytest.mark.parametrize("is_recommitment", [False, True])
def test_check_3yc_commitment_request_not_committed(
    mocker,
    mock_adobe_client,
    mock_mpt_client,
    agreement_factory,
    adobe_customer_factory,
    adobe_commitment_factory,
    is_recommitment,
):
    status_param_ext_id = (
        "3YCCommitmentRequestStatus" if not is_recommitment else "3YCRecommitmentRequestStatus"
    )
    request_type = "commitment_request" if not is_recommitment else "recommitment_request"
    customer_kwargs = {request_type: adobe_commitment_factory(status="ACCEPTED")}
    agreement = agreement_factory()
    customer = adobe_customer_factory(**customer_kwargs)
    mock_adobe_client.get_customer.return_value = customer
    mocked_get_agreements = mocker.patch(
        "adobe_vipm.flows.benefits.get_agreements_by_3yc_commitment_request_status",
        return_value=[agreement],
    )
    mocked_update_agreement = mocker.patch("adobe_vipm.flows.benefits.update_agreement")

    check_3yc_commitment_request(mock_mpt_client, is_recommitment=is_recommitment)

    mocked_get_agreements.assert_called_once_with(mock_mpt_client, is_recommitment=is_recommitment)
    mocked_update_agreement.assert_called_once_with(
        mock_mpt_client,
        agreement["id"],
        parameters={
            "fulfillment": [
                {"externalId": status_param_ext_id, "value": "ACCEPTED"},
            ],
        },
    )


@pytest.mark.parametrize("is_recommitment", [False, True])
@pytest.mark.parametrize(
    "request_status",
    [
        ThreeYearCommitmentStatus.DECLINED.value,
        ThreeYearCommitmentStatus.EXPIRED.value,
        ThreeYearCommitmentStatus.NONCOMPLIANT.value,
    ],
)
def test_check_3yc_commitment_request_declined(
    mocker,
    mock_adobe_client,
    mock_mpt_client,
    settings,
    agreement_factory,
    adobe_customer_factory,
    adobe_commitment_factory,
    is_recommitment,
    request_status,
):
    status_param_ext_id = (
        "3YCCommitmentRequestStatus" if not is_recommitment else "3YCRecommitmentRequestStatus"
    )
    request_type = "commitment_request" if not is_recommitment else "recommitment_request"
    customer_kwargs = {request_type: adobe_commitment_factory(status=request_status)}
    agreement = agreement_factory()
    customer = adobe_customer_factory(**customer_kwargs)
    mock_adobe_client.get_customer.return_value = customer
    mocked_get_agreements = mocker.patch(
        "adobe_vipm.flows.benefits.get_agreements_by_3yc_commitment_request_status",
        return_value=[agreement],
    )
    mocked_update_agreement = mocker.patch("adobe_vipm.flows.benefits.update_agreement")
    mocked_send_warning = mocker.patch("adobe_vipm.flows.benefits.send_warning")

    check_3yc_commitment_request(mock_mpt_client, is_recommitment=is_recommitment)

    mocked_get_agreements.assert_called_once_with(mock_mpt_client, is_recommitment=is_recommitment)
    mocked_update_agreement.assert_called_once_with(
        mock_mpt_client,
        agreement["id"],
        parameters={
            "fulfillment": [
                {"externalId": status_param_ext_id, "value": request_status},
            ],
        },
    )
    request_type_param_phase = "ordering" if not is_recommitment else "fulfillment"
    agreement_link = urljoin(
        settings.MPT_PORTAL_BASE_URL, f"/commerce/agreements/{agreement['id']}"
    )
    request_type_title = "commitment" if not is_recommitment else "recommitment"
    mocked_send_warning.assert_called_once_with(
        f"3YC {request_type_title.capitalize()} Request {request_status}",
        f"The 3-year {request_type_title} request for agreement {agreement['id']} "
        f"**{agreement['name']}** of the customer **{get_company_name(agreement)}** "
        f"has been denied: {request_status}.\n\n"
        "To request the 3YC again, as a Vendor user, "
        "modify the Agreement and mark the 3-year "
        f"{request_type_title} {request_type_param_phase} parameter checkbox again.",
        button=Button(f"Open {agreement['id']}", agreement_link),
    )


@pytest.mark.parametrize("is_recommitment", [False, True])
def test_check_3yc_commitment_request_exception(
    mocker,
    mock_adobe_client,
    mock_mpt_client,
    agreement_factory,
    adobe_api_error_factory,
    is_recommitment,
):
    req_type = "Recommitment" if is_recommitment else "Commitment"
    agreement = agreement_factory()
    mock_adobe_client.get_customer.side_effect = AdobeAPIError(
        500,
        adobe_api_error_factory(code="1224", message="Internal Server Error"),
    )
    mocked_get_agreements = mocker.patch(
        "adobe_vipm.flows.benefits.get_agreements_by_3yc_commitment_request_status",
        return_value=[agreement],
    )
    mocked_send_exception = mocker.patch("adobe_vipm.flows.benefits.send_exception")

    check_3yc_commitment_request(mock_mpt_client, is_recommitment=is_recommitment)

    mocked_get_agreements.assert_called_once_with(mock_mpt_client, is_recommitment=is_recommitment)
    mock_adobe_client.get_customer.assert_called_once_with(
        agreement["authorization"]["id"], get_adobe_customer_id(agreement)
    )
    assert (
        mocked_send_exception.mock_calls[0].args[0]
        == f"3YC {req_type} Request exception for {agreement['id']}"
    )
    assert "Traceback" in mocked_send_exception.mock_calls[0].args[1]


def test_check_3yc_commitment_request_global_customers(
    mocker,
    mock_adobe_client,
    mpt_client,
    agreement_factory,
    fulfillment_parameters_factory,
    adobe_customer_factory,
    adobe_commitment_factory,
):
    agreement = agreement_factory(
        fulfillment_parameters=fulfillment_parameters_factory(
            global_customer="Yes",
            deployment_id="",
            deployments="here-should-be-deployment-ids",
        ),
    )
    deployment_agreements = [
        agreement_factory(
            fulfillment_parameters=fulfillment_parameters_factory(
                global_customer="",
                deployment_id=f"deployment-{i}",
                deployments="",
            ),
        )
        for i in range(2)
    ]

    mocker.patch(
        "adobe_vipm.flows.benefits.get_agreements_by_3yc_commitment_request_status",
        return_value=[agreement],
    )
    customer_kwargs = {
        "commitment": adobe_commitment_factory(status="COMMITTED"),
        "commitment_request": adobe_commitment_factory(status="COMMITTED"),
        "global_sales_enabled": True,
    }
    customer = adobe_customer_factory(**customer_kwargs)
    mock_adobe_client.get_customer.return_value = customer
    mock_adobe_client.get_customer_deployments_active_status.return_value = [
        {"deploymentId": str(i)} for i in range(2)
    ]
    mocked_update_agreement = mocker.patch("adobe_vipm.flows.benefits.update_agreement")
    mocked_get_agreements_by_deployments = mocker.patch(
        "adobe_vipm.flows.benefits.get_agreements_by_customer_deployments",
        return_value=deployment_agreements,
    )

    check_3yc_commitment_request(mpt_client, is_recommitment=False)

    mocked_get_agreements_by_deployments.assert_called_once_with(
        mpt_client,
        Param.DEPLOYMENT_ID.value,
        ["0", "1"],
    )
    assert mocked_update_agreement.call_args_list == [
        mocker.call(
            mpt_client,
            "AGR-2119-4550-8674-5962",
            parameters={
                "fulfillment": [
                    {"externalId": "3YCCommitmentRequestStatus", "value": "COMMITTED"},
                    {"externalId": "3YCEnrollStatus", "value": "COMMITTED"},
                    {"externalId": "3YCStartDate", "value": "2024-01-01"},
                    {"externalId": "3YCEndDate", "value": "2025-01-01"},
                ],
                "ordering": [{"externalId": "3YC", "value": None}],
            },
        ),
        mocker.call(
            mpt_client,
            "AGR-2119-4550-8674-5962",
            parameters={
                "fulfillment": [
                    {"externalId": "3YCCommitmentRequestStatus", "value": "COMMITTED"},
                    {"externalId": "3YCEnrollStatus", "value": "COMMITTED"},
                    {"externalId": "3YCStartDate", "value": "2024-01-01"},
                    {"externalId": "3YCEndDate", "value": "2025-01-01"},
                ],
                "ordering": [{"externalId": "3YC", "value": None}],
            },
        ),
        mocker.call(
            mpt_client,
            "AGR-2119-4550-8674-5962",
            parameters={
                "fulfillment": [
                    {"externalId": "3YCCommitmentRequestStatus", "value": "COMMITTED"},
                    {"externalId": "3YCEnrollStatus", "value": "COMMITTED"},
                    {"externalId": "3YCStartDate", "value": "2024-01-01"},
                    {"externalId": "3YCEndDate", "value": "2025-01-01"},
                ],
                "ordering": [{"externalId": "3YC", "value": None}],
            },
        ),
    ]
