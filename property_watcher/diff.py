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

    previous_ok = bool(previous["ok"])

    # 取得失敗時は title/price/status/contact が空になるが、それらは物件の変更ではない。
    # 取得可否だけを1イベントにまとめ、空値との比較による大量通知を防ぐ。
    if previous_ok and not current.ok:
        reason = current.error or current.status_text
        return [
            _event(
                target,
                current,
                "high" if current.status_code in (404, 410) else "medium",
                "availability_changed",
                "ページを取得できなくなりました",
                previous["status_code"],
                reason,
            )
        ]

    # 復旧時も、失敗スナップショットの空値とは比較しない。復旧通知1件だけにする。
    if not previous_ok and current.ok:
        return [
            _event(
                target,
                current,
                "info",
                "availability_restored",
                "ページを再び取得できました",
                previous["error"] or previous["status_text"],
                current.status_code,
            )
        ]

    # 連続する取得失敗は同じ異常を繰り返し通知しない。
    if not previous_ok and not current.ok:
        return []

    events: list[dict] = []

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

    # 本文全体のhashは、広告・おすすめ枠・トラッキングパラメータ・掲載件数などの
    # 動的要素で毎回変わることがあるため、メール通知の対象にしない。
    # latest_snapshots には最新状態を上書き保存するので、後から raw_text の確認は可能。
    # 価格・タイトル・掲載状態・問い合わせ導線・HTTP状態などの明確な変化だけ通知する。

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
