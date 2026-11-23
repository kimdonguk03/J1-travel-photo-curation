"""실제 CLIP 모델 점검.

  py tests/check_clip.py 작업폴더 사진1.jpg 사진2.png ... [--clip-model 경로]

서로 다른 장면의 원본 사진 여러 장(6장 이상 권장)을 넣으면 세 가지를 확인합니다.
  1. 유사도 분포: 연사 흉내(1~3% 이동, 밝기 변화, 재압축) / 재촬영 흉내(70~85% 영역 다시 잡기) / 서로 다른 사진
  2. 속도: 휴대폰 크기(4032x3024) JPEG의 디코딩+임베딩 시간
  3. 묶기: 사진들로 가짜 여행 앨범을 만들어 시간 묶음과 시간+CLIP 묶음이 장면을 얼마나 정확히 나누는지
"""
import argparse
import datetime as dt
import io
import itertools
import json
import random
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import curation as C  # noqa: E402


def recompress(im, q):
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=q)
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def burst(im, rng):
    w, h = im.size
    dx, dy = int(w * rng.uniform(-0.03, 0.03)), int(h * rng.uniform(-0.03, 0.03))
    out = im.crop((max(0, dx), max(0, dy), w + min(0, dx), h + min(0, dy))).resize((w, h))
    out = ImageEnhance.Brightness(out).enhance(rng.uniform(0.96, 1.04))
    return recompress(out, rng.randint(80, 92))


def reframe(im, rng):
    w, h = im.size
    s = rng.uniform(0.70, 0.85)
    cw, ch = int(w * s), int(h * s)
    x, y = rng.randint(0, w - cw), rng.randint(0, h - ch)
    return recompress(im.crop((x, y, x + cw, y + ch)).resize((w, h)), 85)


def stats(xs, th):
    xs = np.array(xs)
    return (f"n={len(xs):3d}  최소 {xs.min():.3f}  중앙 {np.median(xs):.3f}  최대 {xs.max():.3f}  "
            f"{th} 이상 {np.mean(xs >= th) * 100:5.1f}%")


def save_with_time(im, path, when):
    ex = Image.Exif()
    ex[0x8769] = {0x9003: when.strftime("%Y:%m:%d %H:%M:%S"), 0x9011: "+09:00"}
    im.save(path, "JPEG", quality=88, exif=ex.tobytes())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("work")
    ap.add_argument("images", nargs="+")
    ap.add_argument("--clip-model")
    args = ap.parse_args()
    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)
    rng = random.Random(7)
    th = C.DEFAULT_PARAMS["clip_sim"]
    names = [Path(p).stem for p in args.images]
    srcs = [Image.open(p).convert("RGB") for p in args.images]
    emb = C.ClipOnnxEmbedder(args.clip_model)
    print(f"모델: {emb.name}, 출력 {emb.output_name}")

    # 1. 유사도 분포
    base = emb.embed(srcs)
    b_sims, r_sims = [], []
    for i, im in enumerate(srcs):
        b_sims += list(emb.embed([burst(im, rng) for _ in range(4)]) @ base[i])
        r_sims += list(emb.embed([reframe(im, rng) for _ in range(4)]) @ base[i])
    d_sims = [float(base[i] @ base[j]) for i, j in itertools.combinations(range(len(srcs)), 2)]
    print("\n[1] 원본과의 코사인 유사도")
    print("  연사 흉내   ", stats(b_sims, th))
    print("  재촬영 흉내 ", stats(r_sims, th))
    print("  다른 사진   ", stats(d_sims, th))
    order = np.argsort([-x for x in d_sims])
    pairs = list(itertools.combinations(range(len(srcs)), 2))
    print("  가장 비슷한 다른 사진 쌍:", ", ".join(f"{names[pairs[k][0]]}-{names[pairs[k][1]]} {d_sims[k]:.3f}" for k in order[:3]))

    # 2. 속도 (휴대폰 크기 JPEG)
    big_dir = work / "big"
    big_dir.mkdir(exist_ok=True)
    paths = []
    for i in range(24):
        p = big_dir / f"big_{i:02d}.jpg"
        srcs[i % len(srcs)].resize((4032, 3024), Image.Resampling.BICUBIC).save(p, "JPEG", quality=90)
        paths.append(p)
    t0 = time.perf_counter()
    ims = [C.open_rgb(p) for p in paths]
    t1 = time.perf_counter()
    for k in range(0, len(ims), 16):
        emb.embed(ims[k:k + 16])
    t2 = time.perf_counter()
    per = (t2 - t0) / len(paths)
    print(f"\n[2] 4032x3024 JPEG 1장당 디코딩 {(t1 - t0) / len(paths) * 1000:.0f}ms + 임베딩 {(t2 - t1) / len(paths) * 1000:.0f}ms"
          f" -> 300장 약 {per * 300:.0f}초 (첫 실행만, 이후 캐시)")

    # 3. 가짜 여행 앨범으로 묶기 점검
    album = work / "album"
    album.mkdir(exist_ok=True)
    for f in album.glob("*.jpg"):
        f.unlink()
    truth = {}
    t = dt.datetime(2026, 10, 1, 9, 0, 0)
    n = 0

    def add(im, src, kind, when):
        nonlocal n
        n += 1
        name = f"IMG_{n:04d}.jpg"
        save_with_time(im.resize((1024, int(1024 * im.size[1] / im.size[0]))), album / name, when)
        truth[name] = (src, kind)

    inter = (0, 1) if len(srcs) > 1 else None   # 앞의 두 사진은 30초 안에 번갈아 찍힌 장면으로
    for i, im in enumerate(srcs):
        if inter and i == inter[1]:
            continue
        if inter and i == inter[0]:
            other = srcs[inter[1]]
            seq = [(im, inter[0]), (im, inter[0]), (other, inter[1]), (im, inter[0]), (other, inter[1]), (other, inter[1])]
            for k, (x, s) in enumerate(seq):
                add(burst(x, rng), s, "섞임", t + dt.timedelta(seconds=4 * k))
        else:
            for k in range(4):
                add(burst(im, rng), i, "연사", t + dt.timedelta(seconds=1.5 * k))
            for k in range(2):
                add(reframe(im, rng), i, "70초 뒤 재촬영", t + dt.timedelta(seconds=70 + 2 * k))
        t += dt.timedelta(minutes=40)

    a = C.load_album(album)
    sharp, E = C.compute_features(a, emb, work / "cache", log=lambda *x, **y: None)
    eng = C.Engine(a, sharp, E, C.load_params())
    print(f"\n[3] 가짜 앨범 {len(a.photos)}장, 실제 장면 {len(srcs)}개 (임계값 {th})")
    for kind in ("time", "time_clip"):
        groups = eng.groups(kind)
        mixed = [g for g in groups if len({truth[a.photos[i].name][0] for i in g}) > 1]
        retake_merged = sum(
            1 for s in range(len(srcs))
            if any({truth[a.photos[i].name] for i in g} >= {(s, "연사"), (s, "70초 뒤 재촬영")} for g in groups))
        print(f"  {kind:9s}: 묶음 {len(groups)}개, 여러 장면이 섞인 묶음 {len(mixed)}개, "
              f"재촬영이 연사와 합쳐진 장면 {retake_merged}/{len(srcs) - (1 if inter else 0) - (1 if inter else 0)}")
    (work / "truth.json").write_text(json.dumps(truth, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
