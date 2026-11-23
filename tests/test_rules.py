"""규칙 단위 테스트. 실행: py tests/test_rules.py"""
import math
import random
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import curation as C  # noqa: E402
import evaluate as E  # noqa: E402


def test_exif_parsing():
    assert C.parse_exif_offset("+09:00") == 32400
    assert C.parse_exif_offset("-05:30") == -(5 * 3600 + 30 * 60)
    assert C.parse_exif_offset("garbage") is None
    assert C.parse_exif_datetime("0000:00:00 00:00:00") is None
    assert C.parse_exif_datetime(b"2026:10:01 14:03:22\x00").hour == 14


def test_group_by_time():
    t = np.array([0, 10, 20, 100, 105, 400], float)
    assert C.group_by_time(t, 30) == [[0, 1, 2], [3, 4], [5]]


def test_time_clip_separates_interleaved_and_merges_retake():
    a, b = np.array([1.0, 0.0]), np.array([0.0, 1.0])
    emb = np.stack([a, b, a, b, a])          # 단체사진/풍경이 번갈아, 마지막은 50초 뒤 재촬영
    t = np.array([0, 10, 20, 30, 80], float)
    g = sorted(C.group_by_time_clip(t, emb, 120, 0.9))
    assert g == [[0, 2, 4], [1, 3]], g
    assert C.group_by_time(t, 30) == [[0, 1, 2, 3], [4]]   # 시간만 쓰면 섞이고, 재촬영은 갈라짐
    far = C.group_by_time_clip(np.array([0, 500.0]), np.stack([a, a]), 120, 0.9)
    assert far == [[0], [1]]                               # 창을 벗어나면 비슷해도 따로


def test_allocate_slots():
    assert C.allocate_slots(Counter({"d1": 50, "d2": 30, "d3": 20}), 10) == {"d1": 5, "d2": 3, "d3": 2}
    q = C.allocate_slots(Counter({"d1": 1, "d2": 1, "d3": 1}), 10)
    assert sum(q.values()) == 10 and sorted(q.values()) == [3, 3, 4]
    rng = random.Random(0)
    for _ in range(200):
        counts = Counter({f"d{i}": rng.randint(1, 80) for i in range(rng.randint(1, 12))})
        assert sum(C.allocate_slots(counts, 10).values()) == 10


def test_mmr_prefers_dissimilar():
    reps = [0, 1, 2]
    imp = np.array([1.0, 0.95, 0.6])
    sims = {(0, 1): 1.0, (0, 2): 0.0, (1, 2): 0.0}
    sim = lambda x, y: sims.get((min(x, y), max(x, y)), 1.0)  # noqa: E731
    assert C.mmr_select(reps, imp, ["d"] * 3, {"d": 2}, sim, 2, 0.7) == [0, 2]
    assert C.mmr_select(reps, imp, ["d"] * 3, {"d": 2}, sim, 2, 0.0) == [0, 1]


def test_mmr_respects_day_quota_then_relaxes():
    reps = [0, 1, 2, 3]
    imp = np.array([1.0, 0.9, 0.8, 0.1])
    sim = lambda x, y: 0.0  # noqa: E731
    assert sorted(C.mmr_select(reps, imp, ["d1", "d1", "d1", "d2"], {"d1": 1, "d2": 1}, sim, 2, 0.7)) == [0, 3]
    # d2 자리가 있어도 d2 후보가 없으면 남은 후보에서 채움
    assert len(C.mmr_select(reps, imp, ["d1"] * 4, {"d1": 1, "d2": 1}, sim, 2, 0.7)) == 2


def test_importance_modes():
    t = np.array([0, 1, 2, 3, 1000, 5000], float)
    groups = [[0, 1, 2, 3], [4], [5]]
    size = C.group_importance(groups, t, "size", 300)
    dens = C.group_importance(groups, t, "density", 300)
    assert size[0] == 1.0 and size[1] == size[2] < 1
    assert dens[0] == 1.0
    both = C.group_importance(groups, t, "both", 300)
    assert np.allclose(both, (size + dens) / 2)


def test_scene_map_and_score():
    labels = {"order": list("abcdefgh"),
              "scenes": [{"start": "a", "title": "공항", "must": False},
                         {"start": "d", "title": "해변", "must": True},
                         {"start": "g", "title": "저녁", "must": True}]}
    smap, scenes = E.scene_map(labels)
    assert [smap[x] for x in "abcdefgh"] == [0, 0, 0, 1, 1, 1, 2, 2]
    r = E.score(["b", "e", "f"], ["a", "d", "g"], smap, scenes)
    assert (r["owner_hit"], r["owner_scenes"]) == (2, 3)
    assert (r["must_hit"], r["must_scenes"]) == (1, 2)
    assert r["dup"] == 1 and r["exact"] == 0 and r["missed_owner"] == ["저녁"]
    # 첫 사진이 시작으로 표시되지 않아도 장면 0이 생김
    smap2, scenes2 = E.scene_map({"order": ["x", "y"], "scenes": [{"start": "y", "title": "", "must": False}]})
    assert smap2 == {"x": 0, "y": 1} and scenes2[1]["title"] == "장면 2"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"{len(tests)}개 통과")
