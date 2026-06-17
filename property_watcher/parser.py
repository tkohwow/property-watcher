import hashlib
import re
from bs4 import BeautifulSoup
from bs4.element import Tag

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

# raw_text を見返す用途に不要なナビ・広告・おすすめ枠を落とすための汎用フィルタ。
# サイトごとにDOM構造が違うため、まずは過剰に本文を消しすぎない範囲で共通ノイズを除去する。
REMOVE_TAGS = [
    "script",
    "style",
    "noscript",
    "svg",
    "header",
    "footer",
    "nav",
    "aside",
    "form",
    "button",
    "select",
    "option",
    "iframe",
]

REMOVE_ATTR_PATTERN = re.compile(
    r"(header|footer|nav|breadcrumb|bread|menu|gnav|global|login|mypage|favorite|history|recent|"
    r"recommend|relation|related|ranking|ad|ads|advert|banner|bnr|campaign|modal|popup|pager|"
    r"pagination|side|sidebar|sns|share|search|condition|footer|assist|guide|pr)",
    re.IGNORECASE,
)

BOILERPLATE_LINE_PATTERNS = [
    re.compile(p)
    for p in [
        r"^\s*$",
        r"^SUUMO\b",
        r"Produced By Recruit",
        r"全国へ",
        r"サイトマップ",
        r"初めての方へ",
        r"ログイン",
        r"マイページ",
        r"お気に入り",
        r"閲覧履歴",
        r"検索$",
        r"検索条件",
        r"資料請求する\s*\(無料\)",
        r"問い合わせ先",
        r"お問い合わせ先",
        r"不動産会社ガイド",
        r"住宅ローン",
        r"無料査定",
        r"引越し見積もり",
        r"リフォーム",
        r"注文住宅",
        r"新築マンション",
        r"中古マンションを買う",
        r"中古一戸建てを買う",
        r"土地を買う",
        r"賃貸マンションを借りる",
        r"この街の情報を見る",
        r"資料請求・お問い合わせ",
        r"お気に入りに追加しました",
        r"あなたにオススメ",
        r"おすすめ物件",
        r"最近見た物件",
        r"周辺の物件",
        r"周辺環境",
        r"会社概要",
        r"個人情報保護方針",
        r"利用規約",
        r"免責事項",
        r"Copyright",
        r"©",
    ]
]

# 物件情報として残したい可能性が高い語。raw_text はこれらを含む行を優先して残す。
IMPORTANT_KEYWORDS = [
    "物件名",
    "価格",
    "販売価格",
    "間取り",
    "専有面積",
    "バルコニー",
    "所在階",
    "階建",
    "向き",
    "所在地",
    "住所",
    "交通",
    "沿線",
    "駅",
    "徒歩",
    "管理費",
    "修繕積立金",
    "築年月",
    "築年数",
    "完成時期",
    "構造",
    "総戸数",
    "土地権利",
    "用途地域",
    "管理形態",
    "管理員",
    "現況",
    "引渡",
    "取引態様",
    "備考",
    "特徴",
    "設備",
    "リフォーム",
    "リノベーション",
    "ペット",
    "駐車場",
    "駐輪場",
    "バイク置場",
    "管理会社",
    "施工",
    "分譲",
    "グラーサ中野坂上",
]


def normalize_text(text: str) -> str:
    text = re.sub(r"[\t\r\f\v]+", " ", text)
    text = re.sub(r" +", " ", text)
    return text.strip()


def normalize_line(text: str) -> str:
    text = normalize_text(text)
    text = re.sub(r"\s*([：:])\s*", r"\1", text)
    return text.strip(" ｜|-/　")


def is_boilerplate_line(line: str) -> bool:
    if not line:
        return True
    if len(line) <= 1:
        return True
    if len(line) > 220:
        # 1行が長すぎるものは、ナビ・免責・おすすめ枠が連結した可能性が高い。
        return True
    return any(pattern.search(line) for pattern in BOILERPLATE_LINE_PATTERNS)


def element_attr_text(tag: Tag) -> str:
    values: list[str] = []
    for attr in ("id", "class", "role", "aria-label", "data-testid"):
        value = tag.get(attr)
        if isinstance(value, list):
            values.extend(str(v) for v in value)
        elif value:
            values.append(str(value))
    return " ".join(values)


def remove_noise_elements(soup: BeautifulSoup) -> None:
    for tag in soup(REMOVE_TAGS):
        tag.decompose()

    for tag in list(soup.find_all(True)):
        if not isinstance(tag, Tag):
            continue
        attrs = element_attr_text(tag)
        if attrs and REMOVE_ATTR_PATTERN.search(attrs):
            tag.decompose()


def extract_clean_text(soup: BeautifulSoup, title: str) -> str:
    # 改行区切りで抽出し、UI文言・広告・ナビをできるだけ落とす。
    raw_lines = soup.get_text("\n").splitlines()
    cleaned: list[str] = []
    seen: set[str] = set()

    if title:
        cleaned.append(title)
        seen.add(title)

    for raw in raw_lines:
        line = normalize_line(raw)
        if is_boilerplate_line(line):
            continue
        if line in seen:
            continue

        # 物件詳細っぽい行、または短めの説明文だけ残す。
        # これにより、SUUMOのフッター・広告・検索導線をかなり削る。
        has_important_keyword = any(keyword in line for keyword in IMPORTANT_KEYWORDS)
        looks_like_price = bool(re.search(r"[0-9,]+\s*万円", line))
        looks_like_station = bool(re.search(r"徒歩\d+分|歩\d+分", line))
        looks_like_area = bool(re.search(r"\d+(?:\.\d+)?\s*(?:m2|㎡)", line))
        looks_like_year = bool(re.search(r"\d{4}年\d{1,2}月|築\d+年", line))

        if has_important_keyword or looks_like_price or looks_like_station or looks_like_area or looks_like_year:
            cleaned.append(line)
            seen.add(line)
            continue

        # 短い説明文は残す。ただし一般ナビっぽいものは上で落とす。
        if 8 <= len(line) <= 80:
            cleaned.append(line)
            seen.add(line)

    # あまりにも少ない場合は、最低限の本文を残す。
    if len(cleaned) <= 3:
        fallback = []
        seen_fallback = set()
        for raw in raw_lines:
            line = normalize_line(raw)
            if is_boilerplate_line(line) or line in seen_fallback:
                continue
            fallback.append(line)
            seen_fallback.add(line)
            if len(fallback) >= 120:
                break
        cleaned = fallback

    return "\n".join(cleaned[:180]).strip()


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

    # 価格・掲載終了・問い合わせ有無の判定は、ノイズ除去前の本文も使う。
    full_text = normalize_text(soup.get_text(" "))

    title = ""
    if soup.title and soup.title.string:
        title = normalize_text(soup.title.string)

    remove_noise_elements(soup)
    clean_text = extract_clean_text(soup, title)

    status_flags = [kw for kw in END_KEYWORDS if kw in full_text]

    contact_available = None
    if full_text:
        contact_available = any(kw in full_text for kw in CONTACT_KEYWORDS)

    # content_hash は通知には使わないが、最新本文の変化確認用に残す。
    # 動的要素を除去した clean_text をhash化することで、DB上の揺れも抑える。
    content_hash = hashlib.sha256(clean_text.encode("utf-8", errors="ignore")).hexdigest()

    return {
        "title": title,
        "price": extract_price(full_text),
        "status_text": ", ".join(status_flags) if status_flags else "掲載中の可能性",
        "contact_available": contact_available,
        "content_hash": content_hash,
        "raw_text": clean_text,
    }
