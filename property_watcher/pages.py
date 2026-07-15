import argparse
import shutil
import unicodedata
from hashlib import sha1
from html import escape
from pathlib import Path

from .web import Dashboard, severity_class, short_text, yes_no


def page_name(url: str) -> str:
    return sha1(url.encode("utf-8")).hexdigest()[:16] + ".html"


def rel_image_path(local_path: str) -> str:
    return "../" + local_path.replace("\\", "/")


def layout(title: str, body: str, root_prefix: str = "") -> str:
    return f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <link rel="stylesheet" href="{root_prefix}assets/style.css">
</head>
<body>{body}</body>
</html>"""


def stylesheet() -> str:
    return """
:root { color-scheme: light; --bg:#f5f7fb; --card:#fff; --text:#162033; --muted:#667085; --line:#d8deea; --brand:#2563eb; }
* { box-sizing: border-box; }
body { margin: 0; padding: 24px; font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: var(--bg); color: var(--text); }
a { color: var(--brand); text-decoration: none; }
a:hover { text-decoration: underline; }
h1 { margin: 0 0 8px; }
h2 { margin: 0 0 12px; font-size: 18px; }
code { background: #eef2ff; padding: 2px 6px; border-radius: 6px; }
.summary, .detail, .events, section { margin: 0 0 24px; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px; }
.card, .detail, .events, section { background: var(--card); border: 1px solid var(--line); border-radius: 16px; padding: 18px; box-shadow: 0 8px 24px rgba(22, 32, 51, .04); }
.card-head { display: flex; gap: 12px; justify-content: space-between; align-items: start; }
.card h2 { line-height: 1.35; }
.price { font-size: 26px; font-weight: 750; margin: 8px 0; }
.price-history { margin: 14px 0; padding: 12px; border: 1px solid var(--line); border-radius: 12px; background: #f8fafc; }
.price-history-title { color: var(--muted); font-size: 12px; font-weight: 700; margin-bottom: 8px; }
.price-history-track { display: flex; align-items: center; gap: 8px; overflow-x: auto; padding-bottom: 3px; scrollbar-width: thin; }
.price-history-point { flex: 0 0 auto; display: grid; gap: 2px; }
.price-history-value { font-size: 14px; font-weight: 750; white-space: nowrap; }
.price-history-date { color: var(--muted); font-size: 11px; }
.price-history-arrow { flex: 0 0 auto; color: #94a3b8; font-weight: 700; }
.memo, .last-event { color: var(--muted); min-height: 1.5em; }
.pill { display: inline-block; white-space: nowrap; border-radius: 999px; padding: 5px 9px; font-size: 12px; font-weight: 700; }
.ok { background: #dcfce7; color: #166534; }
.bad { background: #fee2e2; color: #991b1b; }
.meta { display: grid; grid-template-columns: 90px 1fr; gap: 6px 10px; margin: 14px 0; }
.meta dt { color: var(--muted); }
.meta dd { margin: 0; word-break: break-all; }
.wide { grid-template-columns: 120px 1fr; }
.external { display: inline-block; margin-top: 8px; font-weight: 700; }
.sev-high { color: #b91c1c; font-weight: 700; }
.sev-medium { color: #b45309; font-weight: 700; }
.sev-low { color: #475569; }
.sev-info { color: #2563eb; }
.table-wrap { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: 14px; }
th, td { border-bottom: 1px solid var(--line); padding: 9px 8px; text-align: left; vertical-align: top; }
th { color: var(--muted); font-weight: 700; }
.gallery { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 14px; }
figure { margin: 0; }
img { width: 100%; aspect-ratio: 4 / 3; object-fit: cover; border-radius: 12px; border: 1px solid var(--line); background: #e5e7eb; }
figcaption { color: var(--muted); font-size: 12px; margin-top: 4px; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; background: #0f172a; color: #e2e8f0; padding: 16px; border-radius: 12px; max-height: 520px; overflow: auto; }
@media (max-width: 640px) {
  body { padding: 12px; }
  .grid { grid-template-columns: 1fr; gap: 12px; }
  .card, .detail, .events, section { border-radius: 12px; padding: 14px; }
  .card-head { display: block; }
  .pill { margin-top: 8px; }
  .price { font-size: 22px; }
  .price-history { margin: 12px 0; padding: 10px; }
  .meta, .wide { grid-template-columns: 82px 1fr; font-size: 13px; }
  .gallery { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
  table { font-size: 12px; }
  th, td { padding: 7px 6px; }
}
"""


def event_table(events) -> str:
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


def name_sort_key(row) -> str:
    return unicodedata.normalize("NFKC", row["name"]).casefold()


def price_label(value) -> str:
    if value is None:
        return "価格不明"
    return f"{int(value):,}万円"


def price_history_html(history: list[tuple[int, str | None]]) -> str:
    if not history:
        return """
        <div class="price-history">
          <div class="price-history-title">価格推移</div>
          <span class="price-history-date">価格情報なし</span>
        </div>
        """

    points = []
    for index, (price, occurred_at) in enumerate(history):
        if index:
            points.append('<span class="price-history-arrow" aria-hidden="true">→</span>')
        if occurred_at:
            date_label = occurred_at[:10].replace("-", "/")
        elif index == len(history) - 1:
            date_label = "現在"
        else:
            date_label = "以前"
        points.append(
            f"""
            <span class="price-history-point">
              <span class="price-history-value">{price:,}万円</span>
              <span class="price-history-date">{date_label}</span>
            </span>
            """
        )

    return f"""
    <div class="price-history" aria-label="価格推移">
      <div class="price-history-title">価格推移</div>
      <div class="price-history-track">{''.join(points)}</div>
    </div>
    """


def render_index(dashboard: Dashboard) -> str:
    rows = sorted(dashboard.targets(), key=name_sort_key)
    cards = []
    for row in rows:
        ok = int(row["ok"] or 0) == 1
        status_class = "ok" if ok else "bad"
        status = row["status_text"] or "not fetched"
        cards.append(
            f"""
            <article class="card">
              <div class="card-head">
                <h2><a href="properties/{page_name(row['url'])}">{escape(row['name'])}</a></h2>
                <span class="pill {status_class}">{escape(status)}</span>
              </div>
              <div class="price">{escape(price_label(row['price']))}</div>
              {price_history_html(dashboard.price_history(row['url'], row['price']))}
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
    return layout(
        "Property Watcher",
        f"""
        <section class="summary">
          <h1>Property Watcher</h1>
          <p>{len(rows)} properties. Static GitHub Pages snapshot generated from <code>property_watcher.db</code>.</p>
        </section>
        <section class="grid">{''.join(cards)}</section>
        <section class="events">
          <h2>Recent Events</h2>
          {event_table(dashboard.events(limit=30))}
        </section>
        """,
    )


def render_property(dashboard: Dashboard, url: str) -> str:
    row = dashboard.target(url)
    if row is None:
        return layout("Not found", "<h1>Property not found</h1>", root_prefix="../")

    figures = []
    for image in dashboard.images(url):
        src = rel_image_path(image["local_path"])
        figures.append(
            f"""
            <figure>
              <a href="{escape(src)}" target="_blank">
                <img src="{escape(src)}" alt="{escape(image['caption'] or '')}">
              </a>
              <figcaption>{escape(image['caption'] or image['image_type'])}</figcaption>
            </figure>
            """
        )
    gallery = "".join(figures) or "<p>No saved photos.</p>"

    return layout(
        row["name"],
        f"""
        <p><a href="../index.html">Back to list</a></p>
        <section class="detail">
          <h1>{escape(row['name'])}</h1>
          <p class="price">{escape(price_label(row['price']))}</p>
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
          {event_table(dashboard.events(url=url))}
        </section>
        <section>
          <h2>Latest Text</h2>
          <pre>{escape(row['raw_text'] or '')}</pre>
        </section>
        """,
        root_prefix="../",
    )


def export_site(db_path: str, image_dir: str, out_dir: str) -> None:
    out = Path(out_dir)
    if out.exists():
        shutil.rmtree(out)
    (out / "assets").mkdir(parents=True)
    (out / "properties").mkdir(parents=True)

    dashboard = Dashboard(db_path, image_dir)
    (out / "assets" / "style.css").write_text(stylesheet(), encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    (out / "index.html").write_text(render_index(dashboard), encoding="utf-8")

    for row in dashboard.targets():
        (out / "properties" / page_name(row["url"])).write_text(
            render_property(dashboard, row["url"]),
            encoding="utf-8",
        )

    images = Path(image_dir)
    if images.exists():
        shutil.copytree(images, out / "property_images")


def main() -> None:
    parser = argparse.ArgumentParser(description="Export Property Watcher as a static GitHub Pages site")
    parser.add_argument("--db", default="property_watcher.db", help="SQLite DB path")
    parser.add_argument("--image-dir", default="property_images", help="saved image directory")
    parser.add_argument("--out", default="site", help="output directory")
    args = parser.parse_args()

    if not Path(args.db).exists():
        raise SystemExit(f"DB not found: {args.db}")

    export_site(args.db, args.image_dir, args.out)
    print(f"Exported static site to {args.out}")


if __name__ == "__main__":
    main()
