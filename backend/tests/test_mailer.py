"""Email outbox: transactional queueing, retries and every template."""
import pytest

from seo_platform import clock, mailer
from seo_platform.email_copy import TEMPLATES, render

CONTEXT = {"name": "Sam", "url": "http://localhost:8000/x", "inviter": "Pat", "client": "Acme", "plan": "Local",
           "state": "on", "device": "Firefox on Windows", "ip": "203.0.113.5"}


def test_queued_email_is_sent(db):
    out = mailer.Outbox()
    mailer.queue(db, "sam@example.com", "verify", name="Sam", url="http://localhost:8000/v/abc")
    assert mailer.send_pending(db, out) == 1
    assert out.last_link("sam@example.com") == "http://localhost:8000/v/abc"
    assert mailer.send_pending(db, out) == 0  # never twice


def test_rolled_back_action_sends_nothing(db):
    with pytest.raises(RuntimeError):
        with db.transaction():
            mailer.queue(db, "sam@example.com", "verify", name="Sam", url="http://x")
            raise RuntimeError("action failed")
    assert mailer.send_pending(db, mailer.Outbox()) == 0


def test_failed_send_retries_then_marks_failed(db):
    def broken(_msg):
        raise OSError("mail server down")

    mailer.queue(db, "sam@example.com", "verify", name="Sam", url="http://x")
    for _ in range(mailer.MAX_ATTEMPTS):
        mailer.send_pending(db, broken)
        clock.advance(hours=2)
    row = db.one("SELECT status, attempts, last_error FROM email_outbox")
    assert row["status"] == "failed" and row["attempts"] == mailer.MAX_ATTEMPTS and "mail server down" in row["last_error"]


def test_failed_send_is_retried_later(db):
    calls = []

    def flaky(msg):
        calls.append(msg)
        if len(calls) == 1:
            raise OSError("temporary")

    mailer.queue(db, "sam@example.com", "verify", name="Sam", url="http://x")
    assert mailer.send_pending(db, flaky) == 0
    assert mailer.send_pending(db, flaky) == 0  # backing off
    clock.advance(minutes=5)
    assert mailer.send_pending(db, flaky) == 1


def test_bad_template_fails_at_queue_time(db):
    with pytest.raises(KeyError):
        mailer.queue(db, "sam@example.com", "verify", name="Sam")  # no url


@pytest.mark.parametrize("template", sorted(TEMPLATES))
def test_every_template_renders_html_and_text(template):
    email = render(template, CONTEXT)
    assert email.subject and email.text and email.html.startswith("<div")
    assert "<script" not in email.html


def test_html_is_escaped():
    email = render("invite", {**CONTEXT, "client": "<b>Acme</b>"})
    assert "<b>Acme</b>" not in email.html and "&lt;b&gt;" in email.html
