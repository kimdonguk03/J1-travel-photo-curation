#!/usr/bin/env python3
"""J-1 추천 모듈.

    from recommend import recommend
    result = recommend(photos, k)
    # photos: [{"photo_id", "relpath", "path", "taken_at"}]
    #         taken_at은 j1_image.read_taken_at 값(미상이면 None), path는 서버 내부의 원본 위치
    # result: {"clusters": [{"cluster_id", "photo_ids", "representative_id"}], "draft_ids": [...], "rule_version": "..."}
    #         photo_ids는 묶음 안 순위순(첫 번째 = representative_id)
    #         draft_ids는 촬영순(미상은 끝)이며 중복 없이 정확히 k장

명령줄 (React 없이 확인):
    py recommend.py --folder "C:\\Photos\\trip"        # 폴더를 읽어 photo_id = 상대 경로로 실행
    py recommend.py photos.json --out result.json      # 사진 목록 JSON으로 실행

규칙 (값은 DEFAULT_PARAMS, params.json으로 바꿀 수 있음)
  1. 시간 구간: 촬영순으로 직전 컷과 30초, 구간 첫 컷부터 120초 한도. 넘거나 날짜가 바뀌면 새 구간.
     촬영 시각 미상은 단독 후보.
  2. 유사 컷: 같은 구간에서 각 묶음의 첫 컷(기준 컷, 고정)과 비교해 0.92 이상인 묶음 중 가장 높은 곳에
     넣습니다. 없으면 새 묶음, 동점이면 먼저 만든 묶음.
  3. 내용 점수: 사진의 CLIP 벡터를 문장 15개(content_prompts.npz)와 비교해, 앨범 안에서 표준화한 뒤
     '보여줄 만한 내용'(사람·단체·관광지·풍경·야경·음식·카페) 평균에서 '빼고 싶은 내용'(도로·바닥·문서·
     스크린샷·흐림·평범) 평균을 뺍니다. 가중치는 학습하지 않고 모두 같습니다.
  4. 대표 컷: 묶음 안에서 내용 점수가 높은 순, 동점은 선명도(긴 변 512px 흑백 라플라시안 분산), 촬영순.
  5. 고르기: 관련도 = (1-w) x min(사진 수, 5)/5 + w x 대표 컷의 내용 점수(앨범 안 0~1), w=0.5.
     MMR = (1-λ) x 관련도 - λ x (지금까지 고른 대표 컷과의 최대 코사인 유사도), λ=0.5.
     묶음이 K개 이상이면 ① 날짜마다 MMR 1위 1장(날짜 수 D>K면 floor((j+0.5)D/K)번째 날짜만)
     ② √사진 수/(배정 수+1)이 가장 큰 구간에 1장씩(미상은 ②부터). 묶음이 K개 미만이면 모든 대표 컷 뒤에
     묶음별 2위, 3위를 첫 컷 촬영순으로 돌아가며 채웁니다.
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import hashlib
import json
import math
import os
import random
import re
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image

import j1_image as J

# ---------------------------------------------------------------------------
# 파라미터와 규칙 버전
# ---------------------------------------------------------------------------
DEFAULT_PARAMS = {
    "seg_gap_sec": 30,      # 직전 컷과의 간격이 이보다 크면 새 시간 구간
    "seg_span_sec": 120,    # 구간 첫 컷과의 간격이 이보다 크면 새 시간 구간
    "clip_sim": 0.92,       # 묶음 기준 컷과의 코사인 유사도가 이 값 이상이면 같은 묶음
    "lambda": 0.5,          # MMR: (1-λ) x 크기 점수 - λ x 중복도
    "size_cap": 5,          # 크기 점수 = min(사진 수, size_cap) / size_cap
    "day_start_hour": 0,    # 날짜 경계 시각 (0 = 자정)
    "size_weight": 1.0,     # 관련도 = 크기·내용·화질 점수의 가중 평균. 이 셋이 각 점수의 비중입니다
    "content_weight": 1.0,  #   내용 점수 비중 (0이면 내용 점수를 쓰지 않음)
    "quality_weight": 1.0,  #   화질 점수 비중 (0이면 선명도는 묶음 안 대표 컷 고르기에만 씀)
    "aesthetic_weight": 1.0,  # 미적 점수 비중 (LAION 미적 점수 모델, 0이면 쓰지 않음)
    "rank_model": "clip",  # 묶음 안 대표 컷: triage_ranker.npz의 학습 모델 small·prompts·clip, 또는 sharpness(선명도)
    "random_seeds": 200,    # 평가에서 무작위 기준선을 평균 낼 시드 수
}
ENGINE_VERSION = "r4"  # 규칙 코드를 바꾸면 올리세요 (r2: 내용 점수, r3: 흔들림에 강한 선명도와 화질 점수, r4: 미적 점수)
CONTENT_FILE = Path(__file__).with_name("content_prompts.npz")
AESTHETIC_FILE = Path(__file__).with_name("aesthetic_vit_b_32.npz")  # LAION-Aesthetics V1 선형층 (MIT)
RANKER_FILE = Path(__file__).with_name("triage_ranker.npz")  # Photo Triage로 학습한 대표 컷 순위 모델 (triage_eval.py)
RANK_MODELS = ("small", "prompts", "clip")
FEATURE_VERSION = 6           # 특징 계산(축소·선명도·CLIP 입력)을 바꾸면 올리세요
RANK_SIDE = 512               # 대표 컷 순위와 CLIP 입력에 쓰는 정방향 축소본의 긴 변
DECODE_WORKERS = min(4, os.cpu_count() or 1)
DEFAULT_CACHE = Path("j1_out") / "cache"

METHODS = {
    "random": "무작위 K장 (참고용 하한선)",
    "uniform": "촬영 순번 균등 추출 (기준선)",
    "time": "시간 묶기 + 같은 선택 규칙 (비교 조건)",
    "time_clip": "시간+CLIP 묶기 + 선택 규칙 (제안, recommend 기본값)",
}
NEEDS_EMBEDDING = {"time", "time_clip"}


def load_params(path_or_dict=None):
    params = dict(DEFAULT_PARAMS)
    if isinstance(path_or_dict, dict):
        user = path_or_dict
    elif path_or_dict:
        with open(path_or_dict, encoding="utf-8") as f:
            user = json.load(f)
    else:
        user = {}
    unknown = set(user) - set(DEFAULT_PARAMS)
    if unknown:
        raise ValueError(f"모르는 파라미터: {sorted(unknown)}")
    params.update(user)
    return params


def rule_version(params, embedder_name):
    """규칙 코드·특징 계산·파라미터·모델·문장 벡터의 지문. 세션 로그와 발표 수치에 함께 남깁니다."""
    rule_params = {k: v for k, v in params.items() if k != "random_seeds"}
    cp = load_content_prompts()
    content = hashlib.sha1(cp[1].tobytes() + cp[2].tobytes()).hexdigest()[:8] if cp else "none"
    ah = load_aesthetic_head()
    aes = hashlib.sha1(ah[0].tobytes() + np.float32(ah[1]).tobytes()).hexdigest()[:8] if ah else "none"
    rk = params.get("rank_model", "sharpness")
    ranker = "none"
    if rk != "sharpness":
        r = load_ranker(rk)
        ranker = hashlib.sha1(r[0].tobytes() + r[1].tobytes()).hexdigest()[:8]
    blob = json.dumps({"p": rule_params, "e": ENGINE_VERSION, "f": FEATURE_VERSION, "m": embedder_name,
                       "c": content, "a": aes, "r": ranker}, sort_keys=True)
    return f"{ENGINE_VERSION}/{embedder_name}/{hashlib.sha1(blob.encode()).hexdigest()[:8]}"


# ---------------------------------------------------------------------------
# 입력 정리
# ---------------------------------------------------------------------------
@dataclasses.dataclass
class Item:
    photo_id: str
    relpath: str
    path: Path
    local: dt.datetime | None  # 현지 벽시계 시각 (날짜 구분용). 미상이면 None
    t: float | None            # 절대 시각(초, 간격 계산용). 미상이면 None


_EPOCH = dt.datetime(1970, 1, 1)


def prepare_items(photos):
    """촬영순(시각 오름차순, 동점은 상대 경로순)으로 정렬하고 미상은 상대 경로순으로 끝에 둡니다."""
    raw, seen = [], set()
    for ph in photos:
        pid = str(ph["photo_id"])
        if pid in seen:
            raise ValueError(f"photo_id가 중복됩니다: {pid}")
        seen.add(pid)
        local, off = J.parse_taken_at(ph.get("taken_at"))
        raw.append((pid, str(ph["relpath"]).replace("\\", "/"), Path(ph["path"]), local, off))
    offsets = Counter(r[4] for r in raw if r[4] is not None)
    default_off = offsets.most_common(1)[0][0] if offsets else 0  # 시간대가 없는 사진은 앨범의 흔한 시간대로
    items = []
    for pid, rel, path, local, off in raw:
        t = None if local is None else (local - _EPOCH).total_seconds() - (default_off if off is None else off)
        items.append(Item(pid, rel, path, local, t))
    known = sorted((i for i in items if i.t is not None), key=lambda i: (i.t, i.relpath, i.photo_id))
    unknown = sorted((i for i in items if i.t is None), key=lambda i: (i.relpath, i.photo_id))
    return known + unknown


def day_of(item, params):
    if item.local is None:
        return None
    return (item.local - dt.timedelta(hours=params["day_start_hour"])).date()


def photos_from_folder(root):
    """폴더를 읽어 recommend 입력 형식으로 (photo_id = 상대 경로). (photos, video_count, failed)"""
    found, videos, failed = J.scan_folder(root)
    photos = [{"photo_id": p["relpath"], "relpath": p["relpath"], "path": str(p["path"]),
               "taken_at": J.read_taken_at(p["path"])} for p in found]
    return photos, videos, failed


# ---------------------------------------------------------------------------
# 임베딩
# ---------------------------------------------------------------------------
def _center_square(im):
    w, h = im.size
    s = min(w, h)
    left, top = (w - s) // 2, (h - s) // 2
    return im.crop((left, top, left + s, top + s))


class TinyEmbedder:
    """16x16 축소 이미지를 벡터로 씁니다. 테스트·흐름 점검용이며 결과 보고에 쓰면 안 됩니다."""

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
    """사전학습 CLIP ViT-B/32 이미지 인코더(ONNX, 가중치 고정). 정규화된 512차원 벡터를 냅니다."""

    def __init__(self, model_path=None):
        import onnxruntime as ort  # 설치: py -m pip install onnxruntime huggingface-hub

        if model_path is None:
            from huggingface_hub import hf_hub_download

            last = None
            for fname in CLIP_FILES:
                try:
                    model_path = hf_hub_download(CLIP_REPO, fname)
                    break
                except Exception as e:  # noqa: BLE001 - 다음 후보 파일 시도
                    last = e
            else:
                raise RuntimeError(f"CLIP 모델을 받지 못했습니다: {last}")
        self.model_path = str(model_path)
        self.name = "clip_" + Path(model_path).stem
        self.sess = ort.InferenceSession(self.model_path, providers=["CPUExecutionProvider"])
        inputs = self.sess.get_inputs()
        self.input_name = next((i.name for i in inputs if "pixel" in i.name), inputs[0].name)
        outs = [o.name for o in self.sess.get_outputs()]
        self.output_name = next((n for n in ("image_embeds", "pooler_output") if n in outs), outs[0])

    @staticmethod
    def preprocess(im):
        """모델 지정 전처리: 짧은 변 224 bicubic, 가운데 224x224, CLIP 평균·표준편차 정규화."""
        w, h = im.size
        s = 224 / min(w, h)
        im = im.resize((max(224, round(w * s)), max(224, round(h * s))), Image.Resampling.BICUBIC)
        im = _center_square(im).resize((224, 224), Image.Resampling.BICUBIC)
        return ((np.asarray(im, np.float32) / 255.0 - CLIP_MEAN) / CLIP_STD).transpose(2, 0, 1)

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


_EMBEDDERS = {}


def get_embedder(kind="clip", clip_model=None):
    """프로세스당 한 번만 모델을 올립니다. (embedder 또는 None, 로딩 초)"""
    if kind == "none":
        return None, 0.0
    key = (kind, clip_model)
    if key in _EMBEDDERS:
        return _EMBEDDERS[key], 0.0
    t0 = time.perf_counter()
    emb = TinyEmbedder() if kind == "tiny" else ClipOnnxEmbedder(clip_model)
    _EMBEDDERS[key] = emb
    return emb, time.perf_counter() - t0


# ---------------------------------------------------------------------------
# 특징: 정방향 512px 축소본 -> 선명도, 임베딩 (캐시)
# ---------------------------------------------------------------------------
def _photo_key(path):
    st = path.stat()
    return hashlib.sha1(f"{path.resolve()}|{st.st_size}|{st.st_mtime_ns}".encode("utf-8")).hexdigest()[:24]


def sharpness(im):
    """선명도: 흑백 축소본에서 가로·세로·두 대각선 방향 2차 미분의 분산 중 가장 작은 값. 클수록 선명합니다.

    손떨림은 흔들린 방향의 디테일만 지우므로, 네 방향을 합친 라플라시안보다 방향별 최솟값이 흔들림을 잘 잡습니다.
    """
    g = np.asarray(im.convert("L"), dtype=np.float32)
    if g.shape[0] < 3 or g.shape[1] < 3:
        return 0.0
    c2 = 2 * g[1:-1, 1:-1]
    d = (g[1:-1, :-2] + g[1:-1, 2:] - c2, g[:-2, 1:-1] + g[2:, 1:-1] - c2,
         g[:-2, :-2] + g[2:, 2:] - c2, g[:-2, 2:] + g[2:, :-2] - c2)
    return float(min(x.var() for x in d))


def work_image_path(cache_dir, key):
    return Path(cache_dir) / "work" / f"{key}.png"


def ensure_work_images(paths_keys, cache_dir, workers=DECODE_WORKERS, log=None):
    """원본을 한 번만 디코딩해 정방향 512px 무손실 PNG로 캐시합니다(병렬). (실패한 key 집합, 새로 디코딩한 수)

    무손실로 두는 이유: JPEG로 다시 압축하면 같은 사진의 CLIP 유사도가 0.95까지 떨어져
    0.92 근처의 판정이 흔들리는 것을 확인했습니다.
    """
    todo = [(p, k) for p, k in paths_keys if not work_image_path(cache_dir, k).exists()]

    def job(pk):
        path, key = pk
        try:
            out = work_image_path(cache_dir, key)
            out.parent.mkdir(parents=True, exist_ok=True)
            tmp = out.with_name(out.stem + f".{os.getpid()}.part")
            J.open_upright(path, RANK_SIDE).save(tmp, "PNG", compress_level=3)
            os.replace(tmp, out)
            return None
        except Exception:  # noqa: BLE001 - 이 사진만 실패
            return key

    failed = set()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for n, bad in enumerate(ex.map(job, todo), 1):
            if bad:
                failed.add(bad)
            if log and len(todo) > 20 and (n % 20 == 0 or n == len(todo)):
                log(f"  원본 디코딩 {n}/{len(todo)}")
    return failed, len(todo) - len(failed)


def compute_features(items, embedder, cache_dir=DEFAULT_CACHE, batch=16, log=None):
    """(sharp, emb 또는 None, 실패한 item 인덱스 집합, 시간 기록). 실패한 사진은 선명도 0, 영벡터입니다."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    keys, failed = [], set()
    for i, it in enumerate(items):
        try:
            keys.append(_photo_key(it.path))
        except OSError:
            keys.append(None)
            failed.add(i)
    t0 = time.perf_counter()
    pk = [(it.path, k) for it, k in zip(items, keys) if k is not None]
    bad_keys, decoded = ensure_work_images(pk, cache_dir, log=log)
    decode_s = time.perf_counter() - t0
    failed |= {i for i, k in enumerate(keys) if k in bad_keys}

    tag = embedder.name if embedder else "none"
    cache_file = cache_dir / f"features_v{FEATURE_VERSION}_{re.sub(r'[^A-Za-z0-9_.-]+', '_', tag)}.npz"
    cache = {}
    if cache_file.exists():
        try:  # with로 닫아야 Windows에서 나중에 같은 파일을 교체할 수 있습니다
            with np.load(cache_file, allow_pickle=False) as z:
                ks, ss, es = z["keys"], z["sharp"], np.array(z["emb"])
            cache = {str(k): (float(s), e) for k, s, e in zip(ks, ss, es)}
        except Exception:  # noqa: BLE001 - 캐시가 깨졌으면 새로 계산
            cache = {}
    todo = [i for i, k in enumerate(keys) if i not in failed and k not in cache]
    t1 = time.perf_counter()
    for s in range(0, len(todo), batch):
        chunk = todo[s:s + batch]
        ims = []
        for i in chunk:
            with Image.open(work_image_path(cache_dir, keys[i])) as im:
                ims.append(im.convert("RGB"))
        vecs = embedder.embed(ims) if embedder else [np.zeros(0, np.float32)] * len(ims)
        for i, im, v in zip(chunk, ims, vecs):
            cache[keys[i]] = (sharpness(im), np.asarray(v, np.float32))
        if log and len(todo) > batch:
            log(f"  특징 계산 {min(s + batch, len(todo))}/{len(todo)}")
    embed_s = time.perf_counter() - t1
    if todo:
        ks = sorted(cache)
        tmp = cache_file.with_name(cache_file.stem + f".{os.getpid()}.part.npz")
        np.savez(tmp, keys=np.array(ks, dtype=str), sharp=np.array([cache[k][0] for k in ks]),
                 emb=np.stack([cache[k][1] for k in ks]))
        os.replace(tmp, cache_file)

    dim = next((len(cache[k][1]) for k in keys if k in cache), 0)
    sharp = np.array([cache[k][0] if (i not in failed and k in cache) else 0.0 for i, k in enumerate(keys)])
    emb = None
    if embedder:
        emb = np.stack([cache[k][1] if (i not in failed and k in cache) else np.zeros(dim, np.float32)
                        for i, k in enumerate(keys)]).astype(np.float32) if items else np.zeros((0, dim), np.float32)
    timing = {"decode_s": decode_s, "decoded": decoded, "embed_s": embed_s, "embedded": len(todo)}
    return sharp, emb, failed, timing


# ---------------------------------------------------------------------------
# 묶기
# ---------------------------------------------------------------------------
def time_segments(items, params):
    """촬영 시각이 있는 사진의 시간 구간(인덱스 목록). 미상은 포함하지 않습니다."""
    gap, span = params["seg_gap_sec"], params["seg_span_sec"]
    segs, cur = [], []
    for i, it in enumerate(items):
        if it.t is None:
            continue
        if cur:
            prev, first = items[cur[-1]], items[cur[0]]
            if it.t - prev.t > gap or it.t - first.t > span or day_of(it, params) != day_of(prev, params):
                segs.append(cur)
                cur = []
        cur.append(i)
    if cur:
        segs.append(cur)
    return segs


def build_groups(items, emb, params, use_clip=True):
    """(groups, diag). groups는 만든 순서의 인덱스 목록이며 각 묶음의 첫 원소가 기준 컷입니다.

    use_clip=False면 시간 구간 하나를 한 묶음으로 봅니다('시간 묶기' 비교 조건).
    diag[i] = {"sim": 가장 비슷했던 기준 컷과의 유사도(없으면 None), "nearest": 그 묶음, "group": 들어간 묶음}
    """
    th = params["clip_sim"]
    groups, diag = [], {}
    for seg in time_segments(items, params):
        if not use_clip:
            groups.append(list(seg))
            for i in seg:
                diag[i] = {"sim": None, "nearest": None, "group": len(groups) - 1}
            continue
        local = []
        for i in seg:
            best, best_s = None, None
            for g in local:  # 만든 순서대로 보며 더 큰 값만 갱신 -> 동점이면 먼저 만든 묶음
                s = float(emb[groups[g][0]] @ emb[i])
                if best_s is None or s > best_s:
                    best, best_s = g, s
            if best is not None and best_s >= th:
                groups[best].append(i)
                joined = best
            else:
                groups.append([i])
                local.append(len(groups) - 1)
                joined = len(groups) - 1
            diag[i] = {"sim": best_s, "nearest": best, "group": joined}
    for i, it in enumerate(items):
        if it.t is None:  # 촬영 시각 미상은 단독 후보
            groups.append([i])
            diag[i] = {"sim": None, "nearest": None, "group": len(groups) - 1}
    return groups, diag


_CONTENT = {}


def load_content_prompts():
    """(이름, 벡터, 부호) 또는 None. content_prompts.npz는 content_prompts.py로 만듭니다."""
    if "v" not in _CONTENT:
        try:
            with np.load(CONTENT_FILE, allow_pickle=False) as z:
                _CONTENT["v"] = ([str(n) for n in z["names"]], np.array(z["vecs"], np.float32),
                                 np.array(z["signs"], np.int8))
        except (OSError, KeyError):
            _CONTENT["v"] = None
    return _CONTENT["v"]


def prompt_z(emb):
    """문장 15개와의 유사도를 문장마다 앨범 안에서 표준화한 값 (사진 수 x 15). 쓸 수 없으면 None."""
    cp = load_content_prompts()
    if emb is None or cp is None or len(emb) == 0 or emb.shape[1] != cp[1].shape[1]:
        return None
    S = emb @ cp[1].T
    std = S.std(axis=0)
    return (S - S.mean(axis=0)) / np.where(std > 1e-9, std, 1.0)


def content_scores(emb):
    """사진별 내용 점수(앨범 안 상대값). 문장 벡터가 없거나 임베딩 차원이 다르면 None."""
    Z = prompt_z(emb)
    if Z is None:
        return None
    signs = load_content_prompts()[2]
    return Z[:, signs > 0].mean(axis=1) - Z[:, signs < 0].mean(axis=1)


def rank_groups(groups, sharp, content=None, score=None):
    """묶음 안 순위. score(학습한 순위 점수)가 있으면 그 내림차순, 없으면 선명도 내림차순.
    같으면 내용 점수 내림차순(없으면 생략), 그다음 촬영순.

    같은 묶음은 거의 같은 장면이라 선명도 차이는 대부분 흔들림·초점 차이입니다.
    """
    first = sharp if score is None else score
    if content is None:
        return [sorted(g, key=lambda i: (-first[i], i)) for g in groups]
    return [sorted(g, key=lambda i: (-first[i], -content[i], i)) for g in groups]


_RANKER = {}


def load_ranker(kind):
    """(scale, w). triage_eval.py --save-ranker로 만든 파일에서 읽습니다. 없으면 ValueError."""
    if kind not in RANK_MODELS:
        raise ValueError(f"rank_model은 sharpness 또는 {', '.join(RANK_MODELS)} 중 하나여야 합니다 (받은 값 {kind}).")
    key = (str(RANKER_FILE), kind)
    if key not in _RANKER:
        try:
            with np.load(RANKER_FILE, allow_pickle=False) as z:
                _RANKER[key] = (np.array(z[f"{kind}_scale"], np.float64), np.array(z[f"{kind}_w"], np.float64))
        except (OSError, KeyError) as e:
            raise ValueError(f"rank_model={kind}에 필요한 {RANKER_FILE.name}이 없거나 {kind} 모델이 없습니다. "
                             "triage_eval.py --save-ranker로 만든 파일을 model 폴더에 넣으세요.") from e
    return _RANKER[key]


def ranker_features(kind, sharp, emb, aes=None, content=None, z=None):
    """순위 모델 입력 (사진 수 x 특징 수). triage_eval.py와 같은 함수를 씁니다.
    small: [log 선명도, 미적, 내용] / prompts: [log 선명도, 미적, 문장 15개] / clip: [log 선명도, 미적, 내용, CLIP 512]"""
    ls = np.log1p(np.asarray(sharp, np.float64))[:, None]
    aes = aesthetic_scores(emb) if aes is None else aes
    aes = np.asarray(aes, np.float64)[:, None]
    if kind == "prompts":
        z = prompt_z(emb) if z is None else z
        return np.hstack([ls, aes, z])
    content = content_scores(emb) if content is None else content
    cols = [ls, aes, np.asarray(content, np.float64)[:, None]]
    if kind == "clip":
        cols.append(np.asarray(emb, np.float64))
    return np.hstack(cols)


def ranker_scores(kind, sharp, emb):
    """학습한 순위 점수 (클수록 사람이 더 좋아할 컷).
    미적 점수·문장 벡터를 쓸 수 없거나 임베딩 차원이 학습 때와 다르면 None (선명도로 고릅니다)."""
    scale, w = load_ranker(kind)
    if emb is None or aesthetic_scores(emb) is None or prompt_z(emb) is None:
        return None
    x = ranker_features(kind, sharp, emb)
    if x.shape[1] != len(scale):
        return None
    return (x / scale) @ w


_AESTHETIC = {}


def load_aesthetic_head():
    """(가중치 512, 절편) 또는 None. LAION-Aesthetics V1의 ViT-B/32 선형층을 aesthetic_head.py로 변환한 파일입니다."""
    if "v" not in _AESTHETIC:
        try:
            with np.load(AESTHETIC_FILE, allow_pickle=False) as z:
                _AESTHETIC["v"] = (np.array(z["w"], np.float32), float(np.ravel(z["b"])[0]))
        except (OSError, KeyError):
            _AESTHETIC["v"] = None
    return _AESTHETIC["v"]


def aesthetic_scores(emb):
    """사진별 미적 점수(대략 1~10, 클수록 보기 좋음). 사람이 매긴 미적 점수로 학습된 선형층을 CLIP 벡터에 씌웁니다.
    가중치 파일이 없거나 임베딩 차원이 다르면 None."""
    ah = load_aesthetic_head()
    if emb is None or ah is None or len(emb) == 0 or emb.shape[1] != ah[0].shape[0]:
        return None
    return emb @ ah[0] + ah[1]


def quality_scores(sharp):
    """화질 점수: 선명도의 앨범 안 백분위(0~1). 사진이 1장이면 1."""
    n = len(sharp)
    if n < 2:
        return np.ones(n)
    order = np.argsort(np.asarray(sharp), kind="stable")
    q = np.empty(n)
    q[order] = np.arange(n) / (n - 1)
    return q


# ---------------------------------------------------------------------------
# 고르기
# ---------------------------------------------------------------------------
def select_draft(items, groups, ranked, emb, k, params, content=None, quality=None, aesthetic=None):
    """초안 K장의 인덱스(촬영순). content·quality·aesthetic이 있으면 관련도에 내용·화질·미적 점수를 섞습니다.
    quality와 aesthetic은 앨범 안 백분위(0~1)입니다."""
    n_groups = len(groups)
    if n_groups < k:  # 묶음이 K개 미만: 모든 대표 컷 뒤에 2위, 3위를 첫 컷 촬영순으로 돌아가며
        order = sorted(range(n_groups), key=lambda g: groups[g][0])
        picks = [ranked[g][0] for g in order]
        r = 1
        while len(picks) < k:
            more = [ranked[g][r] for g in order if len(ranked[g]) > r]
            if not more:
                break
            picks += more[: k - len(picks)]
            r += 1
        return sorted(picks)

    lam, cap = params["lambda"], params["size_cap"]
    reps = [r[0] for r in ranked]
    size = [min(len(g), cap) / cap for g in groups]
    parts = [(params.get("size_weight", 1.0), size)]  # 관련도 = 가중 평균 (점수는 모두 0~1)
    if content is not None and params.get("content_weight", 0.0):
        cn = (content - content.min()) / (content.max() - content.min() + 1e-9)  # 앨범 안 0~1
        parts.append((params["content_weight"], [float(cn[r]) for r in reps]))
    if quality is not None and params.get("quality_weight", 0.0):
        parts.append((params["quality_weight"], [float(quality[r]) for r in reps]))
    if aesthetic is not None and params.get("aesthetic_weight", 0.0):
        parts.append((params["aesthetic_weight"], [float(aesthetic[r]) for r in reps]))
    total = sum(w for w, _ in parts)
    rel = [sum(w * v[n] for w, v in parts) / total for n in range(n_groups)] if total else [0.0] * n_groups
    bucket = [day_of(items[g[0]], params) for g in groups]  # None = 촬영 시각 미상
    photo_count = Counter(day_of(it, params) for it in items)
    alive = set(range(n_groups))
    maxsim = [None] * n_groups  # 지금까지 고른 대표 컷과의 최대 코사인 유사도 (아직 없으면 None -> 0)
    chosen, assigned = [], Counter()

    def take(b):
        cands = [g for g in alive if bucket[g] == b]

        def mmr(g):
            red = 0.0 if maxsim[g] is None else maxsim[g]  # 음의 코사인 값도 그대로 씀
            return (1 - lam) * rel[g] - lam * red

        best = max(cands, key=lambda g: (mmr(g), -reps[g]))  # 동점: 대표 컷 촬영순, 상대 경로순
        chosen.append(best)
        alive.discard(best)
        assigned[b] += 1
        for g in alive:
            s = float(emb[reps[g]] @ emb[reps[best]])
            maxsim[g] = s if maxsim[g] is None else max(maxsim[g], s)

    dates = sorted(b for b in set(bucket) if b is not None)
    if dates:
        d = len(dates)
        use = dates if d <= k else [dates[((2 * j + 1) * d) // (2 * k)] for j in range(k)]
        for day in use:  # ① 날짜마다 1장
            take(day)
        while len(chosen) < k:  # ② √사진 수/(배정 수+1)이 가장 큰 구간 (동점은 이른 날짜, 미상은 끝)
            live = {bucket[g] for g in alive}
            order = [b for b in dates if b in live] + ([None] if None in live else [])
            take(max(order, key=lambda b: (math.sqrt(photo_count[b]) / (assigned[b] + 1), -order.index(b))))
    else:  # 전부 미상
        while len(chosen) < k:
            take(None)
    return sorted(reps[g] for g in chosen)


def uniform_draft(n, k):
    """촬영 순번 균등 추출: floor((j+0.5) n/k)번째."""
    return [((2 * j + 1) * n) // (2 * k) for j in range(k)]


# ---------------------------------------------------------------------------
# 분석 단위
# ---------------------------------------------------------------------------
class Analysis:
    def __init__(self, items, sharp, emb, params, failed, timing, embedder_name):
        self.items, self.sharp, self.emb, self.params = items, sharp, emb, params
        self.failed, self.timing, self.embedder_name = failed, timing, embedder_name
        self.rule_version = rule_version(params, embedder_name)
        self.content = content_scores(emb) if params.get("content_weight", 0.0) else None
        self.quality = quality_scores(sharp) if params.get("quality_weight", 0.0) else None
        aes = aesthetic_scores(emb) if params.get("aesthetic_weight", 0.0) else None
        self.aesthetic = quality_scores(aes) if aes is not None else None  # 앨범 안 백분위
        rk = params.get("rank_model", "sharpness")
        self.rank_score = None if rk == "sharpness" else ranker_scores(rk, sharp, emb)
        self._groups = {}

    def groups(self, kind="time_clip"):
        """(groups, ranked, diag)"""
        if kind not in self._groups:
            if self.emb is None:
                raise ValueError("묶기에는 임베딩이 필요합니다 (embedder='clip').")
            g, diag = build_groups(self.items, self.emb, self.params, use_clip=(kind == "time_clip"))
            self._groups[kind] = (g, rank_groups(g, self.sharp, self.content, self.rank_score), diag)
        return self._groups[kind]

    def default_k(self):
        return min(10, len(self.items))

    def run(self, method, k=None, seed=0):
        """초안 인덱스(촬영순)."""
        n = len(self.items)
        k = self.default_k() if k is None else k
        if not 0 < k <= n:
            raise ValueError(f"k는 1~{n} 사이여야 합니다 (받은 값 {k}).")
        if method == "random":
            return sorted(random.Random(seed).sample(range(n), k))
        if method == "uniform":
            return uniform_draft(n, k)
        if method not in NEEDS_EMBEDDING:
            raise ValueError(f"모르는 방식: {method}")
        groups, ranked, _ = self.groups(method)
        return select_draft(self.items, groups, ranked, self.emb, k, self.params, self.content, self.quality,
                            self.aesthetic)

    def clusters_json(self, kind="time_clip"):
        _, ranked, _ = self.groups(kind)
        return [{"cluster_id": f"c{n + 1:04d}", "photo_ids": [self.items[i].photo_id for i in r],
                 "representative_id": self.items[r[0]].photo_id} for n, r in enumerate(ranked)]


def analyze(photos, *, embedder="clip", clip_model=None, cache_dir=DEFAULT_CACHE, params=None,
            drop_failed=False, log=None):
    """사진 목록의 특징을 계산하고 Analysis를 돌려줍니다.

    drop_failed=True면 디코딩에 실패한 사진을 분석에서 빼고 a.failed에만 남깁니다. False면 선명도 0,
    영벡터로 남는데, 영벡터는 중복도가 0이라 MMR에서 오히려 유리해지므로 추천에는 쓰지 마세요.
    """
    params = load_params(params)
    items = prepare_items(photos)
    if not items:
        raise ValueError("유효한 사진이 없습니다.")
    emb_obj, load_s = get_embedder(embedder, clip_model)
    sharp, emb, failed, timing = compute_features(items, emb_obj, cache_dir, log=log)
    timing["model_load_s"] = load_s
    failed_ids = [items[i].photo_id for i in sorted(failed)]
    if drop_failed and failed:
        keep = [i for i in range(len(items)) if i not in failed]
        items = [items[i] for i in keep]
        sharp = sharp[keep]
        emb = emb[keep] if emb is not None else None
        if not items:
            raise ValueError("디코딩할 수 있는 사진이 없습니다.")
    return Analysis(items, sharp, emb, params, failed_ids, timing, emb_obj.name if emb_obj else "none")


def recommend(photos, k=None, *, embedder="clip", clip_model=None, cache_dir=DEFAULT_CACHE, params=None):
    """추천 인터페이스. k를 생략하면 min(10, 디코딩에 성공한 사진 수).

    디코딩에 실패한 사진은 초안 후보에서 빼고 묶음 목록 끝에 단독 묶음으로만 남깁니다.
    (호출하는 쪽에서 open_upright가 실패한 사진은 읽기 실패로 세고 photos에 넣지 않는 것이 원칙입니다.)
    """
    a = analyze(photos, embedder=embedder, clip_model=clip_model, cache_dir=cache_dir, params=params,
                drop_failed=True)
    if k is not None and k > len(a.items):
        raise ValueError(f"디코딩할 수 있는 사진이 {len(a.items)}장뿐이라 k={k}장을 고를 수 없습니다. "
                         f"실패: {', '.join(a.failed)}")
    draft = a.run("time_clip", k)
    return {"clusters": a.clusters_json("time_clip") + _failed_clusters(a),
            "draft_ids": [a.items[i].photo_id for i in draft],
            "rule_version": a.rule_version}


def _failed_clusters(a):
    start = len(a.groups("time_clip")[0])
    return [{"cluster_id": f"c{start + n + 1:04d}", "photo_ids": [pid], "representative_id": pid}
            for n, pid in enumerate(a.failed)]


# ---------------------------------------------------------------------------
# 명령줄
# ---------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description="J-1 추천 모듈 실행 (React 없이 결과 확인)")
    ap.add_argument("photos_json", nargs="?", help="사진 목록 JSON ([{photo_id, relpath, path, taken_at}])")
    ap.add_argument("--folder", help="사진 폴더 (photo_id = 상대 경로)")
    ap.add_argument("--k", type=int, help="초안 장수 (기본 min(10, N))")
    ap.add_argument("--out", help="결과 JSON 경로")
    ap.add_argument("--cache", default=str(DEFAULT_CACHE), help="캐시 폴더 (입력 폴더 밖, 기본 j1_out/cache)")
    ap.add_argument("--embedder", choices=["clip", "tiny"], default="clip")
    ap.add_argument("--clip-model", help="CLIP 이미지 인코더 .onnx 경로 (없으면 Hugging Face에서 받음)")
    ap.add_argument("--params", help="파라미터 JSON")
    args = ap.parse_args(argv)
    if bool(args.photos_json) == bool(args.folder):
        ap.error("사진 목록 JSON 또는 --folder 중 하나를 주세요.")

    if args.folder:
        photos, videos, failed = photos_from_folder(args.folder)
        print(f"사진 {len(photos)}장, 동영상 {videos}개, 읽기 실패 {len(failed)}장")
        for rel, why in failed[:5]:
            print(f"  - {rel}: {why}")
    else:
        with open(args.photos_json, encoding="utf-8") as f:
            photos = json.load(f)
        print(f"사진 {len(photos)}장")
    a = analyze(photos, embedder=args.embedder, clip_model=args.clip_model, cache_dir=args.cache,
                params=args.params, drop_failed=True, log=print)
    k = args.k or a.default_k()
    draft = a.run("time_clip", k)
    result = {"clusters": a.clusters_json("time_clip") + _failed_clusters(a),
              "draft_ids": [a.items[i].photo_id for i in draft], "rule_version": a.rule_version}
    t = a.timing
    unknown = sum(1 for it in a.items if it.t is None)
    print(f"시간 구간 {len(time_segments(a.items, a.params))}개, 묶음 {len(result['clusters'])}개, "
          f"촬영 시각 미상 {unknown}장, K={k}")
    print(f"시간: 모델 로딩 {t['model_load_s']:.1f}s, 디코딩 {t['decode_s']:.1f}s({t['decoded']}장), "
          f"추론 {t['embed_s']:.1f}s({t['embedded']}장) - 캐시에 없던 사진만 셉니다")
    if a.failed:
        print(f"! 디코딩 실패 {len(a.failed)}장 (초안 후보에서 제외, 단독 묶음으로만 표시): {', '.join(a.failed[:5])}")
    print("초안:", ", ".join(result["draft_ids"]))
    print("rule_version:", result["rule_version"])
    if args.out:
        Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
        print("저장:", Path(args.out).resolve())


if __name__ == "__main__":
    sys.exit(main())
