import logging

import pymsteams
import pytest

from adobe_vipm.notifications import (
    Button,
    FactsSection,
    send_error,
    send_exception,
    send_notification,
    send_warning,
)


def test_send_notification_full(mocker, settings):
    settings.EXTENSION_CONFIG = {
        "MSTEAMS_WEBHOOK_URL": "https://teams.webhook",
    }
    mocked_message = mocker.MagicMock()
    mocked_section = mocker.MagicMock()

    mocked_card = mocker.patch(
        "adobe_vipm.notifications.pymsteams.connectorcard",
        return_value=mocked_message,
    )

    mocker.patch(
        "adobe_vipm.notifications.pymsteams.cardsection",
        return_value=mocked_section,
    )

    button = Button("button-label", "button-url")
    facts_section = FactsSection("section-title", {"key": "value"})

    send_notification(
        "not-title",
        "not-text",
        "not-color",
        button=button,
        facts=facts_section,
    )

    mocked_message.title.assert_called_once_with("not-title")
    mocked_message.text.assert_called_once_with("not-text")
    mocked_message.color.assert_called_once_with("not-color")
    mocked_message.addLinkButton.assert_called_once_with(button.label, button.url)
    mocked_section.title.assert_called_once_with(facts_section.title)
    mocked_section.addFact.assert_called_once_with(
        list(facts_section.data.keys())[0], list(facts_section.data.values())[0]
    )
    mocked_message.addSection.assert_called_once_with(mocked_section)
    mocked_message.send.assert_called_once()
    mocked_card.assert_called_once_with("https://teams.webhook")


def test_send_notification_simple(mocker, settings):
    settings.EXTENSION_CONFIG = {
        "MSTEAMS_WEBHOOK_URL": "https://teams.webhook",
    }
    mocked_message = mocker.MagicMock()

    mocker.patch(
        "adobe_vipm.notifications.pymsteams.connectorcard",
        return_value=mocked_message,
    )

    mocked_cardsection = mocker.patch(
        "adobe_vipm.notifications.pymsteams.cardsection",
    )

    send_notification(
        "not-title",
        "not-text",
        "not-color",
    )

    mocked_message.title.assert_called_once_with("not-title")
    mocked_message.text.assert_called_once_with("not-text")
    mocked_message.color.assert_called_once_with("not-color")
    mocked_message.addLinkButton.assert_not_called()
    mocked_cardsection.assert_not_called()
    mocked_message.send.assert_called_once()


def test_send_notification_exception(mocker, settings, caplog):
    settings.EXTENSION_CONFIG = {
        "MSTEAMS_WEBHOOK_URL": "https://teams.webhook",
    }
    mocked_message = mocker.MagicMock()
    mocked_message.send.side_effect = pymsteams.TeamsWebhookException("error")

    mocker.patch(
        "adobe_vipm.notifications.pymsteams.connectorcard",
        return_value=mocked_message,
    )

    with caplog.at_level(logging.ERROR):
        send_notification(
            "not-title",
            "not-text",
            "not-color",
        )

    assert "Error sending notification to MSTeams!" in caplog.text


@pytest.mark.parametrize(
    ("function", "color", "icon"),
    [
        (send_warning, "#ffa500", "\u2622"),
        (send_error, "#df3422", "\U0001f4a3"),
        (send_exception, "#541c2e", "\U0001f525"),
    ]
)
def test_send_others(mocker, function, color, icon):
    mocked_send_notification = mocker.patch(
        "adobe_vipm.notifications.send_notification",
    )

    mocked_button = mocker.MagicMock()
    mocked_facts_section = mocker.MagicMock()

    function("title", "text", button=mocked_button, facts=mocked_facts_section)

    mocked_send_notification.assert_called_once_with(
        f"{icon} title",
        "text",
        color,
        button=mocked_button,
        facts=mocked_facts_section,
    )
