"""테스트용 가짜 여행 앨범과 '주인 정답' 라벨을 만듭니다. 실제 사진 품질 평가용이 아닙니다.

  py tests/make_synthetic_album.py 출력폴더
  -> 출력폴더/album (사진), 출력폴더/labels_synthetic.json (정답)
"""
import datetime as dt
import json
import os
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import curation as C  # noqa: E402

# (날짜, 시작 시각, 장면 이름, 연사 묶음 크기들, 꼭 필요?)
SCENES = [
    (1, "09:10", "공항", [2, 1], False),
    (1, "13:30", "해변 단체사진", [8, 3], True),
    (1, "13:31", "해변 바다 풍경", [4], False),      # 단체사진과 섞여 찍힘
    (1, "16:00", "카페", [3, 1, 1], False),
    (1, "19:20", "저녁 식사", [1, 1, 1], True),       # 다 다른 컷, 연사 없음
    (2, "10:00", "산책로", [5, 2], False),
    (2, "12:30", "점심", [2], False),
    (2, "15:00", "전망대", [10, 4, 2], True),
    (2, "21:40", "야경", [6, 3], False),
    (3, "00:30", "숙소 야식", [2], False),            # 새벽이라 2일차로 셈
    (3, "10:30", "시장", [3, 2, 1, 1], False),
    (3, "14:00", "기념품 가게", [1, 1], False),
    (3, "17:00", "돌아가는 길", [2], False),
]
BASE_DAY = dt.datetime(2026, 10, 1)


def scene_image(rng, hue, layout, jitter):
    im = Image.new("HSV", (640, 480), (hue, 160, 200)).convert("RGB")
    d = ImageDraw.Draw(im)
    lr = random.Random(layout)
    for _ in range(6):
        x, y = lr.randint(0, 560), lr.randint(0, 400)
        x += rng.randint(-jitter, jitter)
        y += rng.randint(-jitter, jitter)
        col = tuple(lr.randint(0, 255) for _ in range(3))
        d.ellipse((x, y, x + lr.randint(40, 140), y + lr.randint(40, 140)), fill=col)
    if rng.random() < 0.3:
        im = im.filter(ImageFilter.GaussianBlur(2.5))  # 흔들린 컷
    return im


def save_jpeg(im, path, when):
    ex = C.Image.Exif()
    ex[0x0132] = when.strftime("%Y:%m:%d %H:%M:%S")
    ex[0x8769] = {0x9003: when.strftime("%Y:%m:%d %H:%M:%S"), 0x9011: "+09:00",
                  0x9291: f"{when.microsecond // 10000:02d}"}
    im.save(path, "JPEG", quality=85, exif=ex.tobytes())


def main(out):
    out = Path(out)
    album = out / "album"
    album.mkdir(parents=True, exist_ok=True)
    rng = random.Random(42)
    truth = {}  # 파일명 -> 장면 번호
    n = 0
    for si, (day, hhmm, title, bursts, _) in enumerate(SCENES):
        h, m = map(int, hhmm.split(":"))
        t = BASE_DAY + dt.timedelta(days=day - 1, hours=h, minutes=m)
        hue = (si * 37) % 255
        for bi, size in enumerate(bursts):
            layout = si * 100 + bi
            for k in range(size):
                n += 1
                name = f"IMG_{n:04d}.jpg"
                save_jpeg(scene_image(rng, hue, layout, 6), album / name, t)
                truth[name] = si
                t += dt.timedelta(seconds=rng.uniform(0.4, 3))
            t += dt.timedelta(seconds=rng.uniform(45, 200))
    # 바다 풍경(13:31)은 단체사진(13:30~) 사이에 섞여 찍힙니다. 장면은 촬영 순서상 연속 구간이어야
    # 하므로 라벨에서는 둘을 하나의 '해변 단체사진' 장면으로 합칩니다.
    # EXIF 없는 PNG 한 장(파일 수정 시각 사용)과 깨진 파일 한 장
    png = album / "screenshot.png"
    scene_image(rng, 10, 999, 0).save(png)
    ts = (BASE_DAY + dt.timedelta(days=1, hours=12, minutes=31)).timestamp()
    os.utime(png, (ts, ts))
    (album / "broken.jpg").write_bytes(b"not really a jpeg")

    a = C.load_album(album)
    order = [p.name for p in a.photos if p.name != "broken.jpg"]
    titles = [s[2] for s in SCENES]
    musts = {s[2] for s in SCENES if s[4]}
    seq = []
    sid = 0
    for name in order:
        sid = truth.get(name, sid)  # EXIF 없는 사진은 바로 앞 사진의 장면으로
        title = titles[sid]
        if title == "해변 바다 풍경":
            title = "해변 단체사진"
        if not seq or seq[-1][1] != title:
            seq.append((name, title))
    scenes = [{"start": s, "title": tt, "must": tt in musts} for s, tt in seq]

    # 주인 선택: 장면별 사진 수가 많은 10개 장면에서 한 장씩(무작위 컷)
    by_scene = {}
    for name in order:
        if name in truth:
            by_scene.setdefault(titles[truth[name]], []).append(name)
    top = sorted(by_scene, key=lambda tt: -len(by_scene[tt]))[:10]
    picks = sorted((rng.choice(by_scene[tt]) for tt in top), key=order.index)
    labels = {"format": "j1-labels-v1", "album": "album", "k": 10, "order": order,
              "picks": picks, "scenes": scenes}
    (out / "labels_synthetic.json").write_text(json.dumps(labels, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"사진 {n + 2}개 파일, 장면 {len(scenes)}개 -> {out}")


if __name__ == "__main__":
    main(sys.argv[1])
