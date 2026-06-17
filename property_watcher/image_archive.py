from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import re
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup
from PIL import Image, ImageOps
import requests

from .fetcher import USER_AGENT


INDOOR_KEYWORDS = (
    "リビング", "ダイニング", "キッチン", "浴室", "バス", "洗面", "トイレ",
    "居室", "洋室", "和室", "寝室", "収納", "玄関", "室内", "廊下",
)

MAX_IMAGES_PER_PROPERTY = 30
MAX_IMAGE_SIZE = (1280, 1280)
JPEG_QUALITY = 82


@dataclass(frozen=True)
class ImageCandidate:
    source_url: str
    download_url: str
    caption: str
    image_type: str
    position: int


@dataclass(frozen=True)
class ArchivedImage:
    source_url: str
    caption: str
    image_type: str
    position: int
    local_path: str
    content_hash: str
    saved_at: str


@dataclass(frozen=True)
class ArchiveResult:
    images: list[ArchivedImage]
    errors: list[str]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def classify_image(caption: str) -> str | None:
    return "indoor" if any(keyword in caption for keyword in INDOOR_KEYWORDS) else None


def _larger_image_url(url: str) -> str:
    parsed = urlparse(url)
    if "resizeImage" not in parsed.path:
        return url
    query = parse_qs(parsed.query)
    if "src" not in query:
        return url
    query["w"] = [str(MAX_IMAGE_SIZE[0])]
    query["h"] = [str(MAX_IMAGE_SIZE[1])]
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))


def extract_image_candidates(html: str, page_url: str) -> list[ImageCandidate]:
    soup = BeautifulSoup(html, "lxml")
    candidates: list[ImageCandidate] = []
    seen: set[str] = set()

    for image in soup.find_all("img"):
        caption = " ".join(str(image.get("alt", "")).split())
        image_type = classify_image(caption)
        if image_type is None:
            continue

        raw_url = next(
            (str(image.get(attr)) for attr in ("rel", "data-src", "data-original", "src") if image.get(attr)),
            "",
        )
        if not raw_url:
            continue
        source_url = urljoin(page_url, raw_url)
        canonical = parse_qs(urlparse(source_url).query).get("src", [source_url])[0]
        if canonical in seen:
            continue
        seen.add(canonical)
        candidates.append(
            ImageCandidate(
                source_url=source_url,
                download_url=_larger_image_url(source_url),
                caption=caption,
                image_type=image_type,
                position=len(candidates) + 1,
            )
        )
        if len(candidates) >= MAX_IMAGES_PER_PROPERTY:
            break

    return candidates


def _safe_directory_name(target_name: str, property_url: str) -> str:
    readable = re.sub(r"[^\w\-]+", "-", target_name, flags=re.UNICODE).strip("-")[:60]
    url_key = sha256(property_url.encode("utf-8")).hexdigest()[:10]
    return f"{readable or 'property'}-{url_key}"


def _to_jpeg(content: bytes) -> bytes:
    with Image.open(BytesIO(content)) as image:
        image = ImageOps.exif_transpose(image)
        if image.mode != "RGB":
            background = Image.new("RGB", image.size, "white")
            if "A" in image.getbands():
                background.paste(image, mask=image.getchannel("A"))
            else:
                background.paste(image)
            image = background
        image.thumbnail(MAX_IMAGE_SIZE, Image.Resampling.LANCZOS)
        output = BytesIO()
        image.save(output, format="JPEG", quality=JPEG_QUALITY, optimize=True)
        return output.getvalue()


def archive_property_images(
    html: str,
    property_url: str,
    target_name: str,
    root_dir: str = "property_images",
    timeout: int = 20,
) -> ArchiveResult:
    destination = Path(root_dir) / _safe_directory_name(target_name, property_url)
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "ja,en-US;q=0.9,en;q=0.8"})
    archived: list[ArchivedImage] = []
    errors: list[str] = []

    for candidate in extract_image_candidates(html, property_url):
        try:
            response = session.get(candidate.download_url, timeout=timeout)
            response.raise_for_status()
            digest = sha256(response.content).hexdigest()
            jpeg = _to_jpeg(response.content)
            filename = f"{candidate.position:02d}-{candidate.image_type}-{digest[:12]}.jpg"
            path = destination / filename
            destination.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_bytes(jpeg)
            archived.append(
                ArchivedImage(
                    source_url=candidate.source_url,
                    caption=candidate.caption,
                    image_type=candidate.image_type,
                    position=candidate.position,
                    local_path=path.as_posix(),
                    content_hash=digest,
                    saved_at=_now_iso(),
                )
            )
        except Exception as exc:
            errors.append(f"{candidate.caption}: {type(exc).__name__}: {exc}")

    return ArchiveResult(images=archived, errors=errors)
