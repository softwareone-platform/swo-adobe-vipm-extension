from collections.abc import Callable, Iterable
from typing import Any, Self

from mpt_api_client.models.model import ModelList
from pydantic import Field, field_serializer, field_validator

from mpt_extension_sdk_v6.models.base import BaseModel


def _normalize_parameter_value(param_value: Any) -> Any:
    if isinstance(param_value, dict):
        return {
            item_key: _normalize_parameter_value(item_value)
            for item_key, item_value in param_value.items()
        }

    if isinstance(param_value, list | tuple | ModelList):
        return [_normalize_parameter_value(element) for element in param_value]

    if hasattr(param_value, "to_dict") and callable(param_value.to_dict):
        return _normalize_parameter_value(param_value.to_dict())

    return param_value


class Constraints(BaseModel):
    """Constraints for a parameter."""

    hidden: bool | None = None
    readonly: bool | None = None
    required: bool | None = None


class ParameterValue(BaseModel):
    """Single ordering or fulfillment parameter value."""

    id: str | None = None
    display_value: str | None = Field(default=None, alias="displayValue")
    external_id: str | None = Field(default=None, alias="externalId")
    multiple: bool | None = None
    name: str | None = None
    phase: str | None = None
    scope: str | None = None
    type: str | None = None
    # TODO: add enum
    value: Any = None  # noqa: WPS110

    constraints: Constraints = Field(default_factory=Constraints)

    @field_validator("value", mode="before")
    @classmethod
    def _normalize_value(cls, param_value: Any) -> Any:
        return _normalize_parameter_value(param_value)

    @field_serializer("value")
    def _serialize_value(self, param_value: Any) -> Any:
        return _normalize_parameter_value(param_value)


class ParameterBag(BaseModel):
    """Container for ordering and fulfillment parameters."""

    fulfillment: list[ParameterValue] = Field(default_factory=list)
    ordering: list[ParameterValue] = Field(default_factory=list)

    def with_fulfillment_error(self, external_id: str, error: dict[str, Any]) -> Self:
        """Return a copy with an updated fulfillment parameter error."""
        return self._with_error(external_id, error, "fulfillment")

    def with_fulfillment_value(self, external_id: str, new_value: Any) -> Self:
        """Return a copy with an updated fulfillment parameter value."""
        return self._with_value(external_id, new_value, "fulfillment")

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

    def get_parameter(self, external_id: str, phase: str) -> ParameterValue | None:
        """Return the parameter matching an external ID within a phase."""
        phase_param = getattr(self, phase) or []
        return next(
            (element for element in phase_param if element.external_id == external_id), None
        )

    def get_fulfillment_value(self, external_id: str) -> Any:
        """Return the raw value for a fulfillment parameter."""
        return self._get_param_value(external_id, "fulfillment")

    def get_ordering_value(self, external_id: str) -> Any:
        """Return the raw value for an ordering parameter."""
        return self._get_param_value(external_id, "ordering")

    def with_ordering_error(self, external_id: str, error: dict[str, Any]) -> Self:
        """Return a copy with an updated ordering parameter error."""
        return self._with_error(external_id, error, "ordering")

    def with_ordering_value(self, external_id: str, new_value: Any) -> Self:
        """Return a copy with an updated ordering parameter value."""
        return self._with_value(external_id, new_value, "ordering")

    def with_visibility(self, visible_params: Iterable[str]) -> Self:
        """Return a copy with parameter visibility recalculated for all phases."""
        visible_set = set(visible_params)
        return self.model_copy(
            update={
                "ordering": self._with_phase_visibility(self.ordering, visible_set),
                "fulfillment": self._with_phase_visibility(self.fulfillment, visible_set),
            }
        )

    def _get_param_value(self, external_id: str, phase: str) -> Any:
        """Return the raw parameter value for an external ID within a phase."""
        parameter = self.get_parameter(external_id, phase)
        return None if parameter is None else parameter.value

    def _with_error(self, external_id: str, error: dict[str, Any], phase: str) -> Self:
        """Return a copy with an updated parameter error for a phase."""
        return self._with_parameter(
            external_id,
            phase,
            lambda parameter: parameter.model_copy(
                update={
                    "error": error,
                    "constraints": Constraints(hidden=False, required=True),
                }
            ),
        )

    def _with_parameter(
        self,
        external_id: str,
        phase: str,
        updater: Callable,
        default_parameter: ParameterValue | None = None,
    ) -> Self:
        """Return a copy with an updated or appended parameter for a phase."""
        updated_parameters: list[ParameterValue] = []
        is_updated = False
        for parameter in list(getattr(self, phase)):
            if parameter.external_id == external_id:
                updated_parameters.append(updater(parameter))
                is_updated = True
                continue

            updated_parameters.append(parameter)

        if not is_updated:
            updated_parameters.append(
                default_parameter or updater(ParameterValue(externalId=external_id))
            )

        return self.model_copy(update={phase: updated_parameters})

    def _with_value(self, external_id: str, new_value: Any, phase: str) -> Self:
        """Return a copy with an updated parameter value for a phase."""
        return self._with_parameter(
            external_id,
            phase,
            lambda parameter: parameter.model_copy(update={"value": new_value}),
            default_parameter=ParameterValue(externalId=external_id, value=new_value),
        )

    def _with_phase_visibility(
        self,
        param_values: list[ParameterValue],
        visible_params: set[str],
    ) -> list[ParameterValue]:
        """Return a phase copy with updated visibility flags."""
        return [
            parameter.model_copy(
                update={
                    "constraints": parameter.constraints.model_copy(
                        update={"hidden": parameter.external_id not in visible_params}
                    )
                }
            )
            for parameter in param_values
        ]
