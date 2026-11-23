"""HEIC(아이폰 원본) 읽기 점검. pillow-heif가 설치돼 있어야 합니다.

  py tests/check_heic.py 작업폴더 사진.jpg [--album JPEG앨범폴더] [--embedder clip|tiny]

  1. EXIF 촬영 시각·시간대를 HEIC에서도 읽는지
  2. 회전 정보(세로 사진)가 JPEG와 똑같이 한 번만 적용되는지
  3. 휴대폰 크기 HEIC 디코딩 속도
  4. --album을 주면 그 앨범의 절반을 HEIC로 바꿔 묶음 결과가 JPEG 때와 같은지
"""
import argparse
import shutil
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import curation as C  # noqa: E402

if not C.HEIF_OK:
    raise SystemExit("pillow-heif가 없습니다: py -m pip install pillow-heif")


def exif_bytes(when="2026:10:01 14:03:22", offset="+09:00", orientation=1):
    ex = Image.Exif()
    ex[0x0112] = orientation
    ex[0x8769] = {0x9003: when, 0x9011: offset, 0x9291: "37"}
    return ex.tobytes()


def gray_vec(im):
    v = np.asarray(im.convert("L").resize((48, 64)), np.float32).ravel()
    v -= v.mean()
    return v / (np.linalg.norm(v) + 1e-8)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("work")
    ap.add_argument("image")
    ap.add_argument("--album")
    ap.add_argument("--embedder", default="clip", choices=["clip", "tiny"])
    args = ap.parse_args()
    work = Path(args.work)
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    # 가로로 저장되고 '시계 방향 90도 돌려서 보라'(Orientation=6)는 세로 사진. 왼쪽 위에 빨간 표식.
    base = Image.open(args.image).convert("RGB").resize((800, 600))
    ImageDraw.Draw(base).rectangle((0, 0, 160, 120), fill=(230, 20, 20))
    one = work / "one"
    one.mkdir()
    base.save(one / "IMG_0001.jpg", "JPEG", quality=92, exif=exif_bytes(orientation=6))
    base.save(one / "IMG_0002.HEIC", format="HEIF", quality=90, exif=exif_bytes(orientation=6))

    # 1. 촬영 시각
    a = C.load_album(one)
    print("[1] 촬영 시각")
    for p in a.photos:
        print(f"  {p.name}: {p.local}  출처={p.time_source}")
    assert not a.failed, a.failed
    assert all(p.time_source == "original" for p in a.photos)
    assert len({p.t for p in a.photos}) == 1, "JPEG와 HEIC의 절대 시각이 달라요"

    # 2. 회전
    jpg, heic = (C.open_rgb(one / n) for n in ("IMG_0001.jpg", "IMG_0002.HEIC"))
    upright = base.rotate(-90, expand=True)  # 사람이 보는 방향
    print("\n[2] 회전")
    print(f"  JPEG {jpg.size}, HEIC {heic.size} (세로여야 함)")
    same = float(gray_vec(jpg) @ gray_vec(heic))
    ok_heic = float(gray_vec(heic) @ gray_vec(upright))
    wrong = float(gray_vec(heic) @ gray_vec(upright.rotate(180)))
    print(f"  HEIC와 JPEG 일치도 {same:.3f}, HEIC와 정방향 일치도 {ok_heic:.3f}, 거꾸로 돌린 것과 {wrong:.3f}")
    with Image.open(one / "IMG_0002.HEIC") as raw:
        print(f"  HEIC를 연 직후 크기 {raw.size}, EXIF Orientation {raw.getexif().get(0x0112)}")
    assert heic.size[1] > heic.size[0] and same > 0.95 and ok_heic > 0.95, "회전이 JPEG와 다릅니다"

    # 3. 속도
    big = base.resize((4032, 3024), Image.Resampling.BICUBIC)
    speed = work / "speed"
    speed.mkdir()
    for i in range(6):
        big.save(speed / f"b{i}.heic", format="HEIF", quality=85, exif=exif_bytes())
        big.save(speed / f"b{i}.jpg", "JPEG", quality=90, exif=exif_bytes())
    for ext in ("heic", "jpg"):
        files = sorted(speed.glob(f"*.{ext}"))
        t0 = time.perf_counter()
        for f in files:
            C.open_rgb(f)
        ms = (time.perf_counter() - t0) / len(files) * 1000
        print(f"\n[3] 4032x3024 {ext.upper()} 디코딩 1장당 {ms:.0f}ms" if ext == "heic" else f"    4032x3024 JPG  디코딩 1장당 {ms:.0f}ms")

    # 4. 기존 JPEG 앨범의 절반을 HEIC로 바꿔도 묶음이 같은지
    if args.album:
        src = Path(args.album)
        mixed = work / "mixed"
        mixed.mkdir()
        files = sorted(src.glob("*.jpg"))
        for k, f in enumerate(files):
            if k % 2:
                with Image.open(f) as im:
                    im.save(mixed / (f.stem + ".HEIC"), format="HEIF", quality=85, exif=im.info.get("exif"))
            else:
                shutil.copy2(f, mixed / f.name)
        emb = C.make_embedder(args.embedder)

        def groups_of(folder):
            al = C.load_album(folder)
            sh, E = C.compute_features(al, emb, work / ("cache_" + folder.name), log=lambda *x, **y: None)
            eng = C.Engine(al, sh, E, C.load_params())
            stem = lambda n: Path(n).stem  # noqa: E731
            return al, {kind: sorted(tuple(stem(al.photos[i].name) for i in g) for g in eng.groups(kind))
                        for kind in ("time", "time_clip")}

        a1, g1 = groups_of(src)
        a2, g2 = groups_of(mixed)
        heics = sum(p.path.suffix.lower() == ".heic" for p in a2.photos)
        print(f"\n[4] 섞인 앨범: 사진 {len(a2.photos)}장 중 HEIC {heics}장, 실패 {len(a2.failed)}장")
        for kind in ("time", "time_clip"):
            print(f"  {kind:9s}: JPEG {len(g1[kind])}개 / 섞인 앨범 {len(g2[kind])}개, 묶음 구성 동일: {g1[kind] == g2[kind]}")
    print("\n모든 확인 통과")


if __name__ == "__main__":
    main()
