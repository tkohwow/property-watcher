import hashlib
import json
import re
from typing import Any

from bs4 import BeautifulSoup
from bs4.element import Tag


END_KEYWORDS = [
    "掲載終了", "公開終了", "販売終了", "成約済", "成約済み", "募集終了",
    "この物件は現在掲載されておりません", "この物件は掲載が終了しました",
    "お探しのページは見つかりません",
]

CONTACT_KEYWORDS = ["問い合わせ", "問合せ", "資料請求", "見学予約", "内見予約", "空室確認"]

PRICE_PATTERNS = [
    re.compile(r"([0-9,]+)\s*万円"),
    re.compile(r"価格[^0-9]{0,10}([0-9,]+)"),
]

PROPERTY_KEYWORDS = [
    "物件名", "価格", "販売価格", "間取り", "専有面積", "バルコニー", "所在階",
    "階建", "向き", "所在地", "住所", "交通", "沿線", "駅", "徒歩", "管理費",
    "修繕積立金", "その他費用", "築年月", "築年数", "完成時期", "構造", "総戸数",
    "土地権利", "用途地域", "管理形態", "管理員", "現況", "引渡", "取引態様",
    "情報提供日", "次回更新日", "備考", "特徴", "設備", "リフォーム",
    "リノベーション", "ペット", "駐車場", "駐輪場", "バイク置場", "管理会社",
    "施工", "分譲",
]

NOISE_KEYWORDS = [
    "ログイン", "マイページ", "お気に入り", "全国へ", "サイトマップ", "おすすめ物件",
    "最近見た物件", "ランキング", "引越し見積もり", "住宅ローン", "返済",
    "シミュレーション", "資料請求", "お問い合わせ", "無料",
    "注文住宅", "新築マンションを探す", "中古一戸建てを買う", "土地を買う",
    "賃貸マンションを借りる", "会社概要", "利用規約", "個人情報保護方針",
    "プライバシーポリシー", "Copyright", "Produced By Recruit",
]

REMOVE_TAGS = [
    "script", "style", "noscript", "svg", "header", "footer", "nav", "aside", "form",
    "button", "select", "option", "iframe",
]

# 属性値を単語単位で見る。以前の `ad` の部分一致は main-detail などまで消し得た。
NOISE_ATTR_TOKEN = re.compile(
    r"(?:^|[-_\s])(breadcrumb|gnav|global-nav|login|mypage|favorite|history|recent|"
    r"recommend|related|ranking|advert|advertisement|banner|bnr|campaign|modal|popup|"
    r"pagination|sidebar|sns|share)(?:$|[-_\s])",
    re.IGNORECASE,
)

MAX_RAW_TEXT_CHARS = 12_000
MAX_VALUE_CHARS = 600


def normalize_text(text: str) -> str:
    text = re.sub(r"[\t\r\f\v]+", " ", text)
    text = re.sub(r"[ \u3000]+", " ", text)
    return text.strip()


def normalize_line(text: str) -> str:
    text = normalize_text(text)
    text = re.sub(r"\s*([：:])\s*", r"\1", text)
    return text.strip(" ｜|/　")


def _meta_content(soup: BeautifulSoup, *, property_name: str = "", name: str = "") -> str:
    attrs = {"property": property_name} if property_name else {"name": name}
    tag = soup.find("meta", attrs=attrs)
    return normalize_line(str(tag.get("content", ""))) if isinstance(tag, Tag) else ""


def _page_title(soup: BeautifulSoup) -> str:
    if soup.title:
        title = normalize_line(soup.title.get_text(" ", strip=True))
        if title:
            return title
    return _meta_content(soup, property_name="og:title")


def _property_name(soup: BeautifulSoup, page_title: str) -> str:
    h1 = soup.find("h1")
    if isinstance(h1, Tag):
        value = normalize_line(h1.get_text(" ", strip=True))
        if value and not _is_noise(value):
            return value
    return _meta_content(soup, property_name="og:title") or page_title


def _is_noise(line: str) -> bool:
    if not line or len(line) <= 1 or len(line) > MAX_VALUE_CHARS:
        return True
    return any(keyword.lower() in line.lower() for keyword in NOISE_KEYWORDS)


def _is_property_label(label: str) -> bool:
    compact = re.sub(r"[：:\s※*]+", "", label)
    return 1 <= len(compact) <= 30 and any(keyword in compact for keyword in PROPERTY_KEYWORDS)


def _clean_value(value: str) -> str:
    value = normalize_line(value)
    value = re.sub(r"(?:\s*\n\s*)+", " / ", value)
    return value


def _add_line(lines: list[str], seen: set[str], line: str) -> None:
    line = normalize_line(line)
    # 保存テキストは人が読むものなので、ラベル区切りを見やすく統一する。
    line = re.sub(r"^([^:：\n]+)[:：](.*)$", lambda match: f"{match.group(1)}: {match.group(2).strip()}", line)
    if _is_noise(line) or line in seen:
        return
    if sum(len(item) + 1 for item in lines) + len(line) > MAX_RAW_TEXT_CHARS:
        return
    lines.append(line)
    seen.add(line)


def _extract_table_pairs(soup: BeautifulSoup) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for row in soup.find_all("tr"):
        cells = row.find_all(["th", "td"], recursive=False)
        if len(cells) < 2:
            continue
        label = _clean_value(cells[0].get_text(" ", strip=True))
        value = _clean_value(" / ".join(cell.get_text(" ", strip=True) for cell in cells[1:]))
        if _is_property_label(label) and value and value != label and not _is_noise(value):
            pairs.append((label, value))
    return pairs


def _extract_definition_pairs(soup: BeautifulSoup) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for dt in soup.find_all("dt"):
        dd = dt.find_next_sibling("dd")
        if not isinstance(dd, Tag):
            continue
        label = _clean_value(dt.get_text(" ", strip=True))
        value = _clean_value(dd.get_text(" ", strip=True))
        if _is_property_label(label) and value and value != label and not _is_noise(value):
            pairs.append((label, value))
    return pairs


def _walk_json(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json(child)


def _extract_json_ld(soup: BeautifulSoup) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    label_map = {
        "name": "物件名", "address": "所在地", "floorSize": "専有面積",
        "numberOfRooms": "間取り", "datePosted": "情報提供日",
    }
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(tag.string or tag.get_text())
        except (json.JSONDecodeError, TypeError):
            continue
        for obj in _walk_json(data):
            object_type = obj.get("@type", "")
            types = object_type if isinstance(object_type, list) else [object_type]
            # BreadcrumbList や Organization の name/address を物件情報として混ぜない。
            if not any(str(value).lower() in {
                "product", "apartment", "accommodation", "residence", "house",
                "singlefamilyresidence", "realestatelisting",
            } for value in types):
                continue
            for key, label in label_map.items():
                value = obj.get(key)
                if isinstance(value, dict):
                    value = value.get("name") or value.get("value") or value.get("streetAddress")
                if isinstance(value, (str, int, float)):
                    pairs.append((label, str(value)))
            offers = obj.get("offers")
            if isinstance(offers, dict) and offers.get("price"):
                price = str(offers["price"])
                if offers.get("priceCurrency") == "JPY" and re.fullmatch(r"\d+(?:\.0+)?", price):
                    yen = int(float(price))
                    price = f"{yen // 10_000:,}万円" if yen >= 1_000_000 and yen % 10_000 == 0 else f"{yen:,}円"
                pairs.append(("価格", price))
    return pairs


def _extract_features(soup: BeautifulSoup) -> list[str]:
    features: list[str] = []
    seen: set[str] = set()
    for heading in soup.find_all(re.compile(r"^h[2-6]$")):
        heading_text = normalize_line(heading.get_text(" ", strip=True))
        if not any(word in heading_text for word in ("特徴", "設備")):
            continue
        container = heading.find_next_sibling()
        if not isinstance(container, Tag):
            continue
        for item in container.find_all("li")[:40]:
            value = normalize_line(item.get_text(" ", strip=True))
            if value and value not in seen and not _is_noise(value) and len(value) <= 80:
                features.append(value)
                seen.add(value)
    return features


def _remove_noise_elements(soup: BeautifulSoup) -> None:
    for tag in soup(REMOVE_TAGS):
        tag.decompose()
    for tag in list(soup.find_all(True)):
        # 親要素を decompose() すると、先に列挙済みの子要素も attrs=None の
        # 破棄済みTagになる。そこへ tag.get() すると BeautifulSoup 内で例外になる。
        if tag.attrs is None:
            continue
        values: list[str] = []
        for attr in ("id", "class", "role", "aria-label"):
            value = tag.get(attr)
            values.extend(value if isinstance(value, list) else [str(value)] if value else [])
        if values and NOISE_ATTR_TOKEN.search(" ".join(values)):
            tag.decompose()


def _extract_keyword_fallback(soup: BeautifulSoup) -> list[str]:
    # 概要表のないサイト向け。物件語や明確な値を含む行だけに限定する。
    fallback: list[str] = []
    for raw in soup.get_text("\n").splitlines():
        line = normalize_line(raw)
        looks_like_value = bool(re.search(
            r"[0-9,]+\s*万円|\d+(?:\.\d+)?\s*(?:m2|㎡)|徒歩\s*\d+分|歩\s*\d+分|"
            r"\d{4}年\d{1,2}月|\b[1-9]\d*LDK\b",
            line,
            re.IGNORECASE,
        ))
        if (any(word in line for word in PROPERTY_KEYWORDS) or looks_like_value) and not _is_noise(line):
            fallback.append(line)
    return fallback


def extract_clean_text(soup: BeautifulSoup, page_title: str) -> str:
    lines: list[str] = []
    seen: set[str] = set()
    name = _property_name(soup, page_title)
    if name:
        _add_line(lines, seen, f"物件名: {name}")

    pairs = _extract_json_ld(soup) + _extract_table_pairs(soup) + _extract_definition_pairs(soup)
    for label, value in pairs:
        _add_line(lines, seen, f"{normalize_line(label)}: {_clean_value(value)}")

    features = _extract_features(soup)
    if features:
        _add_line(lines, seen, "特徴:")
        for feature in features:
            _add_line(lines, seen, f"- {feature}")

    # 構造化情報が乏しい場合のみ description とキーワード行で補完する。
    if len(lines) < 5:
        description = _meta_content(soup, name="description") or _meta_content(soup, property_name="og:description")
        if description and not _is_noise(description):
            _add_line(lines, seen, f"概要: {description}")

        if not pairs:
            fallback_soup = BeautifulSoup(str(soup), "lxml")
            _remove_noise_elements(fallback_soup)
            for line in _extract_keyword_fallback(fallback_soup):
                _add_line(lines, seen, line)

    return "\n".join(lines).strip()


def extract_price(text: str) -> int | None:
    candidates: list[int] = []
    for pattern in PRICE_PATTERNS:
        for match in pattern.finditer(text):
            try:
                value = int(match.group(1).replace(",", ""))
            except ValueError:
                continue
            if value >= 100:
                candidates.append(value)
    return candidates[0] if candidates else None


def parse_html(html: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    full_text = normalize_text(soup.get_text(" "))
    title = _page_title(soup)
    clean_text = extract_clean_text(soup, title)
    status_flags = [keyword for keyword in END_KEYWORDS if keyword in full_text]

    return {
        "title": title,
        # 構造化済み本文を先に見ることで、広告中の価格を拾いにくくする。
        "price": extract_price(clean_text) or extract_price(full_text),
        "status_text": ", ".join(status_flags) if status_flags else "掲載中の可能性",
        "contact_available": any(keyword in full_text for keyword in CONTACT_KEYWORDS) if full_text else None,
        "content_hash": hashlib.sha256(clean_text.encode("utf-8", errors="ignore")).hexdigest(),
        "raw_text": clean_text,
    }
