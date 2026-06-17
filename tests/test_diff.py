import unittest

from property_watcher.diff import compare
from property_watcher.models import PropertyTarget, Snapshot


TARGET = PropertyTarget(name="テスト物件", url="https://example.com/property")


def snapshot(*, ok=True, status_code=200, title="物件A", price=5000,
             status_text="掲載中の可能性", contact_available=True, error=None):
    return Snapshot(
        url=TARGET.url,
        fetched_at="2026-06-18T00:00:00+00:00",
        ok=ok,
        status_code=status_code,
        final_url=TARGET.url if status_code else None,
        title=title,
        price=price,
        status_text=status_text,
        contact_available=contact_available,
        content_hash="hash",
        error=error,
    )


def row(value: Snapshot) -> dict:
    return {
        "ok": int(value.ok),
        "status_code": value.status_code,
        "final_url": value.final_url,
        "price": value.price,
        "title": value.title,
        "status_text": value.status_text,
        "contact_available": None if value.contact_available is None else int(value.contact_available),
        "error": value.error,
    }


class DiffTest(unittest.TestCase):
    def test_failure_produces_only_one_event(self):
        previous = row(snapshot())
        current = snapshot(
            ok=False, status_code=None, title="", price=None,
            status_text="取得失敗", contact_available=None, error="temporary parser error",
        )

        events = compare(TARGET, previous, current)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "availability_changed")

    def test_recovery_produces_only_one_event(self):
        previous = row(snapshot(
            ok=False, status_code=None, title="", price=None,
            status_text="取得失敗", contact_available=None, error="temporary parser error",
        ))

        events = compare(TARGET, previous, snapshot())

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "availability_restored")

    def test_repeated_failure_does_not_notify_again(self):
        failed = snapshot(
            ok=False, status_code=None, title="", price=None,
            status_text="取得失敗", contact_available=None, error="temporary parser error",
        )
        self.assertEqual(compare(TARGET, row(failed), failed), [])


if __name__ == "__main__":
    unittest.main()
