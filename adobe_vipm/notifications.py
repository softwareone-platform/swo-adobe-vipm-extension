import logging
import os
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

import pymsteams
from django.conf import settings
from jinja2 import Environment, FileSystemLoader, select_autoescape
from mpt_extension_sdk.mpt_http.base import MPTClient
from mpt_extension_sdk.mpt_http.mpt import notify

logger = logging.getLogger(__name__)

NotifyCategories = StrEnum("NotifyCategories", settings.MPT_NOTIFY_CATEGORIES)


def dateformat(date_string):
    return datetime.fromisoformat(date_string).strftime("%-d %B %Y") if date_string else ""


env = Environment(
    loader=FileSystemLoader(
        os.path.join(
            os.path.abspath(os.path.dirname(__file__)),
            "templates",
        ),
    ),
    autoescape=select_autoescape(),
)

env.filters["dateformat"] = dateformat


@dataclass
class Button:
    label: str
    url: str


@dataclass
class FactsSection:
    title: str
    data: dict


def send_notification(
    title: str,
    text: str,
    color: str,
    button: Button | None = None,
    facts: FactsSection | None = None,
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
    title: str,
    text: str,
    button: Button | None = None,
    facts: FactsSection | None = None,
) -> None:
    send_notification(
        f"\u2622 {title}",
        text,
        "#ffa500",
        button=button,
        facts=facts,
    )


def send_error(
    title: str,
    text: str,
    button: Button | None = None,
    facts: FactsSection | None = None,
) -> None:
    send_notification(
        f"\U0001f4a3 {title}",
        text,
        "#df3422",
        button=button,
        facts=facts,
    )


def send_exception(
    title: str,
    text: str,
    button: Button | None = None,
    facts: FactsSection | None = None,
) -> None:
    send_notification(
        f"\U0001f525 {title}",
        text,
        "#541c2e",
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
            NotifyCategories.ORDERS.value,
            account_id,
            buyer_id,
            subject,
            rendered_template,
        )
    except Exception:
        logger.exception(
            f"Cannot send MPT API notification:"
            f" Category: '{NotifyCategories.ORDERS.value}',"
            f" Account ID: '{account_id}',"
            f" Buyer ID: '{buyer_id}',"
            f" Subject: '{subject}',"
            f" Message: '{rendered_template}'"
        )
