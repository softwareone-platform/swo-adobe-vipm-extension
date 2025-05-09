import logging

import pymsteams
import pytest
from mpt_extension_sdk.mpt_http.mpt import NotifyCategories

from adobe_vipm.notifications import (
    Button,
    FactsSection,
    dateformat,
    mpt_notify,
    send_error,
    send_exception,
    send_notification,
    send_warning,
)
from adobe_vipm.shared import mpt_o_client


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
    ],
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


def test_mpt_notify(mocker):
    mocked_template = mocker.MagicMock()
    mocked_template.render.return_value = "rendered-template"
    mocked_jinja_env = mocker.MagicMock()
    mocked_jinja_env.get_template.return_value = mocked_template
    mocker.patch("adobe_vipm.notifications.env", mocked_jinja_env)

    mocked_notify = mocker.patch("adobe_vipm.notifications.notify", autospec=True)
    mpt_notify(
        "account_id", "buyer_id", "email-subject", "template_name", {"test": "context"}
    )

    mocked_jinja_env.get_template.assert_called_once_with("template_name.html")
    mocked_template.render.assert_called_once_with({"test": "context"})
    mocked_notify.assert_called_once_with(
        mpt_o_client,
        "NTC-0000-0006",
        "account_id",
        "buyer_id",
        "email-subject",
        "rendered-template",
    )


def test_mpt_notify_exception(mocker, caplog):
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
            "account_id",
            "buyer_id",
            "email-subject",
            "template_name",
            {"test": "context"},
        )

    assert (
        f"Cannot send MPT API notification:"
        f" Category: '{NotifyCategories.ORDERS.value}',"
        f" Account ID: 'account_id',"
        f" Buyer ID: 'buyer_id',"
        f" Subject: 'email-subject',"
        f" Message: 'rendered-template'"
    ) in caplog.text


def test_dateformat():
    assert dateformat("2024-05-16T10:54:42.831Z") == "16 May 2024"
    assert dateformat("") == ""
    assert dateformat(None) == ""
