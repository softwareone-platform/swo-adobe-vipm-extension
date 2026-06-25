import json
import logging

import pytest
import requests

from adobe_vipm.notifications import (
    Button,
    FactsSection,
    Style,
    dateformat,
    mpt_notify,
    send_error,
    send_exception,
    send_notification,
    send_warning,
)


def test_send_notification_full(settings, requests_mocker):
    settings.EXTENSION_CONFIG = {
        "MSTEAMS_WEBHOOK_URL": "https://teams.webhook",
    }
    requests_mocker.post("https://teams.webhook", status=200)
    button = Button("button-label", "button-url")
    facts_section = FactsSection("section-title", {"key": "value"})

    send_notification(
        "not-title",
        "not-text",
        Style.WARNING,
        button=button,
        facts=facts_section,
    )  # act

    payload = json.loads(requests_mocker.calls[0].request.body)
    card = payload["attachments"][0]["content"]
    card_body = card["body"]
    title_container = card_body[0]["items"][0]
    fact_sets = [block for block in card_body if block.get("type") == "FactSet"]
    assert (
        payload["type"],
        card["type"],
        card_body[1]["text"],
        card["actions"],
        fact_sets[0]["facts"],
    ) == (
        "message",
        "AdaptiveCard",
        "not-text",
        [{"type": "Action.OpenUrl", "title": "button-label", "url": "button-url"}],
        [{"title": "key", "value": "value"}],
    )
    assert title_container["text"] == "not-title"
    assert (
        card_body[0]["style"],
        title_container["weight"],
        title_container["size"],
        title_container["color"],
    ) == ("warning", "bolder", "large", "warning")
    assert any(block.get("text") == "section-title" for block in card_body)


def test_send_notification_coerces_facts_to_strings(settings, requests_mocker):
    settings.EXTENSION_CONFIG = {
        "MSTEAMS_WEBHOOK_URL": "https://teams.webhook",
    }
    requests_mocker.post("https://teams.webhook", status=200)

    send_notification(
        "not-title",
        "not-text",
        Style.WARNING,
        facts=FactsSection("section-title", {9999: 123}),
    )  # act

    payload = json.loads(requests_mocker.calls[0].request.body)
    card_body = payload["attachments"][0]["content"]["body"]
    fact_sets = [block for block in card_body if block.get("type") == "FactSet"]
    assert fact_sets[0]["facts"] == [{"title": "9999", "value": "123"}]


def test_send_notification_simple(settings, requests_mocker):
    settings.EXTENSION_CONFIG = {
        "MSTEAMS_WEBHOOK_URL": "https://teams.webhook",
    }
    requests_mocker.post("https://teams.webhook", status=200)

    send_notification("not-title", "not-text", Style.WARNING)  # act

    payload = json.loads(requests_mocker.calls[0].request.body)
    card = payload["attachments"][0]["content"]
    assert "actions" not in card
    assert len(card["body"]) == 2


def test_send_notification_exception(settings, requests_mocker, caplog):
    settings.EXTENSION_CONFIG = {
        "MSTEAMS_WEBHOOK_URL": "https://teams.webhook",
    }
    requests_mocker.post("https://teams.webhook", body=requests.ConnectionError("error"))

    with caplog.at_level(logging.ERROR):
        send_notification("not-title", "not-text", Style.WARNING)  # act

    assert "Error sending notification to MSTeams!" in caplog.text


def test_send_notification_exception_on_raise_for_status(settings, requests_mocker, caplog):
    settings.EXTENSION_CONFIG = {
        "MSTEAMS_WEBHOOK_URL": "https://teams.webhook",
    }
    requests_mocker.post("https://teams.webhook", status=500)

    with caplog.at_level(logging.ERROR):
        send_notification("not-title", "not-text", Style.WARNING)  # act

    assert "Error sending notification to MSTeams!" in caplog.text


def test_send_warning(mocker):
    mock_send_notification = mocker.patch("adobe_vipm.notifications.send_notification")
    mocked_button = mocker.MagicMock()
    mocked_facts_section = mocker.MagicMock()

    send_warning("title", "text", button=mocked_button, facts=mocked_facts_section)  # act

    mock_send_notification.assert_called_once_with(
        "\u2622 title",
        "text",
        Style.WARNING,
        button=mocked_button,
        facts=mocked_facts_section,
    )


def test_send_error(mocker):
    mock_send_notification = mocker.patch("adobe_vipm.notifications.send_notification")
    mocked_button = mocker.MagicMock()
    mocked_facts_section = mocker.MagicMock()

    send_error("title", "text", button=mocked_button, facts=mocked_facts_section)  # act

    mock_send_notification.assert_called_once_with(
        "\U0001f4a3 title",
        "text",
        Style.ATTENTION,
        button=mocked_button,
        facts=mocked_facts_section,
    )


def test_send_exception(mocker):
    mock_send_notification = mocker.patch("adobe_vipm.notifications.send_notification")
    mocked_button = mocker.MagicMock()
    mocked_facts_section = mocker.MagicMock()

    send_exception("title", "text", button=mocked_button, facts=mocked_facts_section)  # act

    mock_send_notification.assert_called_once_with(
        "\U0001f525 title",
        "text",
        Style.ATTENTION,
        button=mocked_button,
        facts=mocked_facts_section,
    )


def test_mpt_notify(mocker, mock_mpt_client):
    mocked_template = mocker.MagicMock()
    mocked_template.render.return_value = "rendered-template"
    mocked_jinja_env = mocker.MagicMock()
    mocked_jinja_env.get_template.return_value = mocked_template
    mocker.patch("adobe_vipm.notifications.env", mocked_jinja_env)
    mocked_notify = mocker.patch("adobe_vipm.notifications.notify", autospec=True)

    mpt_notify(
        mock_mpt_client,
        "account_id",
        "buyer_id",
        "email-subject",
        "template_name",
        {"test": "context"},
    )  # act

    mocked_jinja_env.get_template.assert_called_once_with("template_name.html")
    mocked_template.render.assert_called_once_with({"test": "context"})
    mocked_notify.assert_called_once_with(
        mock_mpt_client,
        "NTC-0000-0006",
        "account_id",
        "buyer_id",
        "email-subject",
        "rendered-template",
    )


def test_mpt_notify_exception(mocker, mock_mpt_client, caplog):
    mocked_template = mocker.MagicMock()
    mocked_template.render.return_value = "rendered-template"
    mocked_jinja_env = mocker.MagicMock()
    mocked_jinja_env.get_template.return_value = mocked_template
    mocker.patch("adobe_vipm.notifications.env", mocked_jinja_env)
    mocker.patch(
        "adobe_vipm.notifications.notify",
        autospec=True,
        side_effect=Exception("error"),
    )

    with caplog.at_level(logging.ERROR):
        mpt_notify(
            mock_mpt_client,
            "account_id",
            "buyer_id",
            "email-subject",
            "template_name",
            {"test": "context"},
        )  # act

    assert (
        "Cannot send MPT API notification:"
        " Category: 'NTC-0000-0006',"
        " Account ID: 'account_id',"
        " Buyer ID: 'buyer_id',"
        " Subject: 'email-subject',"
        " Message: 'rendered-template'"
    ) in caplog.text


@pytest.mark.parametrize(
    ("date_time", "expected_result"),
    [
        pytest.param("2024-05-16T10:54:42.831Z", "16 May 2024", id="datetime with timezone"),
        pytest.param("", "", id="empty string"),
        pytest.param(None, "", id="None datetime"),
    ],
)
def test_dateformat(date_time, expected_result):
    result = dateformat(date_time)

    assert result == expected_result
