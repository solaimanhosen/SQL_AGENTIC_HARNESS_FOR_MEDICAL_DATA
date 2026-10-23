"""Sending email: password reset links and confirming an address (ADR 0009).

Plain SMTP from the standard library, so any provider works: Gmail with an app password, or
Brevo, Resend or Amazon SES on a domain of your own. Changing provider is a change to these
settings in Backend/.env, never to the code:

    SQL_AGENT_SMTP_HOST=smtp.gmail.com
    SQL_AGENT_SMTP_PORT=587                  # 587 for STARTTLS, 465 for TLS from the start
    SQL_AGENT_SMTP_USERNAME=you@gmail.com
    SQL_AGENT_SMTP_PASSWORD=...              # an app password; a secret, never commit it
    SQL_AGENT_MAIL_FROM=SQL Agent <you@gmail.com>

Email is off unless the host, username, password and From address are all set. The password
is read here and kept out of Settings, like the Anthropic key and Google's secret, so
printing the settings can never show it.

Send one test message, from the Backend folder:

    .venv/bin/python -m sql_agent.mailer you@example.org
"""

from __future__ import annotations

import argparse
import os
import smtplib
import ssl
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import make_msgid, parseaddr
from typing import Protocol

from .config import ConfigError, load_settings

DEFAULT_PORT = 587
IMPLICIT_TLS_PORT = 465
TIMEOUT_SECONDS = 15
# The name the interface shows, so a message is recognisably from it.
PRODUCT = "Patient data questions"


class MailError(RuntimeError):
    """The message could not be handed to the mail server."""


class Mailer(Protocol):
    def send(self, to: str, subject: str, text: str) -> None: ...


@dataclass(frozen=True)
class SmtpMailer:
    host: str
    port: int
    username: str
    password: str = field(repr=False)
    sender: str

    def send(self, to: str, subject: str, text: str) -> None:
        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = to
        message["Subject"] = subject
        message["Message-ID"] = make_msgid(domain=parseaddr(self.sender)[1].rpartition("@")[2] or None)
        message.set_content(text)
        try:
            with self._connect() as smtp:
                smtp.send_message(message)
        except (smtplib.SMTPException, OSError) as exc:
            raise MailError(f"{type(exc).__name__}: {exc}") from exc

    def check(self) -> None:
        """Connect and sign in without sending anything, for the setup check."""
        try:
            with self._connect():
                pass
        except (smtplib.SMTPException, OSError) as exc:
            raise MailError(f"{type(exc).__name__}: {exc}") from exc

    def _connect(self) -> smtplib.SMTP:
        context = ssl.create_default_context()
        if self.port == IMPLICIT_TLS_PORT:
            smtp: smtplib.SMTP = smtplib.SMTP_SSL(self.host, self.port, timeout=TIMEOUT_SECONDS, context=context)
        else:
            smtp = smtplib.SMTP(self.host, self.port, timeout=TIMEOUT_SECONDS)
            try:
                smtp.starttls(context=context)
            except BaseException:
                smtp.close()
                raise
        try:
            smtp.login(self.username, self.password)
        except BaseException:
            smtp.close()
            raise
        return smtp


def load_mailer(env: Mapping[str, str] | None = None) -> SmtpMailer | None:
    """The mailer from the SQL_AGENT_SMTP_* settings, or None when any required one is unset."""
    env = os.environ if env is None else env
    host = env.get("SQL_AGENT_SMTP_HOST", "").strip()
    username = env.get("SQL_AGENT_SMTP_USERNAME", "").strip()
    password = env.get("SQL_AGENT_SMTP_PASSWORD", "").strip()
    sender = env.get("SQL_AGENT_MAIL_FROM", "").strip()
    if not host or not username or not password or not sender:
        return None
    raw_port = env.get("SQL_AGENT_SMTP_PORT", "").strip() or str(DEFAULT_PORT)
    if not raw_port.isdigit() or not 0 < int(raw_port) < 65536:
        raise ConfigError(f"SQL_AGENT_SMTP_PORT must be a port number, such as 587 or 465, not {raw_port!r}.")
    if "@" not in parseaddr(sender)[1]:
        raise ConfigError("SQL_AGENT_MAIL_FROM must hold an address, such as: SQL Agent <you@gmail.com>")
    return SmtpMailer(host, int(raw_port), username, password, sender)


# The messages the service sends -------------------------------------------------------


def reset_message(email: str, link: str, minutes: int) -> tuple[str, str]:
    return (
        f"Reset your password for {PRODUCT}",
        f"Someone asked to reset the password of {email} on {PRODUCT}.\n\n"
        f"To choose a new password, open this link within {minutes} minutes:\n\n{link}\n\n"
        "The link works once, and signs out every browser that is signed in to the account.\n"
        "If you did not ask for this, ignore this email. Your password stays as it is.\n",
    )


def verify_message(email: str, link: str, days: int) -> tuple[str, str]:
    return (
        f"Confirm your email for {PRODUCT}",
        f"Confirm that {email} is your address by opening this link within {days} days:\n\n{link}\n\n"
        "Once it is confirmed, signing in with Google as this address reaches the same account.\n"
        "If you did not make this account, ignore this email.\n",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Send one test email with the SQL_AGENT_SMTP_* settings.")
    parser.add_argument("to", help="the address to send it to")
    args = parser.parse_args(argv)
    try:
        load_settings()  # reads Backend/.env into the environment
        mailer = load_mailer()
    except ConfigError as exc:
        print(f"Settings error: {exc}", file=sys.stderr)
        return 1
    if mailer is None:
        print(
            "Email is off. Set SQL_AGENT_SMTP_HOST, SQL_AGENT_SMTP_USERNAME, SQL_AGENT_SMTP_PASSWORD "
            "and SQL_AGENT_MAIL_FROM in Backend/.env.",
            file=sys.stderr,
        )
        return 1
    try:
        mailer.send(
            args.to,
            f"{PRODUCT} test email",
            f"This is a test from {PRODUCT}. Email works, so password reset links can be sent.\n",
        )
    except MailError as exc:
        print(f"Could not send through {mailer.host}:{mailer.port}: {exc}", file=sys.stderr)
        return 1
    print(f"Sent to {args.to} through {mailer.host}:{mailer.port} as {mailer.sender}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
