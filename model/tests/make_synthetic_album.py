"""테스트용 가짜 여행 앨범과 owner.csv를 만듭니다. 실제 사진 품질 평가용이 아닙니다.

  py tests/make_synthetic_album.py out_dir
  -> out_dir/album (사진), out_dir/owner.csv (정답)
"""
import csv
import datetime as dt
import os
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import recommend as R  # noqa: E402

# (날짜, 시작 시각, 장면 이름, 연사 묶음 크기들)
SCENES = [
    (1, "09:10", "공항", [2, 1]),
    (1, "13:30", "해변 단체사진", [8, 3]),
    (1, "16:00", "카페", [3, 1, 1]),
    (1, "19:20", "저녁 식사", [1, 1, 1]),
    (2, "10:00", "산책로", [5, 2]),
    (2, "12:30", "점심", [2]),
    (2, "15:00", "전망대", [10, 4, 2]),
    (2, "21:40", "야경", [6, 3]),
    (3, "00:30", "숙소 야식", [2]),
    (3, "10:30", "시장", [3, 2, 1, 1]),
    (3, "14:00", "기념품 가게", [1, 1]),
    (3, "17:00", "돌아가는 길", [2]),
]
BASE_DAY = dt.datetime(2026, 10, 1)


def scene_image(rng, hue, layout, jitter):
    im = Image.new("HSV", (640, 480), (hue, 160, 200)).convert("RGB")
    d = ImageDraw.Draw(im)
    lr = random.Random(layout)
    for _ in range(6):
        x, y = lr.randint(0, 560) + rng.randint(-jitter, jitter), lr.randint(0, 400) + rng.randint(-jitter, jitter)
        d.ellipse((x, y, x + lr.randint(40, 140), y + lr.randint(40, 140)), fill=tuple(lr.randint(0, 255) for _ in range(3)))
    if rng.random() < 0.3:
        im = im.filter(ImageFilter.GaussianBlur(2.5))  # 흔들린 컷
    return im


def save_jpeg(im, path, when):
    ex = Image.Exif()
    ex[0x8769] = {0x9003: when.strftime("%Y:%m:%d %H:%M:%S"), 0x9011: "+09:00",
                  0x9291: f"{when.microsecond // 10000:02d}"}
    im.save(path, "JPEG", quality=85, exif=ex.tobytes())


def main(out):
    out = Path(out)
    album = out / "album"
    album.mkdir(parents=True, exist_ok=True)
    rng = random.Random(42)
    truth, n = {}, 0
    for si, (day, hhmm, title, bursts) in enumerate(SCENES):
        h, m = map(int, hhmm.split(":"))
        t = BASE_DAY + dt.timedelta(days=day - 1, hours=h, minutes=m)
        for bi, size in enumerate(bursts):
            for _ in range(size):
                n += 1
                name = f"IMG_{n:04d}.jpg"
                save_jpeg(scene_image(rng, (si * 37) % 255, si * 100 + bi, 6), album / name, t)
                truth[name] = title
                t += dt.timedelta(seconds=rng.uniform(0.4, 3))
            t += dt.timedelta(seconds=rng.uniform(45, 200))
    # EXIF 없는 스크린샷 1장(촬영 시각 미상), 깨진 파일 1장, 동영상 1개
    scene_image(rng, 10, 999, 0).save(album / "screenshot.png")
    (album / "broken.jpg").write_bytes(b"not really a jpeg")
    (album / "clip.MOV").write_bytes(b"\x00" * 16)

    photos, _, _ = R.photos_from_folder(album)
    order = [p["relpath"] for p in photos]
    by_scene = {}
    for rel in order:
        if rel in truth:
            by_scene.setdefault(truth[rel], []).append(rel)
    top = sorted(by_scene, key=lambda s: -len(by_scene[s]))[:10]   # 주인: 많이 찍은 10개 장면에서 한 장씩
    picks = {rng.choice(by_scene[s]) for s in top}
    with open(out / "owner.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["album_id", "scene_id", "relpath", "owner_pick"])
        for k, s in enumerate(top, 1):
            for rel in by_scene[s]:   # 같은 장면의 컷은 모두 인정
                w.writerow(["synthetic", f"S{k:02d}_{s}", rel, int(rel in picks)])
    print(f"사진 {n + 1}장 + 깨진 파일 1 + 동영상 1, 중요 장면 {len(top)}개 -> {out}")


if __name__ == "__main__":
    main(sys.argv[1])
