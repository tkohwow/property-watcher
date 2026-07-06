import argparse
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from .db import connect
from .notifier import notify_gmail
from .run import load_targets


USER_AGENT = "Mozilla/5.0 (compatible; PersonalPropertyWatcher/1.0; +https://github.com/)"

SEARCHES = [
    (
        "中野坂上",
        "https://suumo.jp/jj/bukken/ichiran/JJ012FC001/?ar=030&bs=011&fw=%E4%B8%AD%E9%87%8E%E5%9D%82%E4%B8%8A&ta=13&sc=13114",
    ),
    (
        "西新宿",
        "https://suumo.jp/jj/bukken/ichiran/JJ012FC001/?ar=030&bs=011&fw=%E8%A5%BF%E6%96%B0%E5%AE%BF&ta=13&sc=13104",
    ),
    (
        "東中野",
        "https://suumo.jp/jj/bukken/ichiran/JJ012FC001/?ar=030&bs=011&fw=%E6%9D%B1%E4%B8%AD%E9%87%8E&ta=13&sc=13114",
    ),
    (
        "初台",
        "https://suumo.jp/jj/bukken/ichiran/JJ012FC001/?ar=030&bs=011&fw=%E5%88%9D%E5%8F%B0&ta=13&sc=13113",
    ),
]

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


def fetch_candidates(search_name: str, search_url: str) -> list[Candidate]:
    response = requests.get(
        search_url,
        timeout=30,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
        },
    )
    response.raise_for_status()
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


def is_promising(candidate: Candidate, min_price: int, max_price: int, min_area: float) -> bool:
    if candidate.price is None:
        return False
    if not (min_price <= candidate.price <= max_price):
        return False
    area = parse_area(candidate.area_text)
    if area is None or area < min_area:
        return False
    layout = candidate.layout.replace("Ｓ", "S")
    return (
        "2LDK" in layout
        or "3LDK" in layout
        or "4LDK" in layout
        or "LDK+S" in layout
        or "納戸" in layout
    )


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


def format_candidates(candidates: list[Candidate], omitted_count: int = 0) -> str:
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
    lines.append("These were not added to properties.csv automatically.")
    if omitted_count:
        lines.append(f"{omitted_count} more candidate(s) were recorded in the database but omitted from this email.")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Discover promising new property candidates")
    parser.add_argument("--csv", default="properties.csv", help="current target CSV")
    parser.add_argument("--db", default="property_watcher.db", help="SQLite DB path")
    parser.add_argument("--min-price", type=int, default=6500, help="minimum price in man-yen")
    parser.add_argument("--max-price", type=int, default=11000, help="maximum price in man-yen")
    parser.add_argument("--min-area", type=float, default=48.0, help="minimum exclusive area in square meters")
    parser.add_argument("--max-candidates", type=int, default=10, help="maximum candidates included in one email/log body")
    parser.add_argument("--notify", action="store_true", help="send Gmail notification for first-seen candidates")
    args = parser.parse_args()

    target_urls, target_ids, target_names = existing_ids(args.csv)
    conn = connect(args.db)
    conn.executescript(SCHEMA)
    seen_at = now_iso()

    all_candidates: list[Candidate] = []
    for search_name, search_url in SEARCHES:
        print(f"Searching {search_name}: {search_url}")
        found = fetch_candidates(search_name, search_url)
        filtered = [
            candidate
            for candidate in found
            if candidate.url not in target_urls
            and candidate.nc_id not in target_ids
            and not is_existing_name(candidate, target_names)
            and is_promising(candidate, args.min_price, args.max_price, args.min_area)
        ]
        print(f"  found={len(found)} promising_new={len(filtered)}")
        all_candidates.extend(filtered)

    deduped = sort_candidates(dedupe_similar(list({candidate.url: candidate for candidate in all_candidates}.values())))
    new_candidates = upsert_and_collect_new(conn, deduped, seen_at)

    if new_candidates:
        visible_candidates = new_candidates[: args.max_candidates]
        omitted_count = max(0, len(new_candidates) - len(visible_candidates))
        body = format_candidates(visible_candidates, omitted_count)
        print(body)
        if args.notify:
            notify_gmail(
                subject=f"[Property Watcher] {len(new_candidates)} new property candidate(s)",
                body=body,
            )
            mark_notified(conn, new_candidates, now_iso())
    else:
        print("No new property candidates.")

    conn.commit()


if __name__ == "__main__":
    main()
