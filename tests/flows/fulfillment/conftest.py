import pytest


@pytest.fixture()
def mock_sync_agreement(mocker):
    return mocker.patch("adobe_vipm.flows.fulfillment.base.sync_agreement", spec=True)


@pytest.fixture()
def mock_get_agreement(mocker):
    return mocker.patch("adobe_vipm.flows.fulfillment.base.get_agreement", spec=True)
