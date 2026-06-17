import hashlib
import re
from bs4 import BeautifulSoup

END_KEYWORDS = [
    "掲載終了",
    "公開終了",
    "販売終了",
    "成約済",
    "成約済み",
    "募集終了",
    "この物件は現在掲載されておりません",
    "この物件は掲載が終了しました",
    "お探しのページは見つかりません",
]

CONTACT_KEYWORDS = ["問い合わせ", "問合せ", "資料請求", "見学予約", "内見予約", "空室確認"]

PRICE_PATTERNS = [
    re.compile(r"([0-9,]+)\s*万円"),
    re.compile(r"価格[^0-9]{0,10}([0-9,]+)"),
]


def normalize_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def extract_price(text: str) -> int | None:
    # 「管理費1万」などの小さい金額を拾いにくくするため、100万円以上を価格候補にする
    candidates: list[int] = []
    for pattern in PRICE_PATTERNS:
        for match in pattern.finditer(text):
            raw = match.group(1).replace(",", "")
            try:
                value = int(raw)
            except ValueError:
                continue
            if value >= 100:
                candidates.append(value)
    return candidates[0] if candidates else None


def parse_html(html: str) -> dict:
    soup = BeautifulSoup(html, "lxml")

    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()

    title = ""
    if soup.title and soup.title.string:
        title = normalize_text(soup.title.string)

    body_text = normalize_text(soup.get_text(" "))
    status_flags = [kw for kw in END_KEYWORDS if kw in body_text]

    contact_available = None
    if body_text:
        contact_available = any(kw in body_text for kw in CONTACT_KEYWORDS)

    # 動的な広告・日付等でhashが揺れすぎないよう、長すぎる空白をならした本文を使う
    content_hash = hashlib.sha256(body_text.encode("utf-8", errors="ignore")).hexdigest()

    return {
        "title": title,
        "price": extract_price(body_text),
        "status_text": ", ".join(status_flags) if status_flags else "掲載中の可能性",
        "contact_available": contact_available,
        "content_hash": content_hash,
    }
