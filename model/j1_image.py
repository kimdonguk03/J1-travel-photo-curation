"""공통 이미지 읽기 함수: 폴더 스캔, 촬영 시각, 정방향 이미지, 썸네일.

    from j1_image import scan_folder, read_taken_at, open_upright, jpeg_bytes

- scan_folder(root): 하위 폴더까지 지원 사진을 찾고 동영상(MOV·MP4) 수와 읽기 실패를 따로 셉니다.
  확장자는 대소문자를 구분하지 않고, 그 밖의 파일은 세지 않습니다.
- read_taken_at(path): EXIF DateTimeOriginal을 ISO 8601 문자열로 돌려줍니다. 없으면 None(촬영 시각 미상).
- open_upright(path, max_side): 회전을 한 번만 적용한 정방향 RGB 이미지. 비율을 유지해 긴 변을
  max_side 이하로 줄이고, 작은 사진은 키우지 않습니다. HEIC는 pillow-heif가 열 때 회전을 적용합니다.
- jpeg_bytes(path, max_side): 목록 썸네일(512)·큰 미리보기(1600)용 컬러 JPEG. EXIF를 넣지 않으므로
  브라우저가 회전을 다시 적용하지 않습니다.
"""
from __future__ import annotations

import datetime as dt
import io
import re
from pathlib import Path

from PIL import Image, ImageOps

try:  # 아이폰 원본(HEIC)
    import pillow_heif

    pillow_heif.register_heif_opener()
    HEIF_OK = True
except ImportError:
    HEIF_OK = False

PHOTO_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp"}
VIDEO_EXTS = {".mov", ".mp4"}
THUMB_SIDE = 512     # 목록 썸네일 긴 변
PREVIEW_SIDE = 1600  # 큰 미리보기 긴 변


# ---------------------------------------------------------------------------
# 폴더 읽기
# ---------------------------------------------------------------------------
def scan_folder(root):
    """(photos, video_count, failed)를 돌려줍니다.

    photos: [{"relpath": "하위/IMG_0001.HEIC", "path": Path}] (상대 경로 구분자는 /, 정렬됨)
    failed: [(relpath, 이유)]. 헤더를 열 수 없는 사진입니다. 디코딩 실패는 open_upright에서 드러납니다.
    """
    root = Path(root)
    if not root.is_dir():
        raise FileNotFoundError(f"폴더를 열 수 없습니다: {root}")
    photos, failed, videos = [], [], 0
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if not p.is_file() or any(part.startswith(".") for part in rel.parts):
            continue
        ext = p.suffix.lower()
        if ext in VIDEO_EXTS:
            videos += 1
            continue
        if ext not in PHOTO_EXTS:
            continue
        relpath = rel.as_posix()
        if ext in (".heic", ".heif") and not HEIF_OK:
            failed.append((relpath, "HEIC 디코더(pillow-heif) 미설치"))
            continue
        try:
            with Image.open(p):
                pass
        except Exception as e:  # noqa: BLE001 - 어떤 이유든 이 사진만 실패로 셈
            failed.append((relpath, f"열기 실패: {type(e).__name__}"))
            continue
        photos.append({"relpath": relpath, "path": p})
    return photos, videos, failed


# ---------------------------------------------------------------------------
# 촬영 시각
# ---------------------------------------------------------------------------
def _exif_str(v):
    if v is None:
        return None
    if isinstance(v, bytes):
        v = v.decode("ascii", "ignore")
    v = str(v).strip().strip("\x00").strip()
    return v or None


def parse_exif_datetime(v):
    s = _exif_str(v)
    if not s:
        return None
    try:
        return dt.datetime.strptime(s[:19], "%Y:%m:%d %H:%M:%S")
    except ValueError:  # "0000:00:00 00:00:00" 같은 빈 값
        return None


def parse_exif_offset(v):
    """"+09:00" -> 32400초"""
    s = _exif_str(v)
    if not s:
        return None
    m = re.fullmatch(r"([+-])(\d{1,2}):?(\d{2})", s)
    if not m:
        return None
    sec = int(m.group(2)) * 3600 + int(m.group(3)) * 60
    return -sec if m.group(1) == "-" else sec


def read_taken_at(path):
    """DateTimeOriginal(+ 1/100초, 시간대)을 "2026-10-01T14:03:22.370+09:00" 형식으로. 없으면 None.

    촬영 시각을 확인할 수 없으면 미상(None)입니다. EXIF DateTime이나 파일 수정 시각으로 대신하지 않습니다.
    """
    try:
        with Image.open(path) as im:
            exif = im.getexif()
            ifd = exif.get_ifd(0x8769) if exif else {}
    except Exception:  # noqa: BLE001
        return None
    local = parse_exif_datetime(ifd.get(0x9003))
    if local is None:
        return None
    sub = _exif_str(ifd.get(0x9291))
    if sub and sub.isdigit():
        local += dt.timedelta(seconds=float("0." + sub))
    off = parse_exif_offset(ifd.get(0x9011))
    if off is not None:
        local = local.replace(tzinfo=dt.timezone(dt.timedelta(seconds=off)))
    return local.isoformat(timespec="milliseconds")


def parse_taken_at(s):
    """read_taken_at 문자열 -> (현지 벽시계 시각(naive), 시간대 초 또는 None). None이면 (None, None)."""
    if not s:
        return None, None
    d = dt.datetime.fromisoformat(s)
    if d.tzinfo is None:
        return d, None
    return d.replace(tzinfo=None), int(d.utcoffset().total_seconds())


# ---------------------------------------------------------------------------
# 정방향 이미지
# ---------------------------------------------------------------------------
def open_upright(path, max_side=THUMB_SIDE):
    """회전을 한 번만 적용한 정방향 RGB. 긴 변을 max_side 이하로 줄이고 작은 사진은 키우지 않습니다."""
    with Image.open(path) as im:
        w, h = im.size
        s = max_side / max(w, h)
        if s < 1:
            try:  # JPEG는 축소 디코딩 (요청 크기보다 작아지지 않는 가장 작은 배율)
                im.draft("RGB", (max(1, int(w * s)), max(1, int(h * s))))
            except Exception:  # noqa: BLE001
                pass
        im = ImageOps.exif_transpose(im).convert("RGB")
    im.thumbnail((max_side, max_side), Image.Resampling.BICUBIC)
    return im


def jpeg_bytes(path, max_side=THUMB_SIDE, quality=85):
    """목록 썸네일·큰 미리보기용 정방향 컬러 JPEG(바이트)."""
    buf = io.BytesIO()
    open_upright(path, max_side).save(buf, "JPEG", quality=quality, optimize=True)
    return buf.getvalue()
