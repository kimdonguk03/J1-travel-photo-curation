"""실제 CLIP 모델 점검: 유사도 분포, 처리 시간, 묶기.

  py tests/check_clip.py 작업폴더 사진1.jpg 사진2.png ... [--clip-model 경로]

서로 다른 장면의 원본 사진 여러 장(6장 이상 권장)을 넣으면 세 가지를 확인합니다.
  1. 유사도 분포: 합성 연사(1~3% 이동, 밝기 변화, 재압축) / 합성 재촬영(70~85% 영역) / 서로 다른 사진
  2. 속도: 휴대폰 크기(4032x3024) JPEG의 디코딩과 추론 시간
  3. 묶기: 가짜 여행 앨범에서 시간 묶기와 시간+CLIP 묶기가 장면을 얼마나 정확히 나누는지
실제 개발 사진의 연사·같은 장소 다른 장면 점검은 curation.py의 clusters.html(경계 사례)로 합니다.
"""
import argparse
import datetime as dt
import io
import itertools
import random
import shutil
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import j1_image as J  # noqa: E402
import recommend as R  # noqa: E402


def recompress(im, q):
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=q)
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def burst(im, rng):
    w, h = im.size
    dx, dy = int(w * rng.uniform(-0.03, 0.03)), int(h * rng.uniform(-0.03, 0.03))
    out = im.crop((max(0, dx), max(0, dy), w + min(0, dx), h + min(0, dy))).resize((w, h))
    return recompress(ImageEnhance.Brightness(out).enhance(rng.uniform(0.96, 1.04)), rng.randint(80, 92))


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
    th = R.DEFAULT_PARAMS["clip_sim"]
    names = [Path(p).stem for p in args.images]
    srcs = [Image.open(p).convert("RGB") for p in args.images]
    emb, load_s = R.get_embedder("clip", args.clip_model)
    print(f"모델: {emb.name} (로딩 {load_s:.1f}s), 출력 {emb.output_name}")

    # 1. 유사도 분포
    base = emb.embed(srcs)
    b_sims, r_sims = [], []
    for i, im in enumerate(srcs):
        b_sims += list(emb.embed([burst(im, rng) for _ in range(4)]) @ base[i])
        r_sims += list(emb.embed([reframe(im, rng) for _ in range(4)]) @ base[i])
    pairs = list(itertools.combinations(range(len(srcs)), 2))
    d_sims = [float(base[i] @ base[j]) for i, j in pairs]
    print("\n[1] 원본과의 코사인 유사도")
    print("  합성 연사   ", stats(b_sims, th))
    print("  합성 재촬영 ", stats(r_sims, th))
    print("  다른 사진   ", stats(d_sims, th))
    top = np.argsort([-x for x in d_sims])[:3]
    print("  가장 비슷한 다른 사진 쌍:", ", ".join(f"{names[pairs[k][0]]}-{names[pairs[k][1]]} {d_sims[k]:.3f}" for k in top))

    # 2. 속도: 디코딩(정방향 512px)과 추론을 따로
    big = work / "big"
    big.mkdir(exist_ok=True)
    paths = []
    for i in range(24):
        p = big / f"big_{i:02d}.jpg"
        srcs[i % len(srcs)].resize((4032, 3024), Image.Resampling.BICUBIC).save(p, "JPEG", quality=90)
        paths.append(p)
    t0 = time.perf_counter()
    ims = [J.open_upright(p, R.RANK_SIDE) for p in paths]
    t1 = time.perf_counter()
    for k in range(0, len(ims), 16):
        emb.embed(ims[k:k + 16])
    t2 = time.perf_counter()
    print(f"\n[2] 4032x3024 JPEG 1장당 디코딩 {(t1 - t0) / len(paths) * 1000:.0f}ms(순차) + 추론 "
          f"{(t2 - t1) / len(paths) * 1000:.0f}ms")

    # 3. 가짜 여행 앨범: 장면마다 연사 4장 + 20초 뒤 재촬영 2장, 앞의 두 사진은 30초 안에 번갈아 찍음
    album = work / "album"
    if album.exists():
        shutil.rmtree(album)
    album.mkdir()
    truth, n = {}, 0
    t = dt.datetime(2026, 10, 1, 9, 0, 0)

    def add(im, src, kind, when):
        nonlocal n
        n += 1
        name = f"IMG_{n:04d}.jpg"
        save_with_time(im.resize((1024, int(1024 * im.size[1] / im.size[0]))), album / name, when)
        truth[name] = (src, kind)

    for i, im in enumerate(srcs):
        if i == 1:
            continue
        if i == 0 and len(srcs) > 1:
            seq = [(0, srcs[0]), (0, srcs[0]), (1, srcs[1]), (0, srcs[0]), (1, srcs[1]), (1, srcs[1])]
            for k, (s, x) in enumerate(seq):
                add(burst(x, rng), s, "섞임", t + dt.timedelta(seconds=4 * k))
        else:
            for k in range(4):
                add(burst(im, rng), i, "연사", t + dt.timedelta(seconds=1.5 * k))
            for k in range(2):
                add(reframe(im, rng), i, "재촬영", t + dt.timedelta(seconds=25 + 2 * k))
        t += dt.timedelta(minutes=40)

    photos, _, _ = R.photos_from_folder(album)
    a = R.analyze(photos, clip_model=args.clip_model, cache_dir=work / "cache", drop_failed=True)
    scenes_with_retake = len(srcs) - 2
    print(f"\n[3] 가짜 앨범 {len(a.items)}장, 실제 장면 {len(srcs)}개, 시간 구간 "
          f"{len(R.time_segments(a.items, a.params))}개 (기준값 {th})")
    for kind in ("time", "time_clip"):
        groups = a.groups(kind)[0]
        kinds = [{truth[a.items[i].relpath] for i in g} for g in groups]
        mixed = sum(1 for ks in kinds if len({s for s, _ in ks}) > 1)
        merged = sum(1 for s in range(2, len(srcs)) if any({(s, "연사"), (s, "재촬영")} <= ks for ks in kinds))
        print(f"  {kind:9s}: 묶음 {len(groups)}개, 여러 장면이 섞인 묶음 {mixed}개, "
              f"재촬영이 연사와 합쳐진 장면 {merged}/{scenes_with_retake}")


if __name__ == "__main__":
    main()
