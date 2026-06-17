from datetime import datetime, timezone
from sqlite3 import Row

from .models import Snapshot, PropertyTarget


def _stringify(value) -> str | None:
    if value is None:
        return None
    return str(value)


def compare(target: PropertyTarget, previous: Row | None, current: Snapshot) -> list[dict]:
    if previous is None:
        return [
            _event(target, current, "info", "first_seen", "初回スナップショットを保存しました", None, current.status_text)
        ]

    events: list[dict] = []

    if int(previous["ok"]) != int(current.ok):
        events.append(_event(target, current, "high", "availability_changed", "ページ取得状態が変わりました", previous["ok"], int(current.ok)))

    if previous["status_code"] != current.status_code:
        severity = "high" if current.status_code in (404, 410) else "medium"
        events.append(_event(target, current, severity, "http_status_changed", "HTTPステータスが変わりました", previous["status_code"], current.status_code))

    if previous["final_url"] and current.final_url and previous["final_url"] != current.final_url:
        events.append(_event(target, current, "medium", "final_url_changed", "リダイレクト先URLが変わりました", previous["final_url"], current.final_url))

    if previous["price"] != current.price:
        events.append(_event(target, current, "high", "price_changed", "価格が変わった可能性があります", previous["price"], current.price))

    if previous["title"] != current.title:
        events.append(_event(target, current, "medium", "title_changed", "ページタイトルが変わりました", previous["title"], current.title))

    if previous["status_text"] != current.status_text:
        severity = "high" if any(word in current.status_text for word in ["終了", "成約", "HTTP 404"]) else "medium"
        events.append(_event(target, current, severity, "status_text_changed", "掲載状態らしき文言が変わりました", previous["status_text"], current.status_text))

    old_contact = previous["contact_available"]
    new_contact = None if current.contact_available is None else int(current.contact_available)
    if old_contact != new_contact:
        events.append(_event(target, current, "medium", "contact_changed", "問い合わせ導線の有無が変わりました", old_contact, new_contact))

    if previous["content_hash"] != current.content_hash and not events:
        events.append(_event(target, current, "low", "content_changed", "本文に何らかの変化がありました", previous["content_hash"][:12], current.content_hash[:12]))

    return events


def _event(target: PropertyTarget, snapshot: Snapshot, severity: str, event_type: str, message: str, old_value, new_value) -> dict:
    return {
        "url": target.url,
        "occurred_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "severity": severity,
        "event_type": event_type,
        "message": f"{target.name}: {message}",
        "old_value": _stringify(old_value),
        "new_value": _stringify(new_value),
    }
