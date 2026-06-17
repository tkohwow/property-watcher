import argparse
import csv
import time
from pathlib import Path

from .db import connect, upsert_target, get_latest_snapshot, upsert_latest_snapshot, insert_events
from .diff import compare
from .fetcher import fetch_snapshot
from .models import PropertyTarget
from .notifier import notify_gmail, format_event


def load_targets(csv_path: str) -> list[PropertyTarget]:
    targets: list[PropertyTarget] = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            url = (row.get("url") or "").strip()
            if not url or url.startswith("#"):
                continue
            targets.append(
                PropertyTarget(
                    name=(row.get("name") or url).strip(),
                    url=url,
                    memo=(row.get("memo") or "").strip(),
                )
            )
    return targets


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", default="properties.csv", help="監視対象CSV")
    parser.add_argument("--db", default="property_watcher.db", help="SQLite DB path")
    parser.add_argument("--sleep", type=float, default=3.0, help="URLごとの待機秒数")
    args = parser.parse_args()

    if not Path(args.csv).exists():
        raise SystemExit(f"CSV not found: {args.csv}")

    targets = load_targets(args.csv)
    if not targets:
        print("No targets.")
        return

    conn = connect(args.db)

    for index, target in enumerate(targets):
        print(f"[{index + 1}/{len(targets)}] Fetching {target.name}: {target.url}")
        upsert_target(conn, target.url, target.name, target.memo)
        previous = get_latest_snapshot(conn, target.url)
        current = fetch_snapshot(target.url)
        events = compare(target, previous, current)

        upsert_latest_snapshot(conn, current)
        if events:
            insert_events(conn, events)
            for event in events:
                # 初回保存はうるさいのでGmail通知しない。ログだけ残す。
                if event["event_type"] == "first_seen":
                    print(event["message"])
                    continue
                notify_gmail(
                    subject=f"[物件ウォッチ] {event['message']}",
                    body=format_event(target, current, event),
                )
                print(event["message"])

        conn.commit()

        if index < len(targets) - 1:
            time.sleep(args.sleep)


if __name__ == "__main__":
    main()
