import logging
from dataclasses import dataclass

import pymsteams
from django.conf import settings

logger = logging.getLogger(__name__)


@dataclass
class Button:
    label: str
    url: str


@dataclass
class FactsSection:
    title: str
    data: dict


def send_notification(
    title: str, text: str, color: str, button: Button = None, facts: FactsSection = None
) -> None:
    message = pymsteams.connectorcard(settings.EXTENSION_CONFIG["MSTEAMS_WEBHOOK_URL"])
    message.color(color)
    message.title(title)
    message.text(text)
    if button:
        message.addLinkButton(button.label, button.url)
    if facts:
        facts_section = pymsteams.cardsection()
        facts_section.title(facts.title)
        for key, value in facts.data.items():
            facts_section.addFact(key, value)
        message.addSection(facts_section)

    try:
        message.send()
    except pymsteams.TeamsWebhookException:
        logger.exception("Error sending notification to MSTeams!")


def send_warning(
    title, text, button: Button = None, facts: FactsSection = None
) -> None:
    send_notification(
        f"\u2622 {title}",
        text,
        "#ffa500",
        button=button,
        facts=facts,
    )


def send_error(title, text, button: Button = None, facts: FactsSection = None) -> None:
    send_notification(
        f"\U0001f4a3 {title}",
        text,
        "#df3422",
        button=button,
        facts=facts,
    )


def send_exception(
    title, text, button: Button = None, facts: FactsSection = None
) -> None:
    send_notification(
        f"\U0001f525 {title}",
        text,
        "#541c2e",
        button=button,
        facts=facts,
    )
