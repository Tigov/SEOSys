"""Words for every email the app sends. Each template returns a subject, plain text and HTML."""
from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Any, Callable

from .config import settings


@dataclass(frozen=True)
class Email:
    subject: str
    text: str
    html: str


def _render(subject: str, greeting: str, paragraphs: list[str], button: tuple[str, str] | None = None,
            footer: str = "") -> Email:
    """One layout for every email. `button` is (label, url)."""
    name = settings.app_name
    text_parts = [greeting, *paragraphs]
    html_parts = [f"<p>{escape(greeting)}</p>", *(f"<p>{escape(p)}</p>" for p in paragraphs)]
    if button:
        label, url = button
        text_parts.append(f"{label}: {url}")
        html_parts.append(
            f'<p><a href="{escape(url, quote=True)}" style="display:inline-block;padding:10px 18px;background:#1f4d3a;'
            f'color:#ffffff;text-decoration:none;border-radius:6px">{escape(label)}</a></p>'
            f'<p style="color:#666;font-size:13px">Or paste this link into your browser: {escape(url)}</p>')
    closing = footer or f"If you didn't expect this email, you can ignore it."
    text_parts += [closing, f"— {name}"]
    html_parts += [f'<p style="color:#666;font-size:13px">{escape(closing)}</p>', f"<p>— {escape(name)}</p>"]
    html = ('<div style="font-family:Segoe UI,Arial,sans-serif;font-size:15px;line-height:1.5;color:#1b1b1b;'
            'max-width:560px">' + "".join(html_parts) + "</div>")
    return Email(subject, "\n\n".join(text_parts), html)


def _hi(ctx: dict[str, Any]) -> str:
    return f"Hi {ctx['name']}," if ctx.get("name") else "Hi,"


TEMPLATES: dict[str, Callable[[dict[str, Any]], Email]] = {
    "verify": lambda c: _render(
        "Confirm your email address", _hi(c),
        ["Please confirm this is your email address. The link works for 24 hours."],
        ("Confirm email address", c["url"])),
    "reset": lambda c: _render(
        "Reset your password", _hi(c),
        ["Someone asked to reset the password for your account. The link works for 30 minutes and can be used once.",
         "Resetting your password signs you out on every other device."],
        ("Choose a new password", c["url"]),
        "If you didn't ask for this, ignore this email. Your password stays the same."),
    "already_registered": lambda c: _render(
        "You already have an account", _hi(c),
        ["Someone tried to create an account with this email address, but you already have one.",
         "If that was you, log in instead. If you've forgotten your password, you can reset it from the login page."],
        ("Log in", c["url"])),
    "link_google": lambda c: _render(
        "Confirm signing in with Google", _hi(c),
        ["Someone tried to sign in with a Google account that uses this email address. "
         "To let that Google account sign in to your existing account, confirm below. The link works for 30 minutes."],
        ("Allow Google sign-in", c["url"]),
        "If this wasn't you, ignore this email and nothing changes."),
    "invite": lambda c: _render(
        f"{c['inviter']} invited you to {c['client']} on {settings.app_name}", "Hi,",
        [f"{c['inviter']} invited you to see {c['client']}'s SEO work on {settings.app_name}. The invitation works for 7 days."],
        ("Accept invitation", c["url"])),
    "welcome": lambda c: _render(
        f"Welcome to {settings.app_name}", _hi(c),
        [f"Thanks for choosing the {c['plan']} package for {c['client']}.",
         "Next, add your website and connect Google so we can start your first audit."],
        ("Open your dashboard", c["url"])),
    "payment_failed": lambda c: _render(
        "Your payment didn't go through", _hi(c),
        [f"We couldn't take the payment for {c['client']}. Your dashboard still works, but new changes to your website "
         "are paused until the payment goes through.", "Update your card to carry on."],
        ("Update payment details", c["url"])),
    "mfa_changed": lambda c: _render(
        f"Two-step login was turned {c['state']}", _hi(c),
        [f"Two-step login was turned {c['state']} for your account."],
        None, "If you didn't do this, reset your password straight away and contact us."),
    "new_device": lambda c: _render(
        "New sign-in to your account", _hi(c),
        [f"Your account was just signed in to from {c['device']} ({c['ip']})."],
        None, "If this wasn't you, reset your password straight away."),
}


def render(template: str, context: dict[str, Any]) -> Email:
    return TEMPLATES[template](context)
