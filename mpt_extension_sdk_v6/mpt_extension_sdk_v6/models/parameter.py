from typing import Any

from pydantic import AliasChoices, Field, field_serializer, field_validator

from mpt_extension_sdk_v6.api.schemas.base import BaseSchema


def _normalize_parameter_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            item_key: _normalize_parameter_value(item_value)
            for item_key, item_value in value.items()
        }

    if isinstance(value, list):
        return [_normalize_parameter_value(item) for item in value]

    if isinstance(value, tuple):
        return tuple(_normalize_parameter_value(item) for item in value)

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

    constraints: Constraints | None = None

    @field_validator("value", mode="before")
    @classmethod
    def _normalize_value(cls, value: Any) -> Any:
        return _normalize_parameter_value(value)

    @field_serializer("value")
    def _serialize_value(self, value: Any) -> Any:
        return _normalize_parameter_value(value)


class ParameterBag(BaseSchema):
    """Container for ordering and fulfillment parameters."""

    ordering: list[ParameterValue] | None = None
    fulfillment: list[ParameterValue] | None = None

    def get_parameter(self, external_id: str, phase: str) -> ParameterValue | None:
        """Return the parameter matching an external ID within a phase."""
        parameters = getattr(self, phase) or []
        return next((param for param in parameters if param.external_id == external_id), None)

    def get_value(self, external_id: str, phase: str) -> Any:
        """Return the raw parameter value for an external ID within a phase."""
        parameter = self.get_parameter(external_id, phase)
        return None if parameter is None else parameter.value

    def get_ordering_value(self, external_id: str) -> Any:
        """Return the raw value for an ordering parameter."""
        return self.get_value(external_id, "ordering")

    def get_fulfillment_value(self, external_id: str) -> Any:
        """Return the raw value for a fulfillment parameter."""
        return self.get_value(external_id, "fulfillment")

    def set_value(self, external_id: str, value: Any, phase: str) -> ParameterValue:
        """Set the raw parameter value for an external ID within a phase."""
        parameter = self.get_parameter(external_id, phase)
        if parameter is not None:
            parameter.value = value
            return parameter

        parameters = getattr(self, phase)
        if parameters is None:
            parameters = []
            setattr(self, phase, parameters)

        parameter = ParameterValue(externalId=external_id, value=value)
        parameters.append(parameter)
        return parameter

    def set_fulfillment_value(self, external_id: str, value: Any) -> ParameterValue:
        """Set the raw parameter value for a fulfillment parameter."""
        return self.set_value(external_id, value, "fulfillment")

    def set_fulfillment_error(self, external_id: str, error: dict) -> ParameterValue:
        """Set an error on an ordering parameter."""
        param = self.get_fulfillment_value(external_id)
        param.error = error
        param.constraints = {"hidden": False, "required": True}
        return self.set_value(external_id, param, "ordering")

    def set_ordering_error(self, external_id: str, error: dict) -> ParameterValue:
        """Set an error on an ordering parameter."""
        param = self.get_ordering_value(external_id)
        param.error = error
        param.constraints = {"hidden": False, "required": True}
        return self.set_value(external_id, error, "ordering")

    def set_ordering_value(self, external_id: str, value: Any) -> ParameterValue:
        """Set the raw parameter value for an ordering parameter."""
        return self.set_value(external_id, value, "ordering")
