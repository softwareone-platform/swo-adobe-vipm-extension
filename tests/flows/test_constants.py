from collections import defaultdict

from adobe_vipm.flows import constants
from adobe_vipm.flows.errors import ValidationError

# Ids two errors already shared before uniqueness was checked; do not add to this.
KNOWN_SHARED_IDS = {
    "VIPM0005": {"ERR_ADOBE_MEMBERSHIP_ID", "ERR_ADOBE_AGENCY_TYPE"},
    "VIPM0011": {"ERR_CONTACT", "ERR_ADOBE_ERROR"},
    "VIPM0034": {"ERR_COMMITMENT_3YC_VALIDATION", "ERR_COTERM_DATE_IN_LAST_24_HOURS"},
    "VIPM0036": {"ERR_ADOBE_RESSELLER_CHANGE_PREVIEW", "ERR_ADOBE_RESSELLER_CHANGE_LINES"},
    "VIPM0038": {"ERR_ADOBE_GOVERNMENT_VALIDATE_IS_LGA", "ERR_SKU_AVAILABILITY"},
    "VIPM0039": {"ERR_ADOBE_GOVERNMENT_VALIDATE_IS_NOT_LGA", "ERR_CUSTOMER_LOST_EXCEPTION"},
}


def test_validation_error_ids_are_unique():
    names_by_id = defaultdict(set)
    for name, value in vars(constants).items():
        if isinstance(value, ValidationError):
            names_by_id[value.id].add(name)

    result = {
        error_id: names
        for error_id, names in names_by_id.items()
        if len(names) > 1 and KNOWN_SHARED_IDS.get(error_id) != names
    }

    assert result == {}
