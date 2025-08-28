import pytest
from mpt_extension_sdk.mpt_http.mpt import get_agreements_by_query


@pytest.fixture()
def mock_get_agreements_by_query(mocker):
    mock = mocker.MagicMock(spec=get_agreements_by_query)
    mocker.patch(
        "adobe_vipm.flows.mpt.get_agreements_by_query",
        new=mock,
    )
    mocker.patch(
        "adobe_vipm.flows.sync.get_agreements_by_query",
        new=mock,
    )
    return mock
