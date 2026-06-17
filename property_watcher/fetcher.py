from datetime import datetime, timezone
import requests

from .models import Snapshot
from .parser import parse_html

USER_AGENT = "Mozilla/5.0 (compatible; PersonalPropertyWatcher/1.0; +https://github.com/)"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fetch_snapshot(url: str, timeout: int = 20) -> Snapshot:
    fetched_at = now_iso()
    try:
        response = requests.get(
            url,
            timeout=timeout,
            headers={
                "User-Agent": USER_AGENT,
                "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
            },
            allow_redirects=True,
        )
        status_code = response.status_code
        final_url = response.url
        ok = 200 <= status_code < 400

        if not ok:
            return Snapshot(
                url=url,
                fetched_at=fetched_at,
                ok=False,
                status_code=status_code,
                final_url=final_url,
                title="",
                price=None,
                status_text=f"HTTP {status_code}",
                contact_available=None,
                content_hash=f"HTTP_{status_code}",
                raw_text="",
                error=None,
            )

        parsed = parse_html(response.text)
        return Snapshot(
            url=url,
            fetched_at=fetched_at,
            ok=True,
            status_code=status_code,
            final_url=final_url,
            title=parsed["title"],
            price=parsed["price"],
            status_text=parsed["status_text"],
            contact_available=parsed["contact_available"],
            content_hash=parsed["content_hash"],
            raw_text=parsed["raw_text"],
            error=None,
        )
    except Exception as exc:
        return Snapshot(
            url=url,
            fetched_at=fetched_at,
            ok=False,
            status_code=None,
            final_url=None,
            title="",
            price=None,
            status_text="取得失敗",
            contact_available=None,
            content_hash=f"ERROR_{type(exc).__name__}",
            raw_text="",
            error=str(exc),
        )
