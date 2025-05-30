import logging
from difflib import get_close_matches

from adobe_vipm.adobe.config import get_config
from adobe_vipm.adobe.utils import join_phone_number
from adobe_vipm.adobe.validation import (
    is_valid_address_line_1_length,
    is_valid_address_line_2_length,
    is_valid_city_length,
    is_valid_company_name,
    is_valid_company_name_length,
    is_valid_country,
    is_valid_email,
    is_valid_first_last_name,
    is_valid_minimum_consumables,
    is_valid_minimum_licenses,
    is_valid_phone_number_length,
    is_valid_postal_code,
    is_valid_postal_code_length,
    is_valid_state_or_province,
)
from adobe_vipm.flows.constants import (
    ERR_3YC_NO_MINIMUMS,
    ERR_3YC_QUANTITY_CONSUMABLES,
    ERR_3YC_QUANTITY_LICENSES,
    ERR_ADDRESS,
    ERR_ADDRESS_LINE_1_LENGTH,
    ERR_ADDRESS_LINE_2_LENGTH,
    ERR_CITY_LENGTH,
    ERR_COMPANY_NAME_CHARS,
    ERR_COMPANY_NAME_LENGTH,
    ERR_CONTACT,
    ERR_COUNTRY_CODE,
    ERR_EMAIL_FORMAT,
    ERR_FIRST_NAME_FORMAT,
    ERR_LAST_NAME_FORMAT,
    ERR_PHONE_NUMBER_LENGTH,
    ERR_POSTAL_CODE_FORMAT,
    ERR_POSTAL_CODE_LENGTH,
    ERR_STATE_DID_YOU_MEAN,
    ERR_STATE_OR_PROVINCE,
    PARAM_3YC,
    PARAM_3YC_CONSUMABLES,
    PARAM_3YC_LICENSES,
    PARAM_ADDRESS,
    PARAM_COMPANY_NAME,
    PARAM_CONTACT,
)
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.helpers import PrepareCustomerData, SetupContext, UpdatePrices
from adobe_vipm.flows.pipeline import Pipeline, Step
from adobe_vipm.flows.utils import (
    get_ordering_parameter,
    is_purchase_validation_enabled,
    set_order_error,
    set_ordering_parameter_error,
    update_ordering_parameter_value,
)
from adobe_vipm.flows.validation.shared import (
    GetPreviewOrder,
    ValidateDuplicateLines,
)

logger = logging.getLogger(__name__)


class CheckPurchaseValidationEnabled(Step):
    def __call__(self, client, context, next_step):
        if not is_purchase_validation_enabled(context.order):
            return
        next_step(client, context)


class ValidateCustomerData(Step):
    def validate_3yc(self, context):
        p3yc = context.customer_data[PARAM_3YC]

        if p3yc != ["Yes"]:
            return

        errors = False

        for param_name, validator, error in (
            (
                PARAM_3YC_CONSUMABLES,
                is_valid_minimum_consumables,
                ERR_3YC_QUANTITY_CONSUMABLES,
            ),
            (PARAM_3YC_LICENSES, is_valid_minimum_licenses, ERR_3YC_QUANTITY_LICENSES),
        ):
            param = get_ordering_parameter(context.order, param_name)

            if not validator(context.customer_data[param_name]):
                context.validation_succeeded = False
                context.order = set_ordering_parameter_error(
                    context.order,
                    param_name,
                    error.to_dict(title=param["name"]),
                    required=False,
                )

        if not errors and not (
            context.customer_data[PARAM_3YC_LICENSES]
            or context.customer_data[PARAM_3YC_CONSUMABLES]
        ):
            errors = True
            param_licenses = get_ordering_parameter(context.order, PARAM_3YC_LICENSES)
            param_consumables = get_ordering_parameter(
                context.order, PARAM_3YC_CONSUMABLES
            )
            context.validation_succeeded = False
            context.order = set_order_error(
                context.order,
                ERR_3YC_NO_MINIMUMS.to_dict(
                    title_min_licenses=param_licenses["name"],
                    title_min_consumables=param_consumables["name"],
                ),
            )

    def validate_company_name(self, context):
        param = get_ordering_parameter(context.order, PARAM_COMPANY_NAME)
        name = context.customer_data[PARAM_COMPANY_NAME]
        if not is_valid_company_name_length(name):
            context.validation_succeeded = False
            context.order = set_ordering_parameter_error(
                context.order,
                PARAM_COMPANY_NAME,
                ERR_COMPANY_NAME_LENGTH.to_dict(title=param["name"]),
            )
            return
        if not is_valid_company_name(name):
            context.validation_succeeded = False
            context.order = set_ordering_parameter_error(
                context.order,
                PARAM_COMPANY_NAME,
                ERR_COMPANY_NAME_CHARS.to_dict(title=param["name"]),
            )

    def validate_address(self, context):
        param = get_ordering_parameter(context.order, PARAM_ADDRESS)
        address = context.customer_data[PARAM_ADDRESS]
        errors = []

        country_code = address["country"]

        if not is_valid_country(country_code):
            errors.append(ERR_COUNTRY_CODE)
            context.validation_succeeded = False
            context.order = set_ordering_parameter_error(
                context.order,
                PARAM_ADDRESS,
                ERR_ADDRESS.to_dict(
                    title=param["name"],
                    errors="".join(errors),
                ),
            )
            return

        if not is_valid_state_or_province(country_code, address["state"]):
            config = get_config()
            country = config.get_country(country_code)
            state_error = ERR_STATE_OR_PROVINCE
            if country.provinces_to_code:  # pragma: no branch
                suggestions = get_close_matches(
                    address["state"],
                    list(country.provinces_to_code.keys()),
                )
                if suggestions:
                    if len(suggestions) > 1:
                        did_u_mean = ERR_STATE_DID_YOU_MEAN.format(
                            suggestion=", ".join(suggestions)
                        )
                        state_error = f"{state_error}{did_u_mean}"
                        errors.append(state_error)
                    else:
                        address["state"] = suggestions[0]
                else:
                    errors.append(state_error)
            else:  # pragma: no cover
                errors.append(state_error)

        if not is_valid_postal_code(country_code, address["postCode"]):
            errors.append(ERR_POSTAL_CODE_FORMAT)

        for field, validator_func, err_msg in (
            ("postCode", is_valid_postal_code_length, ERR_POSTAL_CODE_LENGTH),
            ("addressLine1", is_valid_address_line_1_length, ERR_ADDRESS_LINE_1_LENGTH),
            ("city", is_valid_city_length, ERR_CITY_LENGTH),
        ):
            if not validator_func(address[field]):
                errors.append(err_msg)

        if address["addressLine2"] and not is_valid_address_line_2_length(
            address["addressLine2"]
        ):
            errors.append(ERR_ADDRESS_LINE_2_LENGTH)

        if errors:
            context.validation_succeeded = False
            context.order = set_ordering_parameter_error(
                context.order,
                PARAM_ADDRESS,
                ERR_ADDRESS.to_dict(
                    title=param["name"],
                    errors="; ".join(errors),
                ),
            )
            return
        context.order = update_ordering_parameter_value(
            context.order,
            PARAM_ADDRESS,
            address,
        )

    def validate_contact(self, context):
        contact = context.customer_data[PARAM_CONTACT]
        param = get_ordering_parameter(context.order, PARAM_CONTACT)
        errors = []

        if not contact:
            context.validation_succeeded = False
            context.order = set_ordering_parameter_error(
                context.order,
                PARAM_CONTACT,
                ERR_CONTACT.to_dict(
                    title=param["name"],
                    errors="it is mandatory.",
                ),
            )
            return

        if not is_valid_first_last_name(contact["firstName"]):
            errors.append(ERR_FIRST_NAME_FORMAT)

        if not is_valid_first_last_name(contact["lastName"]):
            errors.append(ERR_LAST_NAME_FORMAT)

        if not is_valid_email(contact["email"]):
            errors.append(ERR_EMAIL_FORMAT)

        if contact.get("phone") and not is_valid_phone_number_length(
            join_phone_number(contact["phone"])
        ):
            errors.append(ERR_PHONE_NUMBER_LENGTH)

        if errors:
            context.validation_succeeded = False
            context.order = set_ordering_parameter_error(
                context.order,
                PARAM_CONTACT,
                ERR_CONTACT.to_dict(
                    title=param["name"],
                    errors="; ".join(errors),
                ),
            )

    def __call__(self, client, context, next_step):
        self.validate_company_name(context)
        self.validate_address(context)
        self.validate_contact(context)
        self.validate_3yc(context)

        if not context.validation_succeeded:
            return

        next_step(client, context)


def validate_purchase_order(client, order):
    pipeline = Pipeline(
        SetupContext(),
        PrepareCustomerData(),
        CheckPurchaseValidationEnabled(),
        ValidateCustomerData(),
        ValidateDuplicateLines(),
        GetPreviewOrder(),
        UpdatePrices(),
    )
    context = Context(order=order)
    pipeline.run(client, context)
    return not context.validation_succeeded, context.order
