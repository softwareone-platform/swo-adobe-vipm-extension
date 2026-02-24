import pytest
from mpt_api_client import MPTClient
from mpt_api_client.http.types import Response
from mpt_api_client.models import Collection, Meta, Pagination
from mpt_api_client.resources.commerce.agreements import Agreement, AgreementsService

from adobe_vipm.migrations.parameters_sync import AgreementClient


@pytest.fixture
def mock_mpt_client(mocker):
    return mocker.MagicMock(spec=MPTClient)


@pytest.fixture
def agreement_client(mock_mpt_client):
    return AgreementClient(mock_mpt_client)


@pytest.fixture
def mock_agreements_service(mocker, agreement_client):
    mock_service = mocker.MagicMock(spec=AgreementsService)
    mock_service.filter.return_value = mock_service
    mock_service.order_by.return_value = mock_service
    mock_service.select.return_value = mock_service
    mocker.patch.object(
        agreement_client,
        "_agreements_service",
        return_value=mock_service,
        spec=True,
    )
    return mock_service


class _FakeMeta:
    def __init__(self, total):
        self.pagination = type("Pagination", (), {"total": total})()


def test_count_returns_total(agreement_client, mock_agreements_service):
    response = Response(headers={}, status_code=200, content=b"")
    meta = Meta(pagination=Pagination(total=42), response=response)
    page = Collection[Agreement](resources=[], meta=meta)
    mock_agreements_service.fetch_page.return_value = page

    result = agreement_client.count("PRD-1234")

    mock_agreements_service.fetch_page.assert_called_once_with(0, 0)
    assert result == 42


def test_count_returns_none_when_meta_is_none(agreement_client, mock_agreements_service):
    page = Collection[Agreement](resources=[], meta=None)
    mock_agreements_service.fetch_page.return_value = page

    result = agreement_client.count("PRD-1234")

    assert result is None


def test_iterate_returns_agreements(mocker, agreement_client, mock_agreements_service):
    agreement_1 = mocker.MagicMock(spec=Agreement)
    agreement_2 = mocker.MagicMock(spec=Agreement)
    mock_agreements_service.iterate.return_value = iter(
        [agreement_1, agreement_2],
    )

    result = list(agreement_client.iterate("PRD-1234"))

    mock_agreements_service.iterate.assert_called_once()
    assert result == [agreement_1, agreement_2]


def test_update_delegates_to_mpt_client(mocker, agreement_client, mock_mpt_client):
    expected_agreement = mocker.MagicMock(spec=Agreement)
    mock_mpt_client.commerce.agreements.update.return_value = expected_agreement
    agreement_data = {"parameters": {"fulfillment": []}}

    result = agreement_client.update("AGR-0001-0002", agreement_data)

    mock_mpt_client.commerce.agreements.update.assert_called_once_with(
        "AGR-0001-0002",
        agreement_data,
    )
    assert result == expected_agreement


def test_agreements_service_applies_filters_and_select(mock_mpt_client):
    mock_service = mock_mpt_client.commerce.agreements
    mock_service.filter.return_value = mock_service
    mock_service.order_by.return_value = mock_service
    mock_service.select.return_value = mock_service
    client = AgreementClient(mock_mpt_client)

    result = client._agreements_service("PRD-9999")

    mock_service.filter.assert_called_once()
    mock_service.order_by.assert_called_once_with("audit.created.at")
    mock_service.select.assert_called_once_with(
        "-listing",
        "-authorization",
        "-vendor",
        "-client",
        "-price",
        "-subscriptions",
        "-template",
        "-lines",
        "-assets",
        "-termsAndConditions",
    )
    assert result == mock_service
