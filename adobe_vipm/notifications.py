import datetime as dt
import enum
import logging
from dataclasses import dataclass
from pathlib import Path

import requests
from django.conf import settings
from jinja2 import Environment, FileSystemLoader, select_autoescape
from mpt_extension_sdk.mpt_http.base import MPTClient
from mpt_extension_sdk.mpt_http.mpt import notify

from adobe_vipm.adobe.constants import MPT_NOTIFY_CATEGORIES

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT = 10


class Style(enum.Enum):
    """Adaptive Card style token, used for both Container.style and TextBlock.color.

    Values are the case-sensitive lower-case Adaptive Card enum tokens.
    """

    WARNING = "warning"
    ATTENTION = "attention"


def dateformat(date_string: str) -> str:
    """Adjusts format of date strings for jinja notification templates."""
    return dt.datetime.fromisoformat(date_string).strftime("%-d %B %Y") if date_string else ""


env = Environment(
    loader=FileSystemLoader(
        Path(__file__).resolve().parent / "templates",
    ),
    autoescape=select_autoescape(),
)

env.filters["dateformat"] = dateformat


@dataclass
class Button:
    """Teams button."""

    label: str
    url: str


@dataclass
class FactsSection:
    """Facts section."""

    title: str
    data: dict


def _build_card(
    title: str,
    text: str,
    style: Style,
    button: Button | None,
    facts: FactsSection | None,
) -> dict:
    """Builds the Adaptive Card payload wrapped in the Workflows envelope."""
    body: list[dict] = [
        {
            "type": "Container",
            "style": style.value,
            "bleed": True,
            "items": [
                {
                    "type": "TextBlock",
                    "text": title,
                    "weight": "bolder",
                    "size": "large",
                    "color": style.value,
                    "wrap": True,
                },
            ],
        },
        {"type": "TextBlock", "text": text, "wrap": True},
    ]

    if facts:
        if facts.title:
            body.append(
                {"type": "TextBlock", "text": facts.title, "weight": "bolder", "wrap": True},
            )
        body.append(
            {
                "type": "FactSet",
                "facts": [
                    {"title": str(key), "value": str(fact_value)}
                    for key, fact_value in facts.data.items()
                ],
            },
        )

    card: dict = {
        "$schema": "https://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.4",
        "msteams": {"width": "Full"},
        "body": body,
    }

    if button:
        card["actions"] = [
            {"type": "Action.OpenUrl", "title": button.label, "url": button.url},
        ]

    return {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": card,
            },
        ],
    }


def send_notification(
    title: str,
    text: str,
    style: Style,
    button: Button | None = None,
    facts: FactsSection | None = None,
) -> None:
    """Sends an Adaptive Card to the MS Teams Workflow webhook."""
    payload = _build_card(title, text, style, button, facts)

    try:
        requests.post(
            settings.EXTENSION_CONFIG["MSTEAMS_WEBHOOK_URL"],
            json=payload,
            timeout=_REQUEST_TIMEOUT,
        ).raise_for_status()
    except requests.RequestException:
        logger.exception("Error sending notification to MSTeams!")


def send_warning(
    title: str,
    text: str,
    button: Button | None = None,
    facts: FactsSection | None = None,
) -> None:
    """Send warning to the Teams channel."""
    send_notification(
        f"\u2622 {title}",
        text,
        Style.WARNING,
        button=button,
        facts=facts,
    )


def send_error(
    title: str,
    text: str,
    button: Button | None = None,
    facts: FactsSection | None = None,
) -> None:
    """Send error to the Teams channel."""
    send_notification(
        f"\U0001f4a3 {title}",
        text,
        Style.ATTENTION,
        button=button,
        facts=facts,
    )


def send_exception(
    title: str,
    text: str,
    button: Button | None = None,
    facts: FactsSection | None = None,
) -> None:
    """Send exception to the Teams channel."""
    send_notification(
        f"\U0001f525 {title}",
        text,
        Style.ATTENTION,
        button=button,
        facts=facts,
    )


def mpt_notify(
    mpt_client: MPTClient,
    account_id: str,
    buyer_id: str,
    subject: str,
    template_name: str,
    context: dict,
) -> None:
    """
    Sends a notification through the MPT API using a specified template and context.

    Raises:
    Exception
        Logs the exception if there is an issue during the notification process,
        including the category, subject, and the rendered message.
    """
    template = env.get_template(f"{template_name}.html")
    rendered_template = template.render(context)

    try:
        notify(
            mpt_client,
            MPT_NOTIFY_CATEGORIES["ORDERS"],
            account_id,
            buyer_id,
            subject,
            rendered_template,
        )
    except Exception:
        logger.exception(
            "Cannot send MPT API notification: Category: '%s', Account ID: '%s',"
            " Buyer ID: '%s', Subject: '%s', Message: '%s'",
            MPT_NOTIFY_CATEGORIES["ORDERS"],
            account_id,
            buyer_id,
            subject,
            rendered_template,
        )
