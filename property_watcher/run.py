import argparse
import csv
import time
from pathlib import Path

from .db import (
    connect, get_latest_snapshot, has_image_archive_attempt, insert_events,
    insert_property_images, mark_image_archive_attempt, upsert_latest_snapshot, upsert_target,
)
from .diff import compare
from .fetcher import fetch_snapshot_with_html
from .image_archive import archive_property_images
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
    parser.add_argument(
        "--images",
        choices=("initial", "refresh", "off"),
        default="initial",
        help="室内写真: initial=未実施物件のみ, refresh=再取得, off=取得しない",
    )
    parser.add_argument("--image-dir", default="property_images", help="画像の保存先")
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
        should_archive = args.images == "refresh" or (
            args.images == "initial" and not has_image_archive_attempt(conn, target.url)
        )
        current, html = fetch_snapshot_with_html(target.url)
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

        if should_archive and current.ok and html:
            print(f"Archiving indoor images for {target.name}...")
            result = archive_property_images(html, target.url, target.name, root_dir=args.image_dir)
            insert_property_images(conn, target.url, result.images)
            error = "\n".join(result.errors) if result.errors else None
            mark_image_archive_attempt(conn, target.url, current.fetched_at, len(result.images), error)
            print(f"Archived {len(result.images)} indoor image(s).")
            for archive_error in result.errors:
                print(f"Image skipped: {archive_error}")

        conn.commit()

        if index < len(targets) - 1:
            time.sleep(args.sleep)


if __name__ == "__main__":
    main()
