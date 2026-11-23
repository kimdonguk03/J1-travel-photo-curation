#!/usr/bin/env python3
"""J-1 여행 사진 큐레이션: 10장 초안 선택 규칙과 비교용 베이스라인.

labeler.py와 evaluate.py가 이 파일을 불러 씁니다.

  py curation.py "C:\\Photos\\여행원본"                  # CLIP으로 6가지 방식 실행
  py curation.py "C:\\Photos\\여행원본" --embedder tiny   # 모델 없이 흐름만 점검 (보고용 아님)
  py curation.py "C:\\Photos\\여행원본" --embedder none   # CLIP이 필요 없는 방식만

원본 폴더에는 아무것도 쓰지 않습니다. 결과는 --work 폴더(기본 j1_out) 아래 앨범별 폴더에 저장합니다.

선택 규칙 (제안 방식 time_clip)
  1. 묶기: 촬영 시각 순으로 보면서, 최근 clip_window_sec 안에 찍힌 묶음 중
     CLIP 유사도가 clip_sim 이상인 묶음에 합칩니다. 없으면 새 묶음을 만듭니다.
     -> 바꿔 끼워도 되는 연사·재촬영만 한 묶음이 되고, 같은 해변의 단체사진과 바다 풍경은 따로 남습니다.
  2. 대표 컷: 묶음마다 가장 선명한 사진(라플라시안 분산 최대)을 고릅니다.
  3. 자리 배분: 하루(새벽 day_start_hour시 기준)마다 촬영 장수에 비례해 10자리를 나눕니다.
  4. 고르기: 중요도(묶음 크기 + 전후 N분 촬영량)가 높은 묶음부터 하나씩 고르되, 이미 고른 사진과
     같은 순간이거나(시간) 생김새가 비슷하면(CLIP) 감점합니다 (MMR: 점수 = 중요도 - lambda x 최대 유사도).

시간 방식(time)과 제안 방식(time_clip)은 묶기·다양성 두 곳에서만 다르고, 두 분리 실험 방식이
각각 한 곳씩만 CLIP을 씁니다. 그래서 CLIP이 어느 단계에서 도움이 됐는지 따로 볼 수 있습니다.
"""
from __future__ import annotations

import argparse
import base64
import dataclasses
import datetime as dt
import hashlib
import html
import io
import json
import math
import os
import random
import re
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

try:  # iPhone 원본(HEIC)
    import pillow_heif

    pillow_heif.register_heif_opener()
    HEIF_OK = True
except ImportError:
    HEIF_OK = False

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp"}

# ---------------------------------------------------------------------------
# 파라미터: 개발용 앨범에서만 조정하고, 평가 전에 params.json으로 고정하세요.
# ---------------------------------------------------------------------------
DEFAULT_PARAMS = {
    "k": 10,                    # 초안 장수
    "time_gap_sec": 30,         # 시간 묶음: 앞 사진과 간격이 이보다 크면 새 묶음
    "clip_window_sec": 120,     # 시간+CLIP 묶음: 이 시간 안에 찍힌 묶음만 합칠 후보
    "clip_sim": 0.92,           # 시간+CLIP 묶음: 코사인 유사도가 이 값 이상이면 같은 묶음
    "day_start_hour": 4,        # 새벽 4시 전 사진은 전날로 셈
    "importance": "both",       # size(묶음 크기) / density(전후 N분 촬영량) / both(둘의 평균)
    "density_window_min": 5,    # density에서 보는 전후 시간(분)
    "rep": "sharp",             # 묶음 대표 컷: sharp(가장 선명) / first / middle
    "lambda": 0.7,              # 다양성 감점 세기
    "time_tau_min": 30,         # 시간 다양성: 시각 차이가 이 척도보다 작을수록 크게 감점
    "clip_div_floor": 0.7,      # CLIP 다양성: 유사도가 이 값 이하면 감점 없음
    "random_seeds": 200,        # 무작위 방식 평균에 쓰는 시드 수 (evaluate.py)
}

METHODS = {
    "random": {"desc": "무작위 10장 (하한선)", "clip": False},
    "uniform": {"desc": "촬영 순서 균등 추출", "clip": False},
    "time": {"desc": "시간 묶음 + 시간 다양성", "group": "time", "div": "time", "clip": False},
    "time_clip": {"desc": "시간+CLIP 묶음 + 시간·CLIP 다양성 (제안)", "group": "time_clip", "div": "time+clip", "clip": True},
    "clip_group_only": {"desc": "[분리 실험] 시간+CLIP 묶음 + 시간 다양성", "group": "time_clip", "div": "time", "clip": True},
    "clip_div_only": {"desc": "[분리 실험] 시간 묶음 + 시간·CLIP 다양성", "group": "time", "div": "time+clip", "clip": True},
}

TIME_SOURCE_KO = {
    "original": "DateTimeOriginal",
    "exif_datetime": "EXIF DateTime(대체)",
    "file_mtime": "파일 수정 시각(대체)",
}


def load_params(path=None):
    params = dict(DEFAULT_PARAMS)
    if path:
        with open(path, encoding="utf-8") as f:
            user = json.load(f)
        unknown = set(user) - set(DEFAULT_PARAMS)
        if unknown:
            raise SystemExit(f"params 파일에 모르는 키가 있습니다: {sorted(unknown)}")
        params.update(user)
    if params["importance"] not in ("size", "density", "both"):
        raise SystemExit("importance는 size / density / both 중 하나여야 합니다.")
    if params["rep"] not in ("sharp", "first", "middle"):
        raise SystemExit("rep는 sharp / first / middle 중 하나여야 합니다.")
    return params


ENGINE_VERSION = "2026-11-23.2"  # 선택 규칙 코드를 바꾸면 올리세요. params_hash에 함께 들어갑니다.


def params_hash(params):
    """파라미터와 규칙·특징 버전의 지문. 평가 결과와 함께 보고하면 '평가 전에 고정했다'를 보일 수 있습니다."""
    blob = json.dumps({"params": params, "engine": ENGINE_VERSION, "features": FEATURE_VERSION}, sort_keys=True)
    return hashlib.sha1(blob.encode()).hexdigest()[:8]


# ---------------------------------------------------------------------------
# 앨범 읽기 (EXIF 촬영 시각)
# ---------------------------------------------------------------------------
@dataclasses.dataclass
class Photo:
    path: Path
    name: str            # 앨범 폴더 기준 상대 경로. 라벨 파일에서 사진 ID로 씁니다.
    local: dt.datetime   # 현지 벽시계 시각 (날짜 구분용)
    t: float             # 절대 시각(초). 촬영 간격 계산용
    time_source: str     # original / exif_datetime / file_mtime


@dataclasses.dataclass
class Album:
    root: Path
    photos: list
    failed: list         # [(name, 이유)]

    def drop(self, items):
        names = {n for n, _ in items}
        self.photos = [p for p in self.photos if p.name not in names]
        self.failed.extend(items)


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


def _subsec(v):
    s = _exif_str(v)
    return float("0." + s) if s and s.isdigit() else 0.0


_EPOCH = dt.datetime(1970, 1, 1)


def _system_offset(local):
    try:
        return local.astimezone().utcoffset().total_seconds()
    except (OSError, OverflowError, ValueError):
        return 0.0


def iter_image_files(root):
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS and not any(x.startswith(".") for x in rel.parts):
            yield p


def load_album(root):
    root = Path(root)
    if not root.is_dir():
        raise SystemExit(f"앨범 폴더가 없습니다: {root}")
    raw, failed = [], []
    for path in iter_image_files(root):
        name = path.relative_to(root).as_posix()
        if path.suffix.lower() in (".heic", ".heif") and not HEIF_OK:
            failed.append((name, "HEIC: pillow-heif 미설치"))
            continue
        try:
            with Image.open(path) as im:
                exif = im.getexif()
                ifd = exif.get_ifd(0x8769) if exif else {}
        except Exception as e:  # noqa: BLE001 - 어떤 이유든 이 사진만 건너뜀
            failed.append((name, f"열기 실패: {type(e).__name__}"))
            continue
        local = parse_exif_datetime(ifd.get(0x9003))           # DateTimeOriginal
        if local is not None:
            source, offset = "original", parse_exif_offset(ifd.get(0x9011))
            local += dt.timedelta(seconds=_subsec(ifd.get(0x9291)))  # 연사 순서용 1/100초
        else:
            local = parse_exif_datetime(exif.get(0x0132) if exif else None)  # DateTime
            source, offset = "exif_datetime", parse_exif_offset(ifd.get(0x9010))
        if local is None:
            mtime = path.stat().st_mtime
            raw.append((path, name, dt.datetime.fromtimestamp(mtime), "file_mtime", None, mtime))
        else:
            raw.append((path, name, local, source, offset, None))

    # 시간대 정보가 없는 사진은 앨범에서 가장 흔한 시간대(없으면 이 PC의 시간대)로 봅니다.
    known = Counter(r[4] for r in raw if r[4] is not None)
    default_offset = known.most_common(1)[0][0] if known else None
    photos = []
    for path, name, local, source, offset, mtime in raw:
        if mtime is not None:
            t = mtime
        else:
            off = offset if offset is not None else (default_offset if default_offset is not None else _system_offset(local))
            t = (local - _EPOCH).total_seconds() - off
        photos.append(Photo(path, name, local, t, source))
    photos.sort(key=lambda p: (p.t, p.name))
    return Album(root, photos, failed)


def day_key(local, start_hour):
    return (local - dt.timedelta(hours=start_hour)).date()


# ---------------------------------------------------------------------------
# 작업용 축소본: 원본은 한 번만 디코딩합니다
# ---------------------------------------------------------------------------
# 원본(특히 HEIC는 1장에 약 1초)을 448px로 한 번만 디코딩해 캐시하고, 선명도·임베딩·축소본은
# 모두 이 작업용 이미지에서 만듭니다. labeler.py와 curation.py가 같은 캐시를 함께 씁니다.
# 무손실(PNG)로 저장합니다. JPEG로 다시 압축하면 같은 사진의 CLIP 유사도가 0.95까지 떨어져
# 기준값 0.92 근처의 판정이 흔들리는 것을 확인했습니다.
WORK_SIDE = 448     # 긴 변. 휴대폰 JPEG(4032px)를 1/8 배율로 바로 디코딩할 수 있는 크기
FEATURE_VERSION = 4  # 특징 계산 방식을 바꾸면 올리세요 (캐시 이름과 params_hash에 들어감)
DECODE_WORKERS = min(4, os.cpu_count() or 1)


def open_rgb(path, max_side=WORK_SIDE):
    with Image.open(path) as im:
        w, h = im.size
        s = max_side / max(w, h)
        if s < 1:
            try:  # JPEG는 축소 디코딩으로 빠르게 (요청 크기보다 작아지지 않는 가장 작은 배율)
                im.draft("RGB", (max(1, int(w * s)), max(1, int(h * s))))
            except Exception:  # noqa: BLE001
                pass
        im = ImageOps.exif_transpose(im).convert("RGB")
    im.thumbnail((max_side, max_side), Image.Resampling.BICUBIC)
    return im


def _file_sig(path):
    st = path.stat()
    return f"{st.st_size}:{st.st_mtime_ns}"


def work_image_path(cache_dir, photo):
    key = hashlib.sha1(f"{photo.name}|{_file_sig(photo.path)}".encode("utf-8")).hexdigest()[:20]
    return Path(cache_dir) / "work" / f"{key}.png"


def ensure_work_images(album, cache_dir, workers=DECODE_WORKERS, log=print):
    """작업용 축소본이 없는 사진만 원본을 디코딩해 만듭니다(병렬). 디코딩 실패한 사진은 앨범에서 뺍니다."""
    todo = [p for p in album.photos if not work_image_path(cache_dir, p).exists()]
    if not todo:
        return

    def job(p):
        try:
            im = open_rgb(p.path, WORK_SIDE)
            out = work_image_path(cache_dir, p)
            out.parent.mkdir(parents=True, exist_ok=True)
            tmp = out.with_suffix(".part")
            im.save(tmp, "PNG", compress_level=3)
            tmp.replace(out)
            return p.name, None
        except Exception as e:  # noqa: BLE001 - 이 사진만 건너뜀
            return p.name, f"디코딩 실패: {type(e).__name__}"

    bad = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for k, (name, err) in enumerate(ex.map(job, todo), 1):
            if err:
                bad.append((name, err))
            if len(todo) > 20 and (k % 20 == 0 or k == len(todo)):
                log(f"  원본 디코딩 {k}/{len(todo)}", end="\r" if k < len(todo) else "\n")
    if bad:
        album.drop(bad)


def load_work_image(cache_dir, photo):
    with Image.open(work_image_path(cache_dir, photo)) as im:
        return im.convert("RGB")


def sharpness(im):
    """라플라시안 분산. 클수록 선명합니다 (흔들림·초점 나감 감지용)."""
    g = np.asarray(im.convert("L"), dtype=np.float32)
    if g.shape[0] < 3 or g.shape[1] < 3:
        return 0.0
    lap = -4 * g[1:-1, 1:-1] + g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:]
    return float(lap.var())


def image_data_uri(im, max_side=220, quality=72):
    im = im.copy()
    im.thumbnail((max_side, max_side), Image.Resampling.BICUBIC)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _center_square(im):
    w, h = im.size
    s = min(w, h)
    left, top = (w - s) // 2, (h - s) // 2
    return im.crop((left, top, left + s, top + s))


class TinyEmbedder:
    """16x16 축소 이미지를 벡터로 씁니다. 모델 없이 흐름을 점검하는 용도이며 결과 보고에 쓰면 안 됩니다."""

    name = "tiny"

    def embed(self, ims):
        out = []
        for im in ims:
            v = np.asarray(_center_square(im).resize((16, 16), Image.Resampling.BILINEAR), np.float32).ravel() / 255
            v = v - v.mean()
            out.append(v / (np.linalg.norm(v) + 1e-8))
        return np.stack(out)


CLIP_MEAN = np.array([0.48145466, 0.4578275, 0.40821073], np.float32)
CLIP_STD = np.array([0.26862954, 0.26130258, 0.27577711], np.float32)
CLIP_REPO = "Xenova/clip-vit-base-patch32"
CLIP_FILES = ("onnx/vision_model_quantized.onnx", "onnx/vision_model_int8.onnx", "onnx/vision_model.onnx")


class ClipOnnxEmbedder:
    """CLIP ViT-B/32 이미지 인코더(ONNX). --clip-model로 이미 받은 .onnx 파일을 지정할 수 있습니다."""

    def __init__(self, model_path=None):
        try:
            import onnxruntime as ort
        except ImportError:
            raise SystemExit("CLIP을 쓰려면: py -m pip install onnxruntime huggingface-hub  (또는 --embedder none)")
        if model_path is None:
            try:
                from huggingface_hub import hf_hub_download
            except ImportError:
                raise SystemExit("모델을 받으려면: py -m pip install huggingface-hub  (또는 --clip-model 경로 지정)")
            last = None
            for fname in CLIP_FILES:
                try:
                    model_path = hf_hub_download(CLIP_REPO, fname)
                    break
                except Exception as e:  # noqa: BLE001 - 다음 후보 파일 시도
                    last = e
            else:
                raise SystemExit(f"CLIP 모델을 받지 못했습니다: {last}")
        self.name = "clip_" + Path(model_path).stem
        self.sess = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
        inputs = self.sess.get_inputs()
        self.input_name = next((i.name for i in inputs if "pixel" in i.name), inputs[0].name)
        outs = [o.name for o in self.sess.get_outputs()]
        self.output_name = next((n for n in ("image_embeds", "pooler_output") if n in outs), outs[0])

    @staticmethod
    def preprocess(im):
        w, h = im.size
        s = 224 / min(w, h)
        im = im.resize((max(224, round(w * s)), max(224, round(h * s))), Image.Resampling.BICUBIC)
        im = _center_square(im).resize((224, 224), Image.Resampling.BICUBIC)
        a = (np.asarray(im, np.float32) / 255.0 - CLIP_MEAN) / CLIP_STD
        return a.transpose(2, 0, 1)

    def _run(self, x):
        y = self.sess.run([self.output_name], {self.input_name: x})[0]
        return y[:, 0, :] if y.ndim == 3 else y

    def embed(self, ims):
        x = np.stack([self.preprocess(i) for i in ims]).astype(np.float32)
        try:
            y = self._run(x)
        except Exception:  # noqa: BLE001 - 배치 크기 1로 고정된 모델 대비
            y = np.concatenate([self._run(x[i:i + 1]) for i in range(len(x))])
        return y / np.linalg.norm(y, axis=1, keepdims=True)


def make_embedder(kind, clip_model=None):
    if kind == "none":
        return None
    if kind == "tiny":
        return TinyEmbedder()
    return ClipOnnxEmbedder(clip_model)


def compute_features(album, embedder, cache_dir, batch=16, log=print):
    """선명도와 임베딩을 계산합니다(캐시 사용). 디코딩에 실패한 사진은 앨범에서 뺍니다."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    ensure_work_images(album, cache_dir, log=log)
    tag = embedder.name if embedder else "none"
    cache_file = cache_dir / f"features_v{FEATURE_VERSION}_{re.sub(r'[^A-Za-z0-9_.-]+', '_', tag)}.npz"
    cached = {}
    if cache_file.exists():
        try:
            z = np.load(cache_file, allow_pickle=False)
            for i, n in enumerate(z["names"]):
                cached[str(n)] = (str(z["sigs"][i]), float(z["sharp"][i]), z["emb"][i])
        except Exception:  # noqa: BLE001 - 캐시가 깨졌으면 새로 계산
            cached = {}
    sigs = {p.name: _file_sig(p.path) for p in album.photos}
    sharp, emb = {}, {}
    todo = []
    for p in album.photos:
        c = cached.get(p.name)
        if c and c[0] == sigs[p.name]:
            sharp[p.name], emb[p.name] = c[1], c[2]
        else:
            todo.append(p)
    for start in range(0, len(todo), batch):
        chunk = todo[start:start + batch]
        ims = [load_work_image(cache_dir, p) for p in chunk]
        for p, im in zip(chunk, ims):
            sharp[p.name] = sharpness(im)
        if embedder:
            for p, v in zip(chunk, embedder.embed(ims)):
                emb[p.name] = v
        done = min(start + batch, len(todo))
        if len(todo) > batch:
            log(f"  특징 계산 {done}/{len(todo)}", end="\r" if done < len(todo) else "\n")
    names = [p.name for p in album.photos]
    if embedder:
        E = np.stack([emb[n] for n in names]).astype(np.float32) if names else np.zeros((0, 1), np.float32)
    else:
        E = np.zeros((len(names), 0), np.float32)
    S = np.array([sharp[n] for n in names], np.float64)
    np.savez(cache_file, names=np.array(names, dtype=str), sigs=np.array([sigs[n] for n in names], dtype=str),
             sharp=S, emb=E)
    return S, (E if embedder else None)


# ---------------------------------------------------------------------------
# 묶기
# ---------------------------------------------------------------------------
def group_by_time(times, gap_sec):
    """시간순으로 보며 앞 사진과 간격이 gap_sec보다 크면 새 묶음."""
    if len(times) == 0:
        return []
    groups = [[0]]
    for i in range(1, len(times)):
        if times[i] - times[i - 1] > gap_sec:
            groups.append([i])
        else:
            groups[-1].append(i)
    return groups


def group_by_time_clip(times, emb, window_sec, sim_th):
    """최근 window_sec 안에 사진이 추가된 묶음 중 가장 비슷한 묶음(멤버와의 최대 유사도)에 합칩니다.

    단체사진-풍경-단체사진처럼 섞여 찍혀도 단체사진끼리 다시 모이고, 풍경은 따로 남습니다.
    """
    groups, last_t, active = [], [], []
    for i, t in enumerate(times):
        active = [g for g in active if t - last_t[g] <= window_sec]
        best, best_s = None, -2.0
        for g in active:
            s = float(np.max(emb[groups[g]] @ emb[i]))
            if s > best_s:
                best, best_s = g, s
        if best is not None and best_s >= sim_th:
            groups[best].append(i)
            last_t[best] = t
        else:
            groups.append([i])
            last_t.append(t)
            active.append(len(groups) - 1)
    return groups


def pick_rep(members, sharp, mode):
    if mode == "first":
        return members[0]
    if mode == "middle":
        return members[len(members) // 2]
    return max(members, key=lambda i: (sharp[i], -i))


# ---------------------------------------------------------------------------
# 고르기
# ---------------------------------------------------------------------------
def group_importance(groups, times, mode, window_sec):
    """0~1. size: 같은 장면을 몇 번 다시 찍었나 / density: 그 무렵 얼마나 많이 찍었나."""
    def norm(x):
        m = x.max() if len(x) else 0
        return x / m if m > 0 else x

    size = norm(np.log1p(np.array([len(g) for g in groups], float)))
    if mode == "size":
        return size
    dens = []
    for g in groups:
        lo, hi = times[g].min() - window_sec, times[g].max() + window_sec
        dens.append(np.searchsorted(times, hi, side="right") - np.searchsorted(times, lo, side="left"))
    dens = norm(np.log1p(np.array(dens, float)))
    return dens if mode == "density" else (size + dens) / 2


def allocate_slots(day_counts, k):
    """날짜별 촬영 장수에 비례해 k자리를 나눕니다(최대 잔여 방식)."""
    total = sum(day_counts.values())
    if total == 0:
        return {}
    raw = {d: k * c / total for d, c in day_counts.items()}
    q = {d: int(math.floor(v)) for d, v in raw.items()}
    for d in sorted(raw, key=lambda d: (-(raw[d] - q[d]), -day_counts[d], d))[: k - sum(q.values())]:
        q[d] += 1
    return q


def mmr_select(reps, imp, gday, quotas, sim, k, lam):
    """자리가 남은 날의 묶음 중 (중요도 - lam x 이미 고른 사진과의 최대 유사도)가 큰 것부터 고릅니다."""
    remaining = dict(quotas)
    alive = list(range(len(reps)))
    maxsim = [0.0] * len(reps)
    chosen = []
    while alive and len(chosen) < k:
        eligible = [g for g in alive if remaining.get(gday[g], 0) > 0] or alive
        best = max(eligible, key=lambda g: (imp[g] - lam * maxsim[g], imp[g], -reps[g]))
        chosen.append(best)
        alive.remove(best)
        remaining[gday[best]] = remaining.get(gday[best], 0) - 1
        for g in alive:
            maxsim[g] = max(maxsim[g], sim(reps[g], reps[best]))
    return chosen


class Engine:
    def __init__(self, album, sharp, emb, params):
        self.album = album
        self.photos = album.photos
        self.sharp = sharp
        self.emb = emb
        self.p = params
        self.times = np.array([p.t for p in self.photos], float)
        self.days = [day_key(p.local, params["day_start_hour"]) for p in self.photos]
        self.day_index = {d: i + 1 for i, d in enumerate(sorted(set(self.days)))}
        self._groups = {}

    def day_label(self, i):
        return f"D{self.day_index[self.days[i]]}"

    def groups(self, kind):
        if kind not in self._groups:
            if kind == "time":
                g = group_by_time(self.times, self.p["time_gap_sec"])
            elif kind == "time_clip":
                g = group_by_time_clip(self.times, self.emb, self.p["clip_window_sec"], self.p["clip_sim"])
            else:
                raise ValueError(kind)
            self._groups[kind] = sorted(g, key=lambda m: m[0])
        return self._groups[kind]

    def similarity(self, kind, a, b):
        """time: 같은 순간일수록 1 / time+clip: 같은 순간이거나 생김새가 비슷하면(다른 날의 비슷한 해변 등) 1"""
        t = math.exp(-abs(self.times[a] - self.times[b]) / (60 * self.p["time_tau_min"]))
        if kind == "time":
            return t
        floor = self.p["clip_div_floor"]
        return max(t, (float(self.emb[a] @ self.emb[b]) - floor) / (1 - floor))

    def run(self, method, seed=0):
        """{"picks": 사진 인덱스(시간순), "detail": 사진별 설명}"""
        spec = METHODS[method]
        if spec["clip"] and self.emb is None:
            raise SystemExit(f"{method}는 임베딩이 필요합니다 (--embedder clip).")
        n, k = len(self.photos), self.p["k"]
        if method == "random":
            picks = sorted(random.Random(seed).sample(range(n), min(k, n)))
            return {"picks": picks, "detail": [{} for _ in picks]}
        if method == "uniform":
            picks = list(range(n)) if n <= k else [int((j + 0.5) * n / k) for j in range(k)]
            return {"picks": picks, "detail": [{} for _ in picks]}
        groups = self.groups(spec["group"])
        reps = [pick_rep(g, self.sharp, self.p["rep"]) for g in groups]
        imp = group_importance(groups, self.times, self.p["importance"], 60 * self.p["density_window_min"])
        gday = [self.days[r] for r in reps]
        quotas = allocate_slots(Counter(self.days), k)
        div = spec["div"]
        chosen = mmr_select(reps, imp, gday, quotas, lambda a, b: self.similarity(div, a, b), k, self.p["lambda"])
        chosen.sort(key=lambda g: reps[g])
        return {
            "picks": [reps[g] for g in chosen],
            "detail": [{"group_size": len(groups[g]), "importance": round(float(imp[g]), 3)} for g in chosen],
        }

    def groups_json(self, kind):
        out = []
        for g in self.groups(kind):
            r = pick_rep(g, self.sharp, self.p["rep"])
            out.append({
                "rep": self.photos[r].name,
                "members": [self.photos[i].name for i in g],
                "day": self.day_label(r),
                "start": self.photos[g[0]].local.isoformat(timespec="seconds"),
                "end": self.photos[g[-1]].local.isoformat(timespec="seconds"),
            })
        return out


def available_methods(has_emb, wanted="all"):
    names = list(METHODS) if wanted == "all" else [m.strip() for m in wanted.split(",") if m.strip()]
    for m in names:
        if m not in METHODS:
            raise SystemExit(f"모르는 방식: {m} (가능: {', '.join(METHODS)})")
    return [m for m in names if has_emb or not METHODS[m]["clip"]]


# ---------------------------------------------------------------------------
# 공통 실행 준비
# ---------------------------------------------------------------------------
def album_work_dir(work, root):
    root = Path(root).resolve()
    base = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", root.name) or "album"
    return Path(work) / f"{base}_{hashlib.sha1(str(root).encode('utf-8')).hexdigest()[:6]}"


def add_common_args(ap):
    ap.add_argument("--embedder", choices=["clip", "tiny", "none"], default="clip",
                    help="clip: CLIP ViT-B/32 (기본) / tiny: 모델 없는 흐름 점검용 / none: CLIP 방식 제외")
    ap.add_argument("--clip-model", help="이미 받은 CLIP 이미지 인코더 .onnx 경로 (없으면 Hugging Face에서 받음)")
    ap.add_argument("--params", help="파라미터 JSON (기본값은 curation.py의 DEFAULT_PARAMS)")
    ap.add_argument("--work", default="j1_out", help="결과·캐시 폴더 (기본 j1_out)")


def build_engine(album_dir, embedder_kind, params_path, work, clip_model=None, log=print):
    params = load_params(params_path)
    album = load_album(album_dir)
    if not album.photos:
        raise SystemExit("읽을 수 있는 사진이 없습니다.")
    out_dir = album_work_dir(work, album.root)
    embedder = make_embedder(embedder_kind, clip_model)
    if embedder_kind == "tiny":
        log("! tiny 임베딩은 흐름 점검용입니다. 이 결과를 발표·논문 수치로 쓰지 마세요.")
    sharp, emb = compute_features(album, embedder, out_dir, log=log)
    return Engine(album, sharp, emb, params), out_dir, (embedder.name if embedder else "none")


def summarize(engine):
    a = engine.album
    src = Counter(p.time_source for p in a.photos)
    lines = [f"사진 {len(a.photos)}장 읽음, 실패 {len(a.failed)}장"]
    lines += [f"  - {n}: {why}" for n, why in a.failed[:5]]
    if len(a.failed) > 5:
        lines.append(f"  - ... 외 {len(a.failed) - 5}장")
    lines.append("촬영 시각 출처: " + ", ".join(f"{v} {src.get(k, 0)}장" for k, v in TIME_SOURCE_KO.items()))
    if src.get("file_mtime"):
        lines.append("  ! 파일 수정 시각은 사진을 옮긴 시각일 수 있어 순서를 믿기 어렵습니다.")
    days = Counter(engine.days)
    lines.append("날짜별: " + ", ".join(f"D{engine.day_index[d]}({d:%m/%d}) {c}장" for d, c in sorted(days.items())))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 비교 HTML
# ---------------------------------------------------------------------------
PAGE_CSS = """
:root{--bg:#f7f7f5;--fg:#1d1d1b;--muted:#6a6a64;--card:#fff;--line:#e2e2dd;--accent:#b45309}
@media (prefers-color-scheme:dark){:root{--bg:#151514;--fg:#ebebe8;--muted:#9b9b94;--card:#1f1f1d;--line:#33332f;--accent:#f59e0b}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,"Malgun Gothic",sans-serif}
main{max-width:1400px;margin:0 auto;padding:16px}h1{font-size:20px;margin:0 0 4px}
.meta{color:var(--muted);margin:0 0 16px;white-space:pre-wrap}.warn{color:var(--accent);font-weight:600}
section{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px;margin:0 0 14px}
h2{font-size:15px;margin:0 0 8px}h2 span{color:var(--muted);font-weight:400;margin-left:6px}
.row{display:flex;gap:8px;overflow-x:auto;padding-bottom:4px}
figure{margin:0;flex:0 0 auto;width:150px}figure img{width:150px;height:150px;object-fit:cover;border-radius:6px;display:block}
figcaption{font-size:12px;color:var(--muted);margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
"""


def write_compare_html(engine, results, out_dir, embedder_name, phash):
    thumbs = {}
    sections = []
    for m, r in results.items():
        cells = []
        for i, d in zip(r["picks"], r["detail"]):
            if i not in thumbs:
                thumbs[i] = image_data_uri(load_work_image(out_dir, engine.photos[i]), 300)
            p = engine.photos[i]
            cap = f"{engine.day_label(i)} {p.local:%H:%M}" + (f" · 묶음 {d['group_size']}장" if "group_size" in d else "")
            cells.append(f'<figure><img src="{thumbs[i]}" alt="{html.escape(p.name)}" loading="lazy">'
                         f'<figcaption title="{html.escape(p.name)}">{html.escape(cap)}</figcaption></figure>')
        sections.append(f'<section><h2>{html.escape(m)}<span>{html.escape(METHODS[m]["desc"])}</span></h2>'
                        f'<div class="row">{"".join(cells)}</div></section>')
    title = f"초안 비교 · {engine.album.root.name}"
    meta = f"임베딩 {embedder_name} · 파라미터 {phash} · 사진 {len(engine.photos)}장"
    page = (f'<!doctype html><html lang="ko"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title>'
            f'<style>{PAGE_CSS}</style></head><body><main><h1>{html.escape(title)}</h1>'
            f'<p class="meta">{html.escape(meta)}\n<span class="warn">앨범 주인이 정답(labeler.py)을 표시하기 전에는 이 화면을 보여주지 마세요.</span></p>'
            f'{"".join(sections)}</main></body></html>')
    out_path = out_dir / "compare.html"
    out_path.write_text(page, encoding="utf-8")
    return out_path


def main(argv=None):
    ap = argparse.ArgumentParser(description="J-1 초안 10장 선택: 여러 방식을 실행하고 비교 HTML을 만듭니다.")
    ap.add_argument("album", help="미선별 원본 사진 폴더")
    add_common_args(ap)
    ap.add_argument("--methods", default="all", help=f"쉼표로 구분 (기본 all: {','.join(METHODS)})")
    args = ap.parse_args(argv)

    engine, out_dir, emb_name = build_engine(args.album, args.embedder, args.params, args.work, args.clip_model)
    print(summarize(engine))
    methods = available_methods(engine.emb is not None, args.methods)
    results = {m: engine.run(m) for m in methods}
    phash = params_hash(engine.p)

    for kind in ("time", "time_clip"):
        if kind in engine._groups:
            print(f"묶음 수 ({kind}): {len(engine._groups[kind])}개")
            (out_dir / f"groups_{kind}.json").write_text(
                json.dumps(engine.groups_json(kind), ensure_ascii=False, indent=1), encoding="utf-8")

    picks = {
        "album": str(engine.album.root), "embedder": emb_name, "params": engine.p, "params_hash": phash,
        "methods": {m: {"desc": METHODS[m]["desc"],
                        "picks": [engine.photos[i].name for i in r["picks"]], "detail": r["detail"]}
                    for m, r in results.items()},
    }
    (out_dir / "picks.json").write_text(json.dumps(picks, ensure_ascii=False, indent=1), encoding="utf-8")
    html_path = write_compare_html(engine, results, out_dir, emb_name, phash)

    for m, r in results.items():
        if len(r["picks"]) < engine.p["k"]:
            print(f"! {m}: 후보가 부족해 {len(r['picks'])}장만 골랐습니다.")
    print(f"\n결과: {out_dir.resolve()}")
    print(f"  비교 화면: {html_path.resolve()}")
    print("  picks.json(방식별 10장), groups_*.json(묶음 목록, 이후 '빠진 장면' UI용)")


if __name__ == "__main__":
    sys.exit(main())
