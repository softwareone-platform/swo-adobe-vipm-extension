import logging
import os
from dataclasses import dataclass
from datetime import datetime

import boto3
import pymsteams
from django.conf import settings
from jinja2 import Environment, FileSystemLoader, select_autoescape

logger = logging.getLogger(__name__)


def dateformat(date_string):
    return (
        datetime.fromisoformat(date_string).strftime("%-d %B %Y") if date_string else ""
    )


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


def send_email(recipient, subject, template_name, context):
    template = env.get_template(f"{template_name}.html")
    rendered_email = template.render(context)

    access_key, secret_key = settings.EXTENSION_CONFIG["AWS_SES_CREDENTIALS"].split(":")

    client = boto3.client(
        "ses",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=settings.EXTENSION_CONFIG["AWS_SES_REGION"],
    )
    try:
        client.send_email(
            Source=settings.EXTENSION_CONFIG["EMAIL_NOTIFICATIONS_SENDER"],
            Destination={
                "ToAddresses": [recipient],
            },
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {
                    "Html": {"Data": rendered_email, "Charset": "UTF-8"},
                },
            },
        )
    except Exception:
        logger.exception(
            f"Cannot send notification email with subject '{subject}' to: {recipient}",
        )
