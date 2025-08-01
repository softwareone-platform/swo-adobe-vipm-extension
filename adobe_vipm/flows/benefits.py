import logging
import traceback
from urllib.parse import urljoin

from django.conf import settings
from mpt_extension_sdk.mpt_http.mpt import (
    get_agreements_by_customer_deployments,
    update_agreement,
)

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.adobe.constants import (
    ThreeYearCommitmentStatus,
)
from adobe_vipm.adobe.utils import get_3yc_commitment_request
from adobe_vipm.flows.constants import Param
from adobe_vipm.flows.mpt import (
    get_agreements_by_3yc_commitment_request_status,
    get_agreements_for_3yc_recommitment,
    get_agreements_for_3yc_resubmit,
)
from adobe_vipm.flows.utils import (
    get_adobe_customer_id,
    get_company_name,
    get_global_customer,
    get_ordering_parameter,
)
from adobe_vipm.notifications import Button, send_exception, send_warning
from adobe_vipm.utils import get_3yc_commitment

logger = logging.getLogger(__name__)


def _build_3yc_parameters(request_info, commitment_info, is_recommitment):
    """Build parameters for 3YC commitment request."""
    status_param_ext_id = (
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

    parameters = {
        Param.PHASE_FULFILLMENT: [
            {
                "externalId": status_param_ext_id,
                "value": request_info["status"],
            },
        ]
    }

    if commitment_info:
        parameters.setdefault(request_type_param_phase, [])
        parameters[request_type_param_phase].append(
            {"externalId": request_type_param_ext_id, "value": None},
        )
        parameters[Param.PHASE_FULFILLMENT].extend(
            [
                {
                    "externalId": Param.THREE_YC_ENROLL_STATUS,
                    "value": commitment_info["status"],
                },
                {
                    "externalId": Param.THREE_YC_START_DATE,
                    "value": commitment_info["startDate"],
                },
                {
                    "externalId": Param.THREE_YC_END_DATE,
                    "value": commitment_info["endDate"],
                },
            ],
        )

    return parameters


def check_3yc_commitment_request(mpt_client, is_recommitment=False):
    adobe_client = get_adobe_client()
    agreements = get_agreements_by_3yc_commitment_request_status(
        mpt_client, is_recommitment=is_recommitment
    )
    request_type_title = "commitment" if not is_recommitment else "recommitment"
    for agreement in agreements:
        try:
            authorization_id = agreement["authorization"]["id"]
            customer_id = get_adobe_customer_id(agreement)
            customer = adobe_client.get_customer(
                authorization_id,
                customer_id,
            )

            request_info = get_3yc_commitment_request(customer, is_recommitment=is_recommitment)
            commitment_info = get_3yc_commitment(customer)

            parameters = _build_3yc_parameters(request_info, commitment_info, is_recommitment)

            logger.info(f"3YC request for agreement {agreement['id']} is {request_info['status']}")

            update_agreement(
                mpt_client,
                agreement["id"],
                parameters=parameters,
            )
            if get_global_customer(agreement)[0] == "Yes":
                update_deployment_agreements_3yc(
                    adobe_client, mpt_client, authorization_id, customer_id, parameters
                )

            status = request_info["status"]
            if status in (
                ThreeYearCommitmentStatus.DECLINED,
                ThreeYearCommitmentStatus.EXPIRED,
                ThreeYearCommitmentStatus.NONCOMPLIANT,
            ):
                request_type_param_phase = (
                    Param.PHASE_ORDERING if not is_recommitment else Param.PHASE_FULFILLMENT
                )
                agreement_link = urljoin(
                    settings.MPT_PORTAL_BASE_URL,
                    f"/commerce/agreements/{agreement['id']}",
                )
                send_warning(
                    f"3YC {request_type_title.capitalize()} Request {status}",
                    f"The 3-year {request_type_title} request for agreement {agreement['id']} "
                    f"**{agreement['name']}** of the customer **{get_company_name(agreement)}** "
                    f"has been denied: {status}.\n\n"
                    "To request the 3YC again, as a Vendor user, "
                    "modify the Agreement and mark the 3-year "
                    f"{request_type_title} {request_type_param_phase} parameter checkbox again.",
                    button=Button(f"Open {agreement['id']}", agreement_link),
                )
        except Exception:
            logger.exception(
                f"An exception has been raised checking 3YC request for {agreement['id']}",
            )
            send_exception(
                f"3YC {request_type_title.capitalize()} Request exception for {agreement['id']}",
                traceback.format_exc(),
            )


def update_deployment_agreements_3yc(
    adobe_client, mpt_client, authorization_id, customer_id, parameters_3yc
):
    customer_deployments = adobe_client.get_customer_deployments_active_status(
        authorization_id, customer_id
    )
    if not customer_deployments:
        return

    deployment_agreements = get_agreements_by_customer_deployments(
        mpt_client,
        Param.DEPLOYMENT_ID,
        [deployment["deploymentId"] for deployment in customer_deployments],
    )

    for deployment_agreement in deployment_agreements:
        update_agreement(
            mpt_client,
            deployment_agreement["id"],
            parameters=parameters_3yc,
        )


def resubmit_3yc_commitment_request(mpt_client, is_recommitment=False):
    request_type_title = "Commitment" if not is_recommitment else "Recommitment"
    status_param_ext_id = (
        Param.THREE_YC_COMMITMENT_REQUEST_STATUS
        if not is_recommitment
        else Param.THREE_YC_RECOMMITMENT_REQUEST_STATUS
    )
    adobe_client = get_adobe_client()
    agreements = get_agreements_for_3yc_resubmit(mpt_client, is_recommitment=is_recommitment)
    for agreement in agreements:
        try:
            authorization_id = agreement["authorization"]["id"]
            customer_id = get_adobe_customer_id(agreement)

            commitment_request = {
                Param.THREE_YC_CONSUMABLES: get_ordering_parameter(
                    agreement, Param.THREE_YC_CONSUMABLES
                ).get("value"),
                Param.THREE_YC_LICENSES: get_ordering_parameter(
                    agreement, Param.THREE_YC_LICENSES
                ).get("value"),
            }
            customer = adobe_client.create_3yc_request(
                authorization_id,
                customer_id,
                commitment_request,
                is_recommitment=is_recommitment,
            )

            commitment_info = get_3yc_commitment_request(customer, is_recommitment=is_recommitment)
            status = commitment_info["status"]
            parameters = {
                Param.PHASE_FULFILLMENT: [
                    {"externalId": status_param_ext_id, "value": status},
                ]
            }

            update_agreement(
                mpt_client,
                agreement["id"],
                parameters=parameters,
            )
        except Exception:
            logger.exception(
                f"An exception has been raised checking 3YC request for {agreement['id']}",
            )
            send_exception(
                f"3YC {request_type_title} Request exception for {agreement['id']}",
                traceback.format_exc(),
            )


def submit_3yc_recommitment_request(mpt_client):
    adobe_client = get_adobe_client()
    agreements = get_agreements_for_3yc_recommitment(mpt_client)
    for agreement in agreements:
        try:
            authorization_id = agreement["authorization"]["id"]
            customer_id = get_adobe_customer_id(agreement)

            commitment_request = {
                Param.THREE_YC_CONSUMABLES: get_ordering_parameter(
                    agreement, Param.THREE_YC_CONSUMABLES
                ).get("value"),
                Param.THREE_YC_LICENSES: get_ordering_parameter(
                    agreement, Param.THREE_YC_LICENSES
                ).get("value"),
            }

            customer = adobe_client.create_3yc_request(
                authorization_id,
                customer_id,
                commitment_request,
                is_recommitment=True,
            )

            commitment_info = get_3yc_commitment_request(customer, is_recommitment=True)
            status = commitment_info["status"]
            parameters = {
                Param.PHASE_FULFILLMENT: [
                    {"externalId": "3YCRecommitmentRequestStatus", "value": status},
                ]
            }

            update_agreement(
                mpt_client,
                agreement["id"],
                parameters=parameters,
            )
        except Exception:
            logger.exception(
                f"An exception has been raised checking 3YC request for {agreement['id']}",
            )
            send_exception(
                f"3YC Recommitment Request exception for {agreement['id']}",
                traceback.format_exc(),
            )
