import logging
import traceback
from urllib.parse import urljoin

from django.conf import settings
from mpt_extension_sdk.core.utils import MPTClient
from mpt_extension_sdk.mpt_http.mpt import (
    get_agreements_by_customer_deployments,
    get_licensee,
    update_agreement,
)

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.adobe.constants import (
    ThreeYearCommitmentStatus,
)
from adobe_vipm.adobe.utils import get_3yc_commitment_request
from adobe_vipm.flows.constants import Param
from adobe_vipm.flows.mpt import get_agreements_by_3yc_commitment_request_status
from adobe_vipm.flows.utils import (
    get_adobe_customer_id,
    get_company_name,
    get_global_customer,
)
from adobe_vipm.flows.utils.parameter import get_fulfillment_parameter, get_ordering_parameter
from adobe_vipm.notifications import Button, mpt_notify, send_exception, send_warning
from adobe_vipm.utils import get_3yc_commitment

logger = logging.getLogger(__name__)


def _build_3yc_parameters(request_info, commitment_info, is_recommitment):
    """Build parameters for 3YC commitment request."""
    status_param_ext_id = (
        Param.THREE_YC_COMMITMENT_REQUEST_STATUS.value
        if not is_recommitment
        else Param.THREE_YC_RECOMMITMENT_REQUEST_STATUS.value
    )
    request_type_param_ext_id = (
        Param.THREE_YC.value if not is_recommitment else Param.THREE_YC_RECOMMITMENT.value
    )
    request_type_param_phase = (
        Param.PHASE_ORDERING.value if not is_recommitment else Param.PHASE_FULFILLMENT.value
    )

    parameters = {
        Param.PHASE_FULFILLMENT.value: [
            {
                "externalId": status_param_ext_id,
                "value": request_info.get("status"),
            },
        ]
    }

    if commitment_info:
        parameters.setdefault(request_type_param_phase, [])
        parameters[request_type_param_phase].append(
            {"externalId": request_type_param_ext_id, "value": None},
        )
        parameters[Param.PHASE_FULFILLMENT.value].extend(
            [
                {
                    "externalId": Param.THREE_YC_ENROLL_STATUS.value,
                    "value": commitment_info.get("status"),
                },
                {
                    "externalId": Param.THREE_YC_START_DATE.value,
                    "value": commitment_info.get("startDate"),
                },
                {
                    "externalId": Param.THREE_YC_END_DATE.value,
                    "value": commitment_info.get("endDate"),
                },
            ],
        )

    return parameters


# TODO: check function also updates parameters :-(
def check_3yc_commitment_request(mpt_client, *, is_recommitment):
    """Checks 3YC request from adobe and updates agreement info."""
    adobe_client = get_adobe_client()
    agreements = get_agreements_by_3yc_commitment_request_status(
        mpt_client,
        is_recommitment=is_recommitment,
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

            logger.info(
                "3YC request for agreement %s is %s",
                agreement["id"],
                request_info["status"],
            )

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
            if status in {
                ThreeYearCommitmentStatus.DECLINED,
                ThreeYearCommitmentStatus.EXPIRED,
                ThreeYearCommitmentStatus.NONCOMPLIANT,
            }:
                request_type_param_phase = (
                    Param.PHASE_ORDERING.value
                    if not is_recommitment
                    else Param.PHASE_FULFILLMENT.value
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
                "An exception has been raised checking 3YC request for %s",
                agreement["id"],
            )
            send_exception(
                f"3YC {request_type_title.capitalize()} Request exception for {agreement['id']}",
                traceback.format_exc(),
            )


def update_deployment_agreements_3yc(
    adobe_client, mpt_client, authorization_id, customer_id, parameters_3yc
):
    """Updates all deployment agreements 3yc parameters for customer."""
    customer_deployments = adobe_client.get_customer_deployments_active_status(
        authorization_id, customer_id
    )
    if not customer_deployments:
        return

    deployment_agreements = get_agreements_by_customer_deployments(
        mpt_client,
        Param.DEPLOYMENT_ID.value,
        [deployment["deploymentId"] for deployment in customer_deployments],
    )

    for deployment_agreement in deployment_agreements:
        update_agreement(
            mpt_client,
            deployment_agreement["id"],
            parameters=parameters_3yc,
        )


def send_3yc_expiration_notification(
    client: MPTClient, agreement: dict, number_of_days: int, template_name: str
):
    """Send 3YC expiration notification to the customer.

    Args:
        client: The MPT client.
        agreement: The agreement.
        number_of_days: The number of days.
        template_name: The template name.
    """
    try:
        licensee = get_licensee(client, agreement["licensee"]["id"])
        minimum_licenses = get_ordering_parameter(agreement, Param.THREE_YC_LICENSES.value)
        minimum_consumables = get_ordering_parameter(agreement, Param.THREE_YC_CONSUMABLES.value)
        three_yc_start_date = get_fulfillment_parameter(agreement, Param.THREE_YC_START_DATE.value)
        three_yc_end_date = get_fulfillment_parameter(agreement, Param.THREE_YC_END_DATE.value)
        three_yc_enroll_status = get_fulfillment_parameter(
            agreement, Param.THREE_YC_ENROLL_STATUS.value
        )

        mpt_notify(
            client,
            licensee["account"]["id"],
            agreement["buyer"]["id"],
            "3YC Expiration Notification",
            template_name,
            {
                "agreement": agreement,
                "portal_base_url": settings.MPT_PORTAL_BASE_URL,
                "minimum_licenses": minimum_licenses.get("displayValue", "N/A"),
                "minimum_consumables": minimum_consumables.get("displayValue", "N/A"),
                "three_yc_start_date": three_yc_start_date.get("displayValue", "N/A"),
                "three_yc_end_date": three_yc_end_date.get("displayValue", "N/A"),
                "three_yc_enroll_status": three_yc_enroll_status.get("displayValue", "N/A"),
                "n_days": number_of_days,
            },
        )

        logger.info("Notification sent for agreement %s", {agreement["id"]})
    except Exception:  # pragma: no cover
        logger.exception("Failed to send notification for agreement %s", agreement["id"])
