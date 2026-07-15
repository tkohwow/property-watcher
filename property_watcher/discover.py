import argparse
import csv
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from .db import connect
from .notifier import notify_gmail
from .run import load_targets


USER_AGENT = "Mozilla/5.0 (compatible; PersonalPropertyWatcher/1.0; +https://github.com/)"
FETCH_ATTEMPTS = 3

SEARCHES = [
    (
        "中野坂上",
        "https://suumo.jp/jj/bukken/ichiran/JJ012FC001/?ar=030&bs=011&fw=%E4%B8%AD%E9%87%8E%E5%9D%82%E4%B8%8A&ta=13&sc=13114",
    ),
    (
        "中野新橋",
        "https://suumo.jp/jj/bukken/ichiran/JJ012FC001/?ar=030&bs=011&fw=%E4%B8%AD%E9%87%8E%E6%96%B0%E6%A9%8B&ta=13&sc=13114",
    ),
    (
        "西新宿五丁目",
        "https://suumo.jp/jj/bukken/ichiran/JJ012FC001/?ar=030&bs=011&fw=%E8%A5%BF%E6%96%B0%E5%AE%BF%E4%BA%94%E4%B8%81%E7%9B%AE&ta=13&sc=13104",
    ),
    (
        "東中野",
        "https://suumo.jp/jj/bukken/ichiran/JJ012FC001/?ar=030&bs=011&fw=%E6%9D%B1%E4%B8%AD%E9%87%8E&ta=13&sc=13114",
    ),
]

AMFLAT_COMP_STATIONS = ("中野坂上", "中野新橋", "西新宿五丁目", "東中野")
AMFLAT_COMP_AREAS = (
    "東京都中野区中央",
    "東京都中野区本町",
    "東京都中野区弥生町",
    "東京都中野区東中野",
    "東京都新宿区北新宿",
    "東京都新宿区西新宿",
)
FULLWIDTH_LAYOUT_TRANSLATION = str.maketrans({"Ｓ": "S", "Ｌ": "L", "Ｄ": "D", "Ｋ": "K"})

SCHEMA = """
CREATE TABLE IF NOT EXISTS candidate_listings (
    url TEXT PRIMARY KEY,
    nc_id TEXT,
    search_name TEXT NOT NULL,
    name TEXT NOT NULL,
    price INTEGER,
    price_text TEXT,
    layout TEXT,
    area_text TEXT,
    station TEXT,
    address TEXT,
    age_text TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    notified_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_candidate_listings_notified
ON candidate_listings(notified_at, first_seen_at);
"""


@dataclass(frozen=True)
class Candidate:
    search_name: str
    url: str
    nc_id: str
    name: str
    price: int | None
    price_text: str
    layout: str
    area_text: str
    station: str
    address: str
    age_text: str


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_nc_id(url: str) -> str | None:
    match = re.search(r"(?:nc_|[?&]nc=)(\d+)", url)
    return match.group(1) if match else None


def normalize_name(value: str) -> str:
    return re.sub(r"[\s　（）()0-9階ＦF]+", "", value)


def existing_ids(csv_path: str) -> tuple[set[str], set[str], set[str]]:
    targets = load_targets(csv_path)
    urls = {target.url for target in targets}
    ids = {nc_id for target in targets if (nc_id := normalize_nc_id(target.url))}
    names = {normalize_name(target.name) for target in targets}
    return urls, ids, names


def text_of(element) -> str:
    if element is None:
        return ""
    return " ".join(element.get_text(" ", strip=True).split())


def field(block, label: str) -> str:
    for dt in block.select("dt"):
        if text_of(dt) == label:
            dd = dt.find_next_sibling("dd")
            return text_of(dd)
    return ""


def parse_price(price_text: str) -> int | None:
    text = price_text.replace(",", "")
    oku = re.search(r"(\d+)億", text)
    man = re.search(r"(\d+)万円", text)
    if oku:
        value = int(oku.group(1)) * 10000
        if man:
            value += int(man.group(1))
        return value
    if man:
        return int(man.group(1))
    return None


def parse_area(area_text: str) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)m", area_text)
    return float(match.group(1)) if match else None


def parse_built_year(age_text: str) -> int | None:
    match = re.search(r"(\d{4})年", age_text)
    return int(match.group(1)) if match else None


def parse_walk_minutes(station_text: str) -> int | None:
    match = re.search(r"(?:徒歩|歩)(\d+)分", station_text)
    return int(match.group(1)) if match else None


def fetch_candidates(search_name: str, search_url: str) -> list[Candidate]:
    for attempt in range(1, FETCH_ATTEMPTS + 1):
        try:
            response = requests.get(
                search_url,
                timeout=30,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
                },
            )
            response.raise_for_status()
            break
        except requests.RequestException as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            retryable = status_code is None or status_code == 429 or status_code >= 500
            if not retryable or attempt == FETCH_ATTEMPTS:
                raise
            delay = 2 ** (attempt - 1)
            print(
                f"  Request failed for {search_name} "
                f"({status_code or exc.__class__.__name__}); retrying in {delay}s..."
            )
            time.sleep(delay)

    soup = BeautifulSoup(response.text, "lxml")
    candidates: list[Candidate] = []
    seen_ids: set[str] = set()

    for title in soup.select("h2.property_unit-title a[href]"):
        href = title.get("href") or ""
        url = urljoin("https://suumo.jp", href)
        nc_id = normalize_nc_id(url)
        if not nc_id or nc_id in seen_ids:
            continue
        seen_ids.add(nc_id)

        block = title.find_parent(class_="property_unit-content") or title.find_parent(class_="property_unit")
        name = field(block, "物件名") or text_of(title)
        price_text = field(block, "販売価格")
        layout = field(block, "間取り")
        price = parse_price(price_text)
        candidates.append(
            Candidate(
                search_name=search_name,
                url=url,
                nc_id=nc_id,
                name=name,
                price=price,
                price_text=price_text,
                layout=layout,
                area_text=field(block, "専有面積"),
                station=field(block, "沿線・駅"),
                address=field(block, "所在地"),
                age_text=field(block, "築年月"),
            )
        )

    return candidates


def is_amflat_comp_candidate(
    candidate: Candidate,
    *,
    min_price: int,
    max_price: int,
    min_area: float,
    max_area: float,
    min_built_year: int,
    max_walk_minutes: int,
) -> bool:
    if candidate.price is None or not (min_price <= candidate.price <= max_price):
        return False

    area = parse_area(candidate.area_text)
    if area is None or not (min_area <= area <= max_area):
        return False

    built_year = parse_built_year(candidate.age_text)
    if built_year is None or built_year < min_built_year:
        return False

    layout = candidate.layout.translate(FULLWIDTH_LAYOUT_TRANSLATION).upper()
    if not (
        "2LDK" in layout
        or "2SLDK" in layout
        or "2LDK+S" in layout
        or "1LDK+S" in layout
        or "1SLDK" in layout
        or "納戸" in layout
        or (("3LDK" in layout or "3SLDK" in layout) and area <= 75)
    ):
        return False

    if not any(area_name in candidate.address for area_name in AMFLAT_COMP_AREAS):
        return False

    if not any(station in candidate.station for station in AMFLAT_COMP_STATIONS):
        return False

    walk_minutes = parse_walk_minutes(candidate.station)
    return walk_minutes is not None and walk_minutes <= max_walk_minutes


def is_existing_name(candidate: Candidate, target_names: set[str]) -> bool:
    candidate_name = normalize_name(candidate.name)
    return any(
        candidate_name and (candidate_name in target_name or target_name in candidate_name)
        for target_name in target_names
    )


def sort_candidates(candidates: list[Candidate]) -> list[Candidate]:
    return sorted(
        candidates,
        key=lambda candidate: (
            candidate.price if candidate.price is not None else 10**9,
            -(parse_area(candidate.area_text) or 0),
            candidate.name,
        ),
    )


def upsert_and_collect_new(conn, candidates: list[Candidate], seen_at: str) -> list[Candidate]:
    new_candidates: list[Candidate] = []
    for candidate in candidates:
        previous = conn.execute(
            "SELECT 1 FROM candidate_listings WHERE url = ?",
            (candidate.url,),
        ).fetchone()
        conn.execute(
            """
            INSERT INTO candidate_listings(
                url, nc_id, search_name, name, price, price_text, layout,
                area_text, station, address, age_text, first_seen_at, last_seen_at, notified_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
            ON CONFLICT(url) DO UPDATE SET
                nc_id = excluded.nc_id,
                search_name = excluded.search_name,
                name = excluded.name,
                price = excluded.price,
                price_text = excluded.price_text,
                layout = excluded.layout,
                area_text = excluded.area_text,
                station = excluded.station,
                address = excluded.address,
                age_text = excluded.age_text,
                last_seen_at = excluded.last_seen_at
            """,
            (
                candidate.url,
                candidate.nc_id,
                candidate.search_name,
                candidate.name,
                candidate.price,
                candidate.price_text,
                candidate.layout,
                candidate.area_text,
                candidate.station,
                candidate.address,
                candidate.age_text,
                seen_at,
                seen_at,
            ),
        )
        if previous is None:
            new_candidates.append(candidate)
    return new_candidates


def mark_notified(conn, candidates: list[Candidate], notified_at: str) -> None:
    conn.executemany(
        "UPDATE candidate_listings SET notified_at = ? WHERE url = ?",
        [(notified_at, candidate.url) for candidate in candidates],
    )


def dedupe_similar(candidates: list[Candidate]) -> list[Candidate]:
    deduped: dict[tuple[str, int | None, int | None], Candidate] = {}
    for candidate in candidates:
        area = parse_area(candidate.area_text)
        key = (
            normalize_name(candidate.name),
            candidate.price,
            round(area * 10) if area is not None else None,
        )
        current = deduped.get(key)
        if current is None or len(candidate.url) < len(current.url):
            deduped[key] = candidate
    return list(deduped.values())


def format_candidates(
    candidates: list[Candidate],
    omitted_count: int = 0,
    *,
    auto_add: bool = False,
    added_count: int = 0,
) -> str:
    lines = ["New property candidates were found.", ""]
    for index, candidate in enumerate(candidates, 1):
        lines.extend(
            [
                f"{index}. {candidate.name}",
                f"   Search: {candidate.search_name}",
                f"   Price: {candidate.price_text or 'unknown'}",
                f"   Layout: {candidate.layout or 'unknown'}",
                f"   Area: {candidate.area_text or 'unknown'}",
                f"   Station: {candidate.station or 'unknown'}",
                f"   Address: {candidate.address or 'unknown'}",
                f"   Built: {candidate.age_text or 'unknown'}",
                f"   URL: {candidate.url}",
                "",
            ]
        )
    if auto_add:
        lines.append(f"Auto-add is enabled; {added_count} matching candidate(s) were appended to properties.csv.")
    else:
        lines.append("These candidates were recorded for review but were not added to properties.csv.")
    if omitted_count:
        lines.append(f"{omitted_count} more candidate(s) were recorded in the database but omitted from this email.")
    return "\n".join(lines)


def candidate_name(candidate: Candidate) -> str:
    layout = candidate.layout or "layout unknown"
    return f"{candidate.name}（{layout}）"


def candidate_memo(candidate: Candidate) -> str:
    parts = [
        candidate.price_text,
        candidate.area_text,
        candidate.station,
        candidate.age_text,
        "アムフラット702売却比較候補",
    ]
    return "・".join(part for part in parts if part)


def append_to_csv(csv_path: str, candidates: list[Candidate]) -> int:
    if not candidates:
        return 0

    path = Path(csv_path)
    targets = load_targets(csv_path)
    existing_urls = {target.url for target in targets}
    existing_nc_ids = {nc_id for target in targets if (nc_id := normalize_nc_id(target.url))}
    rows = [
        {
            "name": candidate_name(candidate),
            "url": candidate.url,
            "memo": candidate_memo(candidate),
        }
        for candidate in candidates
        if candidate.url not in existing_urls and candidate.nc_id not in existing_nc_ids
    ]
    if not rows:
        return 0

    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["name", "url", "memo"])
        for row in rows:
            writer.writerow(row)
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Discover promising new property candidates")
    parser.add_argument("--csv", default="properties.csv", help="current target CSV")
    parser.add_argument("--db", default="property_watcher.db", help="SQLite DB path")
    parser.add_argument("--min-price", type=int, default=7000, help="minimum price in man-yen")
    parser.add_argument("--max-price", type=int, default=11500, help="maximum price in man-yen")
    parser.add_argument("--min-area", type=float, default=45.0, help="minimum exclusive area in square meters")
    parser.add_argument("--max-area", type=float, default=75.0, help="maximum exclusive area in square meters")
    parser.add_argument("--min-built-year", type=int, default=1988, help="minimum built year")
    parser.add_argument("--max-walk-minutes", type=int, default=10, help="maximum station walk minutes")
    parser.add_argument("--max-candidates", type=int, default=10, help="maximum candidates included in one email/log body")
    parser.add_argument("--auto-add", action="store_true", help="append first-seen matching candidates to properties.csv")
    parser.add_argument("--notify", action="store_true", help="send Gmail notification for first-seen candidates")
    args = parser.parse_args()

    target_urls, target_ids, target_names = existing_ids(args.csv)
    conn = connect(args.db)
    conn.executescript(SCHEMA)
    seen_at = now_iso()

    all_candidates: list[Candidate] = []
    skipped_searches: list[str] = []
    for search_name, search_url in SEARCHES:
        print(f"Searching {search_name}: {search_url}")
        try:
            found = fetch_candidates(search_name, search_url)
        except requests.RequestException as exc:
            skipped_searches.append(search_name)
            print(f"::warning::Skipping {search_name} after repeated request failure: {exc}")
            continue
        filtered = [
            candidate
            for candidate in found
            if candidate.url not in target_urls
            and candidate.nc_id not in target_ids
            and not is_existing_name(candidate, target_names)
            and is_amflat_comp_candidate(
                candidate,
                min_price=args.min_price,
                max_price=args.max_price,
                min_area=args.min_area,
                max_area=args.max_area,
                min_built_year=args.min_built_year,
                max_walk_minutes=args.max_walk_minutes,
            )
        ]
        print(f"  found={len(found)} promising_new={len(filtered)}")
        all_candidates.extend(filtered)

    if skipped_searches:
        print(f"Skipped {len(skipped_searches)} search(es): {', '.join(skipped_searches)}")

    deduped = sort_candidates(dedupe_similar(list({candidate.url: candidate for candidate in all_candidates}.values())))
    added_count = append_to_csv(args.csv, deduped) if args.auto_add else 0
    if args.auto_add:
        print(f"Added {added_count} candidate(s) to {args.csv}.")
    new_candidates = upsert_and_collect_new(conn, deduped, seen_at)

    if new_candidates:
        visible_candidates = new_candidates[: args.max_candidates]
        omitted_count = max(0, len(new_candidates) - len(visible_candidates))
        body = format_candidates(
            visible_candidates,
            omitted_count,
            auto_add=args.auto_add,
            added_count=added_count,
        )
        print(body)
        if args.notify:
            notify_gmail(
                subject=f"[Property Watcher] {len(new_candidates)} new property candidate(s)",
                body=body,
            )
            mark_notified(conn, new_candidates, now_iso())
    else:
        if args.auto_add and added_count:
            print("Matching candidates were already known in the database, but were appended to the CSV now.")
        else:
            print("No new property candidates.")

    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()
