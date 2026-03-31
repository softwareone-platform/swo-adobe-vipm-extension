from typing import Any

from mpt_api_client.models.model import ModelList
from pydantic import AliasChoices, Field, field_serializer, field_validator

from mpt_extension_sdk_v6.models.base import BaseSchema


def _normalize_parameter_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            item_key: _normalize_parameter_value(item_value)
            for item_key, item_value in value.items()
        }

    if isinstance(value, list | tuple | ModelList):
        return [_normalize_parameter_value(element) for element in value]

    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _normalize_parameter_value(value.to_dict())

    return value


class Constraints(BaseSchema):
    """Constraints for a parameter."""

    hidden: bool | None = None
    readonly: bool | None = None
    required: bool | None = None


class ParameterValue(BaseSchema):
    """Single ordering or fulfillment parameter value."""

    id: str | None = None
    external_id: str | None = Field(default=None, alias="externalId")
    name: str | None = None
    type: str | None = None
    # TODO: add enum
    phase: str | None = None
    scope: str | None = None
    multiple: bool | None = None
    value: Any = None
    display_value: str | None = Field(
        default=None,
        alias="displayValue",
        validation_alias=AliasChoices("displayValue", "display_value"),
    )

    constraints: Constraints = Field(default_factory=Constraints)

    @field_validator("value", mode="before")
    @classmethod
    def _normalize_value(cls, param_value: Any) -> Any:
        return _normalize_parameter_value(param_value)

    @field_serializer("value")
    def _serialize_value(self, param_value: Any) -> Any:
        return _normalize_parameter_value(param_value)


class ParameterBag(BaseSchema):
    """Container for ordering and fulfillment parameters."""

    ordering: list[ParameterValue] = Field(default_factory=list)
    fulfillment: list[ParameterValue] = Field(default_factory=list)

    def get_parameter(self, external_id: str, phase: str) -> ParameterValue | None:
        """Return the parameter matching an external ID within a phase."""
        phase_param = getattr(self, phase) or []
        return next(
            (element for element in phase_param if element.external_id == external_id), None
        )

    def get_fulfillment_parameter(self, external_id: str) -> ParameterValue:
        """Return the fulfillment parameter matching an external ID."""
        fulfillment_param = self.get_parameter(external_id, "fulfillment")
        if fulfillment_param is None:
            raise ValueError(f"No fulfillment parameter found for external ID: {external_id}")

        return fulfillment_param

    def get_ordering_parameter(self, external_id: str) -> ParameterValue:
        """Return the ordering parameter matching an external ID."""
        ordering_param = self.get_parameter(external_id, "ordering")
        if ordering_param is None:
            raise ValueError(f"No ordering parameter found for external ID: {external_id}")

        return ordering_param

    def get_ordering_value(self, external_id: str) -> Any:
        """Return the raw value for an ordering parameter."""
        return self._get_value(external_id, "ordering")

    def get_fulfillment_value(self, external_id: str) -> Any:
        """Return the raw value for a fulfillment parameter."""
        return self._get_value(external_id, "fulfillment")

    def set_value(self, external_id: str, new_value: Any, phase: str) -> ParameterValue:
        """Set the raw parameter value for an external ID within a phase."""
        parameter = self.get_parameter(external_id, phase)
        if parameter is not None:
            parameter.value = new_value
            return parameter

        parameters = getattr(self, phase)
        parameter = ParameterValue(externalId=external_id, value=new_value)
        parameters.append(parameter)
        return parameter

    def set_fulfillment_value(self, external_id: str, new_value: Any) -> ParameterValue:
        """Set the raw parameter value for a fulfillment parameter."""
        return self.set_value(external_id, new_value, "fulfillment")

    def set_fulfillment_error(self, external_id: str, error: dict[str, Any]) -> ParameterValue:
        """Set an error on an ordering parameter."""
        param = self.get_fulfillment_value(external_id)
        param.error = error
        param.constraints = {"hidden": False, "required": True}
        return self.set_value(external_id, param, "ordering")

    def set_ordering_error(self, external_id: str, error: dict[str, Any]) -> ParameterValue:
        """Set an error on an ordering parameter."""
        param = self.get_ordering_value(external_id)
        param.error = error
        param.constraints.hidden = {"hidden": False, "required": True}
        return self.set_value(external_id, error, "ordering")

    def set_ordering_value(self, external_id: str, value: Any) -> ParameterValue:
        """Set the raw parameter value for an ordering parameter."""
        return self.set_value(external_id, value, "ordering")

    def _get_value(self, external_id: str, phase: str) -> Any:
        """Return the raw parameter value for an external ID within a phase."""
        parameter = self.get_parameter(external_id, phase)
        return None if parameter is None else parameter.value
