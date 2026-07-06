import csv
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from property_watcher import discover


def amflat_like_candidate(**overrides):
    values = {
        "search_name": "中野坂上",
        "url": "https://suumo.jp/ms/chuko/tokyo/sc_nakano/nc_21000001/",
        "nc_id": "21000001",
        "name": "テスト中野坂上",
        "price": 8998,
        "price_text": "8998万円",
        "layout": "2LDK",
        "area_text": "55.61m2（壁芯）",
        "station": "東京メトロ丸ノ内線「中野坂上」徒歩3分",
        "address": "東京都中野区中央２",
        "age_text": "1998年10月",
    }
    values.update(overrides)
    return discover.Candidate(**values)


class DiscoverTest(unittest.TestCase):
    def test_identifies_amflat_sale_comparable_candidate(self):
        self.assertTrue(
            discover.is_amflat_comp_candidate(
                amflat_like_candidate(),
                min_price=7000,
                max_price=11500,
                min_area=45.0,
                max_area=75.0,
                min_built_year=1988,
                max_walk_minutes=10,
            )
        )

    def test_rejects_candidates_outside_comparable_location(self):
        self.assertFalse(
            discover.is_amflat_comp_candidate(
                amflat_like_candidate(
                    search_name="初台",
                    station="京王新線「初台」徒歩6分",
                    address="東京都渋谷区本町１",
                ),
                min_price=7000,
                max_price=11500,
                min_area=45.0,
                max_area=75.0,
                min_built_year=1988,
                max_walk_minutes=10,
            )
        )

    def test_auto_add_appends_candidate_even_when_database_already_knows_it(self):
        candidate = amflat_like_candidate()

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            csv_path = temp_path / "properties.csv"
            db_path = temp_path / "property_watcher.db"
            csv_path.write_text("name,url,memo\n既存,https://example.com/existing,\n", encoding="utf-8")

            conn = discover.connect(str(db_path))
            conn.executescript(discover.SCHEMA)
            discover.upsert_and_collect_new(conn, [candidate], "2026-07-07T00:00:00+09:00")
            conn.commit()
            conn.close()

            with (
                patch.object(discover, "SEARCHES", [("中野坂上", "https://example.com/search")]),
                patch.object(discover, "fetch_candidates", return_value=[candidate]),
                patch.object(
                    sys,
                    "argv",
                    [
                        "discover",
                        "--csv",
                        str(csv_path),
                        "--db",
                        str(db_path),
                        "--auto-add",
                    ],
                ),
            ):
                discover.main()

            with csv_path.open(encoding="utf-8", newline="") as f:
                rows = list(csv.DictReader(f))

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]["url"], candidate.url)
        self.assertIn("アムフラット702売却比較候補", rows[1]["memo"])


if __name__ == "__main__":
    unittest.main()
