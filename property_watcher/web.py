import argparse
import mimetypes
import socket
import sqlite3
from html import escape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse


def open_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def yen(value) -> str:
    if value is None:
        return "unknown"
    return f"{int(value):,} man yen"


def yes_no(value) -> str:
    if value is None:
        return "unknown"
    return "yes" if int(value) else "no"


def severity_class(severity: str | None) -> str:
    return {
        "high": "sev-high",
        "medium": "sev-medium",
        "low": "sev-low",
        "info": "sev-info",
    }.get(severity or "", "sev-info")


def short_text(value: str | None, limit: int = 160) -> str:
    if not value:
        return ""
    value = " ".join(value.split())
    return value if len(value) <= limit else value[:limit] + "..."


def lan_addresses(port: int) -> list[str]:
    addresses: set[str] = set()
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            address = info[4][0]
            if not address.startswith("127."):
                addresses.add(address)
    except OSError:
        pass

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            address = sock.getsockname()[0]
            if not address.startswith("127."):
                addresses.add(address)
    except OSError:
        pass

    return [f"http://{address}:{port}/" for address in sorted(addresses)]


class Dashboard:
    def __init__(self, db_path: str, image_dir: str):
        self.db_path = db_path
        self.image_dir = Path(image_dir).resolve()

    def targets(self) -> list[sqlite3.Row]:
        with open_db(self.db_path) as conn:
            return conn.execute(
                """
                SELECT
                    t.name, t.memo, t.url,
                    s.fetched_at, s.ok, s.status_code, s.final_url, s.title,
                    s.price, s.status_text, s.contact_available, s.error,
                    COALESCE(img.image_count, 0) AS image_count,
                    last_event.occurred_at AS last_event_at,
                    last_event.event_type AS last_event_type,
                    last_event.severity AS last_event_severity,
                    last_event.message AS last_event_message
                FROM targets t
                LEFT JOIN latest_snapshots s ON s.url = t.url
                LEFT JOIN (
                    SELECT url, COUNT(*) AS image_count
                    FROM property_images
                    GROUP BY url
                ) img ON img.url = t.url
                LEFT JOIN (
                    SELECT e.*
                    FROM events e
                    JOIN (
                        SELECT url, MAX(id) AS max_id
                        FROM events
                        GROUP BY url
                    ) latest ON latest.max_id = e.id
                ) last_event ON last_event.url = t.url
                ORDER BY
                    CASE WHEN s.ok = 1 THEN 0 ELSE 1 END,
                    s.price IS NULL,
                    s.price,
                    t.name
                """
            ).fetchall()

    def target(self, url: str) -> sqlite3.Row | None:
        with open_db(self.db_path) as conn:
            return conn.execute(
                """
                SELECT t.name, t.memo, t.url, t.updated_at,
                       s.fetched_at, s.ok, s.status_code, s.final_url, s.title,
                       s.price, s.status_text, s.contact_available,
                       s.content_hash, s.raw_text, s.error,
                       a.attempted_at AS image_attempted_at,
                       a.saved_count AS image_saved_count,
                       a.error AS image_error
                FROM targets t
                LEFT JOIN latest_snapshots s ON s.url = t.url
                LEFT JOIN image_archive_status a ON a.url = t.url
                WHERE t.url = ?
                LIMIT 1
                """,
                (url,),
            ).fetchone()

    def events(self, url: str | None = None, limit: int = 80) -> list[sqlite3.Row]:
        with open_db(self.db_path) as conn:
            if url:
                return conn.execute(
                    """
                    SELECT e.*, t.name
                    FROM events e
                    LEFT JOIN targets t ON t.url = e.url
                    WHERE e.url = ?
                    ORDER BY e.id DESC
                    LIMIT ?
                    """,
                    (url, limit),
                ).fetchall()
            return conn.execute(
                """
                SELECT e.*, t.name
                FROM events e
                LEFT JOIN targets t ON t.url = e.url
                ORDER BY e.id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

    def images(self, url: str) -> list[sqlite3.Row]:
        with open_db(self.db_path) as conn:
            return conn.execute(
                """
                SELECT *
                FROM property_images
                WHERE url = ?
                ORDER BY position, id
                """,
                (url,),
            ).fetchall()


class Handler(BaseHTTPRequestHandler):
    dashboard: Dashboard

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/":
                self.html(self.index())
            elif parsed.path == "/property":
                url = parse_qs(parsed.query).get("url", [""])[0]
                self.html(self.property_page(url))
            elif parsed.path.startswith("/images/"):
                self.image(parsed.path.removeprefix("/images/"))
            else:
                self.error_page(HTTPStatus.NOT_FOUND, "Not found")
        except sqlite3.Error as exc:
            self.error_page(HTTPStatus.INTERNAL_SERVER_ERROR, f"DB error: {exc}")

    def index(self) -> str:
        rows = self.dashboard.targets()
        cards = []
        for row in rows:
            ok = int(row["ok"] or 0) == 1
            status_class = "ok" if ok else "bad"
            status = row["status_text"] or "not fetched"
            detail_href = "/property?url=" + quote(row["url"], safe="")
            cards.append(
                f"""
                <article class="card">
                  <div class="card-head">
                    <h2><a href="{detail_href}">{escape(row['name'])}</a></h2>
                    <span class="pill {status_class}">{escape(status)}</span>
                  </div>
                  <div class="price">{escape(yen(row['price']))}</div>
                  <p class="memo">{escape(row['memo'] or '')}</p>
                  <dl class="meta">
                    <dt>Fetched</dt><dd>{escape(row['fetched_at'] or 'not fetched')}</dd>
                    <dt>HTTP</dt><dd>{escape(str(row['status_code'] or 'unknown'))}</dd>
                    <dt>Contact</dt><dd>{escape(yes_no(row['contact_available']))}</dd>
                    <dt>Photos</dt><dd>{int(row['image_count'] or 0)}</dd>
                  </dl>
                  <p class="last-event {severity_class(row['last_event_severity'])}">
                    {escape(short_text(row['last_event_message']) or 'No events')}
                  </p>
                  <a class="external" href="{escape(row['url'])}" target="_blank" rel="noreferrer">Open listing</a>
                </article>
                """
            )
        return self.layout(
            "Property Watcher",
            f"""
            <section class="summary">
              <h1>Property Watcher</h1>
              <p>{len(rows)} properties. DB: <code>{escape(self.dashboard.db_path)}</code></p>
            </section>
            <section class="grid">{''.join(cards)}</section>
            <section class="events">
              <h2>Recent Events</h2>
              {self.event_table(self.dashboard.events(limit=30))}
            </section>
            """,
        )

    def property_page(self, url: str) -> str:
        row = self.dashboard.target(url)
        if row is None:
            return self.layout("Not found", "<h1>Property not found</h1>")

        images = self.dashboard.images(url)
        gallery = "".join(self.image_figure(image) for image in images) or "<p>No saved photos.</p>"

        body = f"""
        <p><a href="/">Back to list</a></p>
        <section class="detail">
          <h1>{escape(row['name'])}</h1>
          <p class="price">{escape(yen(row['price']))}</p>
          <p>{escape(row['memo'] or '')}</p>
          <p><a class="external" href="{escape(row['url'])}" target="_blank" rel="noreferrer">Open listing</a></p>
          <dl class="meta wide">
            <dt>Status</dt><dd>{escape(row['status_text'] or 'not fetched')}</dd>
            <dt>Fetched</dt><dd>{escape(row['fetched_at'] or 'not fetched')}</dd>
            <dt>HTTP</dt><dd>{escape(str(row['status_code'] or 'unknown'))}</dd>
            <dt>Contact</dt><dd>{escape(yes_no(row['contact_available']))}</dd>
            <dt>Title</dt><dd>{escape(row['title'] or '')}</dd>
            <dt>Final URL</dt><dd>{escape(row['final_url'] or '')}</dd>
            <dt>Saved photos</dt><dd>{escape(str(row['image_saved_count'] if row['image_saved_count'] is not None else 'not attempted'))}</dd>
            <dt>Photo error</dt><dd>{escape(row['image_error'] or '')}</dd>
            <dt>Fetch error</dt><dd>{escape(row['error'] or '')}</dd>
          </dl>
        </section>
        <section>
          <h2>Saved Photos</h2>
          <div class="gallery">{gallery}</div>
        </section>
        <section>
          <h2>Property Events</h2>
          {self.event_table(self.dashboard.events(url=url))}
        </section>
        <section>
          <h2>Latest Text</h2>
          <pre>{escape(row['raw_text'] or '')}</pre>
        </section>
        """
        return self.layout(row["name"], body)

    def image_figure(self, image: sqlite3.Row) -> str:
        image_url = "/images/" + quote(image["local_path"].replace("\\", "/"), safe="/")
        return (
            f"""
            <figure>
              <a href="{image_url}" target="_blank">
                <img src="{image_url}" alt="{escape(image['caption'] or '')}">
              </a>
              <figcaption>{escape(image['caption'] or image['image_type'])}</figcaption>
            </figure>
            """
        )

    def event_table(self, events: list[sqlite3.Row]) -> str:
        if not events:
            return "<p>No events.</p>"
        rows = []
        for event in events:
            rows.append(
                f"""
                <tr>
                  <td>{escape(event['occurred_at'])}</td>
                  <td><span class="{severity_class(event['severity'])}">{escape(event['severity'])}</span></td>
                  <td>{escape(event['event_type'])}</td>
                  <td>{escape(event['name'] or '')}</td>
                  <td>{escape(event['message'])}</td>
                  <td>{escape(event['old_value'] or '')}</td>
                  <td>{escape(event['new_value'] or '')}</td>
                </tr>
                """
            )
        return f"""
        <div class="table-wrap">
          <table>
            <thead>
              <tr><th>Time</th><th>Severity</th><th>Type</th><th>Property</th><th>Message</th><th>Old</th><th>New</th></tr>
            </thead>
            <tbody>{''.join(rows)}</tbody>
          </table>
        </div>
        """

    def image(self, local_path: str) -> None:
        decoded = unquote(local_path).replace("/", "\\")
        path = Path(decoded)
        if not path.is_absolute():
            path = Path.cwd() / path
        resolved = path.resolve()
        if self.dashboard.image_dir not in resolved.parents and resolved != self.dashboard.image_dir:
            self.error_page(HTTPStatus.FORBIDDEN, "Forbidden")
            return
        if not resolved.exists() or not resolved.is_file():
            self.error_page(HTTPStatus.NOT_FOUND, "Image not found")
            return
        content_type = mimetypes.guess_type(str(resolved))[0] or "application/octet-stream"
        data = resolved.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def html(self, body: str) -> None:
        data = body.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def error_page(self, status: HTTPStatus, message: str) -> None:
        data = self.layout(status.phrase, f"<h1>{escape(status.phrase)}</h1><p>{escape(message)}</p>").encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def layout(self, title: str, body: str) -> str:
        return f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <style>
    :root {{ color-scheme: light; --bg:#f5f7fb; --card:#fff; --text:#162033; --muted:#667085; --line:#d8deea; --brand:#2563eb; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; padding: 24px; font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: var(--bg); color: var(--text); }}
    a {{ color: var(--brand); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    h1 {{ margin: 0 0 8px; }}
    h2 {{ margin: 0 0 12px; font-size: 18px; }}
    code {{ background: #eef2ff; padding: 2px 6px; border-radius: 6px; }}
    .summary, .detail, .events, section {{ margin: 0 0 24px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px; }}
    .card, .detail, .events, section {{ background: var(--card); border: 1px solid var(--line); border-radius: 16px; padding: 18px; box-shadow: 0 8px 24px rgba(22, 32, 51, .04); }}
    .card-head {{ display: flex; gap: 12px; justify-content: space-between; align-items: start; }}
    .card h2 {{ line-height: 1.35; }}
    .price {{ font-size: 26px; font-weight: 750; margin: 8px 0; }}
    .memo, .last-event {{ color: var(--muted); min-height: 1.5em; }}
    .pill {{ display: inline-block; white-space: nowrap; border-radius: 999px; padding: 5px 9px; font-size: 12px; font-weight: 700; }}
    .ok {{ background: #dcfce7; color: #166534; }}
    .bad {{ background: #fee2e2; color: #991b1b; }}
    .meta {{ display: grid; grid-template-columns: 90px 1fr; gap: 6px 10px; margin: 14px 0; }}
    .meta dt {{ color: var(--muted); }}
    .meta dd {{ margin: 0; word-break: break-all; }}
    .wide {{ grid-template-columns: 120px 1fr; }}
    .external {{ display: inline-block; margin-top: 8px; font-weight: 700; }}
    .sev-high {{ color: #b91c1c; font-weight: 700; }}
    .sev-medium {{ color: #b45309; font-weight: 700; }}
    .sev-low {{ color: #475569; }}
    .sev-info {{ color: #2563eb; }}
    .table-wrap {{ overflow-x: auto; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 14px; }}
    th, td {{ border-bottom: 1px solid var(--line); padding: 9px 8px; text-align: left; vertical-align: top; }}
    th {{ color: var(--muted); font-weight: 700; }}
    .gallery {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 14px; }}
    figure {{ margin: 0; }}
    img {{ width: 100%; aspect-ratio: 4 / 3; object-fit: cover; border-radius: 12px; border: 1px solid var(--line); background: #e5e7eb; }}
    figcaption {{ color: var(--muted); font-size: 12px; margin-top: 4px; }}
    pre {{ white-space: pre-wrap; overflow-wrap: anywhere; background: #0f172a; color: #e2e8f0; padding: 16px; border-radius: 12px; max-height: 520px; overflow: auto; }}
    @media (max-width: 640px) {{
      body {{ padding: 12px; }}
      .grid {{ grid-template-columns: 1fr; gap: 12px; }}
      .card, .detail, .events, section {{ border-radius: 12px; padding: 14px; }}
      .card-head {{ display: block; }}
      .pill {{ margin-top: 8px; }}
      .price {{ font-size: 22px; }}
      .meta, .wide {{ grid-template-columns: 82px 1fr; font-size: 13px; }}
      .gallery {{ grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }}
      table {{ font-size: 12px; }}
      th, td {{ padding: 7px 6px; }}
    }}
  </style>
</head>
<body>{body}</body>
</html>"""

    def log_message(self, format: str, *args) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser(description="Property Watcher simple web dashboard")
    parser.add_argument("--db", default="property_watcher.db", help="SQLite DB path")
    parser.add_argument("--image-dir", default="property_images", help="saved image directory")
    parser.add_argument("--host", default="127.0.0.1", help="bind host")
    parser.add_argument("--port", type=int, default=8000, help="bind port")
    parser.add_argument("--mobile", action="store_true", help="bind to 0.0.0.0 and print LAN URLs")
    args = parser.parse_args()

    if args.mobile and args.host == "127.0.0.1":
        args.host = "0.0.0.0"

    if not Path(args.db).exists():
        raise SystemExit(f"DB not found: {args.db}")

    Handler.dashboard = Dashboard(args.db, args.image_dir)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Serving Property Watcher dashboard at http://{args.host}:{args.port}/")
    if args.mobile:
        urls = lan_addresses(args.port)
        if urls:
            print("Open one of these URLs from a phone on the same Wi-Fi:")
            for url in urls:
                print(f"  {url}")
        else:
            print("Could not detect a LAN IP. Check your PC's Wi-Fi IPv4 address.")
    server.serve_forever()


if __name__ == "__main__":
    main()
