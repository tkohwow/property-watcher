import os
import smtplib
from email.message import EmailMessage

from .models import PropertyTarget, Snapshot


def format_event(target: PropertyTarget, snapshot: Snapshot, event: dict) -> str:
    price = f"{snapshot.price:,}万円" if snapshot.price else "不明"
    return (
        f"{event['message']}\n\n"
        f"重要度: {event['severity']}\n"
        f"種別: {event['event_type']}\n"
        f"物件名: {target.name}\n"
        f"価格: {price}\n"
        f"状態: {snapshot.status_text}\n"
        f"変更前: {event.get('old_value')}\n"
        f"変更後: {event.get('new_value')}\n"
        f"URL: {target.url}\n"
    )


def notify_gmail(
    subject: str,
    body: str,
    gmail_user: str | None = None,
    gmail_app_password: str | None = None,
    to_address: str | None = None,
) -> None:
    """Send a notification email via Gmail SMTP.

    Required environment variables:
      - GMAIL_USER: Gmail address used as sender
      - GMAIL_APP_PASSWORD: Google App Password, not the normal login password
      - NOTIFY_TO: recipient address. Defaults to GMAIL_USER when omitted.
    """
    gmail_user = gmail_user or os.environ.get("GMAIL_USER")
    gmail_app_password = gmail_app_password or os.environ.get("GMAIL_APP_PASSWORD")
    to_address = to_address or os.environ.get("NOTIFY_TO") or gmail_user

    if not gmail_user or not gmail_app_password or not to_address:
        print("GMAIL_USER / GMAIL_APP_PASSWORD / NOTIFY_TO is not fully set. Notification skipped.")
        print(f"Subject: {subject}")
        print(body)
        return

    msg = EmailMessage()
    msg["From"] = gmail_user
    msg["To"] = to_address
    msg["Subject"] = subject
    msg.set_content(body)

    with smtplib.SMTP("smtp.gmail.com", 587, timeout=20) as smtp:
        smtp.starttls()
        smtp.login(gmail_user, gmail_app_password)
        smtp.send_message(msg)
