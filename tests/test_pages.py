import tempfile
import unittest
from pathlib import Path

from property_watcher import pages
from property_watcher.db import connect, insert_events, upsert_latest_snapshot, upsert_target
from property_watcher.models import Snapshot
from property_watcher.web import Dashboard


def snapshot(url: str, price: int) -> Snapshot:
    return Snapshot(
        url=url,
        fetched_at="2026-07-15T03:30:00+00:00",
        ok=True,
        status_code=200,
        final_url=url,
        title="物件情報",
        price=price,
        status_text="掲載中の可能性",
        contact_available=True,
        content_hash=f"hash-{price}",
    )


class PagesTest(unittest.TestCase):
    def test_index_sorts_by_name_and_shows_price_history_in_cards(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            db_path = temp_path / "property_watcher.db"
            image_dir = temp_path / "property_images"
            alpha_url = "https://example.com/alpha"
            beta_url = "https://example.com/beta"

            conn = connect(str(db_path))
            upsert_target(conn, beta_url, "ベータ物件")
            upsert_target(conn, alpha_url, "アルファ物件")
            upsert_latest_snapshot(conn, snapshot(beta_url, 10480))
            upsert_latest_snapshot(conn, snapshot(alpha_url, 9500))
            insert_events(
                conn,
                [
                    {
                        "url": beta_url,
                        "occurred_at": "2026-07-07T03:26:00+00:00",
                        "severity": "high",
                        "event_type": "price_changed",
                        "message": "価格が変わりました",
                        "old_value": "8980",
                        "new_value": "10480",
                    }
                ],
            )
            conn.commit()
            conn.close()

            html = pages.render_index(Dashboard(str(db_path), str(image_dir)))

        self.assertLess(html.index("アルファ物件"), html.index("ベータ物件"))
        self.assertIn("価格推移", html)
        self.assertIn("8,980万円", html)
        self.assertIn("10,480万円", html)
        self.assertIn("2026/07/07", html)


if __name__ == "__main__":
    unittest.main()
