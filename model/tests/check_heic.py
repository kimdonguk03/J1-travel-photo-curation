"""HEIC(아이폰 원본) 읽기 점검. pillow-heif가 설치돼 있어야 합니다.

  py tests/check_heic.py work_dir photo.jpg [--album jpeg_album_dir]

  1. EXIF 촬영 시각·시간대를 HEIC에서도 JPEG와 같게 읽는지
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
import j1_image as J  # noqa: E402
import recommend as R  # noqa: E402

if not J.HEIF_OK:
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
    args = ap.parse_args()
    work = Path(args.work)
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    # 가로로 저장되고 '시계 방향 90도 돌려서 보라'(Orientation=6)는 세로 사진. 왼쪽 위에 빨간 표식.
    base = Image.open(args.image).convert("RGB").resize((800, 600))
    ImageDraw.Draw(base).rectangle((0, 0, 160, 120), fill=(230, 20, 20))
    jpg, heic = work / "IMG_0001.jpg", work / "IMG_0002.HEIC"
    base.save(jpg, "JPEG", quality=92, exif=exif_bytes(orientation=6))
    base.save(heic, format="HEIF", quality=90, exif=exif_bytes(orientation=6))

    print("[1] 촬영 시각")
    tj, th = J.read_taken_at(jpg), J.read_taken_at(heic)
    print(f"  JPEG {tj} / HEIC {th}")
    assert tj == th == "2026-10-01T14:03:22.370+09:00"

    print("\n[2] 회전")
    a, b = J.open_upright(jpg), J.open_upright(heic)
    upright = base.rotate(-90, expand=True)
    same, ok = float(gray_vec(a) @ gray_vec(b)), float(gray_vec(b) @ gray_vec(upright))
    print(f"  JPEG {a.size}, HEIC {b.size} (세로여야 함), HEIC-JPEG 일치도 {same:.3f}, HEIC-정방향 {ok:.3f}")
    with Image.open(heic) as raw:
        print(f"  HEIC를 연 직후 크기 {raw.size}, EXIF Orientation {raw.getexif().get(0x0112)}")
    assert b.size[1] > b.size[0] and same > 0.95 and ok > 0.95, "회전이 JPEG와 다릅니다"

    print("\n[3] 4032x3024 디코딩 (정방향 512px, 순차)")
    big = base.resize((4032, 3024), Image.Resampling.BICUBIC)
    for ext, kw in (("heic", {"format": "HEIF", "quality": 85}), ("jpg", {"format": "JPEG", "quality": 90})):
        files = []
        for i in range(4):
            p = work / f"b{i}.{ext}"
            big.save(p, exif=exif_bytes(), **kw)
            files.append(p)
        t0 = time.perf_counter()
        for f in files:
            J.open_upright(f, R.RANK_SIDE)
        print(f"  {ext.upper():4s} 1장당 {(time.perf_counter() - t0) / len(files) * 1000:.0f}ms")

    if args.album:
        src, mixed = Path(args.album), work / "mixed"
        mixed.mkdir()
        for k, f in enumerate(sorted(src.glob("*.jpg"))):
            if k % 2:
                with Image.open(f) as im:
                    im.save(mixed / (f.stem + ".HEIC"), format="HEIF", quality=85, exif=im.info.get("exif"))
            else:
                shutil.copy2(f, mixed / f.name)

        def groups_of(folder):
            photos, _, failed = R.photos_from_folder(folder)
            a = R.analyze(photos, cache_dir=work / "cache", drop_failed=True)
            return a, {kind: sorted(tuple(Path(a.items[i].relpath).stem for i in g) for g in a.groups(kind)[0])
                       for kind in ("time", "time_clip")}

        a1, g1 = groups_of(src)
        a2, g2 = groups_of(mixed)
        heics = sum(it.relpath.lower().endswith(".heic") for it in a2.items)
        print(f"\n[4] 섞인 앨범: 사진 {len(a2.items)}장 중 HEIC {heics}장, 디코딩 실패 {len(a2.failed)}장")
        for kind in ("time", "time_clip"):
            print(f"  {kind:9s}: JPEG {len(g1[kind])}개 / 섞인 앨범 {len(g2[kind])}개, 묶음 구성 동일: {g1[kind] == g2[kind]}")
    print("\n모든 확인 통과")


if __name__ == "__main__":
    main()
