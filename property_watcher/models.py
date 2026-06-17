from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class PropertyTarget:
    name: str
    url: str
    memo: str = ""


@dataclass(frozen=True)
class Snapshot:
    url: str
    fetched_at: str
    ok: bool
    status_code: Optional[int]
    final_url: Optional[str]
    title: str
    price: Optional[int]
    status_text: str
    contact_available: Optional[bool]
    content_hash: str
    raw_text: str = ""
    error: Optional[str] = None
