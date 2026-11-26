"""추천 규칙 단위 테스트. 실행: py tests/test_rules.py"""
import datetime as dt
import math
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import evaluate as E  # noqa: E402
import j1_image as J  # noqa: E402
import recommend as R  # noqa: E402

P = R.load_params()
BASE = dt.datetime(2026, 10, 1, 9, 0, 0)


def items_at(times, unknown=0):
    """초 단위 시각 목록으로 Item을 만듭니다. unknown개는 촬영 시각 미상."""
    out = [R.Item(f"p{i:03d}", f"IMG_{i:03d}.jpg", Path("x"), BASE + dt.timedelta(seconds=s),
                  (BASE + dt.timedelta(seconds=s) - R._EPOCH).total_seconds()) for i, s in enumerate(times)]
    out += [R.Item(f"u{i:03d}", f"zz_{i:03d}.png", Path("x"), None, None) for i in range(unknown)]
    return out


def unit(deg):
    return np.array([math.cos(math.radians(deg)), math.sin(math.radians(deg))])


def rand_unit(n, dim=64, seed=0):
    v = np.random.default_rng(seed).normal(size=(n, dim))
    return v / np.linalg.norm(v, axis=1, keepdims=True)


# --- 입력 -------------------------------------------------------------------
def test_taken_at_parsing():
    assert J.parse_exif_offset("+09:00") == 32400 and J.parse_exif_offset("-05:30") == -19800
    assert J.parse_exif_datetime("0000:00:00 00:00:00") is None
    local, off = J.parse_taken_at("2026-10-01T14:03:22.370+09:00")
    assert local == dt.datetime(2026, 10, 1, 14, 3, 22, 370000) and off == 32400
    assert J.parse_taken_at(None) == (None, None)


def test_prepare_items_orders_unknown_last():
    photos = [{"photo_id": "b", "relpath": "b.jpg", "path": "b", "taken_at": None},
              {"photo_id": "c", "relpath": "c.jpg", "path": "c", "taken_at": "2026-10-01T10:00:05.000+09:00"},
              {"photo_id": "a", "relpath": "a.jpg", "path": "a", "taken_at": "2026-10-01T10:00:05.000+09:00"},
              {"photo_id": "d", "relpath": "sub\\d.jpg", "path": "d", "taken_at": "2026-10-01T09:00:00.000"}]
    items = R.prepare_items(photos)
    assert [i.photo_id for i in items] == ["d", "a", "c", "b"]  # 동점은 상대 경로순, 미상은 끝
    assert items[0].relpath == "sub/d.jpg"


# --- 시간 구간 ----------------------------------------------------------------
def test_segment_gap_30s():
    assert R.time_segments(items_at([0, 10, 45]), P) == [[0, 1], [2]]
    assert R.time_segments(items_at([0, 30]), P) == [[0, 1]]  # 정확히 30초는 넘지 않음


def test_segment_span_120s_from_first():
    assert R.time_segments(items_at([0, 25, 50, 75, 100, 125, 150]), P) == [[0, 1, 2, 3, 4], [5, 6]]


def test_segment_splits_at_date_change():
    items = items_at([0, 15])
    for it, d in zip(items, (dt.datetime(2026, 10, 1, 23, 59, 50), dt.datetime(2026, 10, 2, 0, 0, 5))):
        it.local, it.t = d, (d - R._EPOCH).total_seconds()
    assert R.time_segments(items, P) == [[0], [1]]


# --- 유사 컷 묶기 --------------------------------------------------------------
def test_compares_only_with_first_shot():
    items = items_at([0, 2, 4])
    emb = np.stack([unit(0), unit(18.19), unit(31.79)])  # a-b 0.95, a-c 0.85, b-c 0.97
    groups, _ = R.build_groups(items, emb, P)
    assert groups == [[0, 1], [2]]


def test_tie_goes_to_earlier_group_and_threshold_inclusive():
    c, s = math.cos(math.radians(12)), math.sin(math.radians(12))
    items = items_at([0, 1, 2])
    emb = np.array([[c, -s], [c, s], [1.0, 0.0]])  # 두 기준 컷은 0.913으로 따로, 셋째는 둘 다 0.978
    assert R.build_groups(items, emb, P)[0] == [[0, 2], [1]]
    emb2 = np.array([[1.0, 0.0], [0.92, math.sqrt(1 - 0.92 ** 2)]])
    assert R.build_groups(items_at([0, 1]), emb2, P)[0] == [[0, 1]]


def test_unknown_time_is_single_and_time_only_grouping():
    items = items_at([0, 5, 100], unknown=2)
    emb = np.tile([1.0, 0.0], (5, 1))
    assert R.build_groups(items, emb, P)[0] == [[0, 1], [2], [3], [4]]
    assert R.build_groups(items, emb, P, use_clip=False)[0] == [[0, 1], [2], [3], [4]]


def test_rank_ties_by_capture_order():
    assert R.rank_groups([[0, 1, 2]], np.array([5.0, 9.0, 9.0])) == [[1, 2, 0]]


# --- 고르기 -------------------------------------------------------------------
def test_mmr_prefers_less_redundant():
    """λ=0.5에서 둘째 날 두 후보의 크기 점수가 같고 첫날 대표 컷과의 유사도가 0.9, 0.3이면 0.3인 후보가 뽑힌다."""
    items = items_at([0, 86400, 86400 + 3600])
    emb = np.array([[1, 0, 0], [0.9, math.sqrt(1 - 0.81), 0], [0.3, 0, math.sqrt(1 - 0.09)]])
    groups, _ = R.build_groups(items, emb, P)
    draft = R.select_draft(items, groups, R.rank_groups(groups, np.zeros(3)), emb, 2, P)
    assert draft == [0, 2]


def test_more_dates_than_k_uses_spread_dates():
    items = items_at([86400 * d for d in range(12)])
    emb = rand_unit(12)
    groups, _ = R.build_groups(items, emb, P)
    draft = R.select_draft(items, groups, R.rank_groups(groups, np.zeros(12)), emb, 10, P)
    assert draft == [0, 1, 3, 4, 5, 6, 7, 9, 10, 11]  # floor((j+0.5)x12/10)


def test_slot_allocation_sqrt_rule():
    day1 = [3600 * h for h in range(9)]
    day2 = [86400 + 3600 * h for h in range(4)]
    items = items_at(day1 + day2)
    emb = rand_unit(13, seed=1)
    groups, _ = R.build_groups(items, emb, P)
    draft = R.select_draft(items, groups, R.rank_groups(groups, np.zeros(13)), emb, 5, P)
    assert sum(i < 9 for i in draft) == 3 and sum(i >= 9 for i in draft) == 2


def test_unknown_joins_from_step_two():
    items = items_at([0, 3600, 7200], unknown=4)
    emb = rand_unit(7, seed=2)
    groups, _ = R.build_groups(items, emb, P)
    draft = R.select_draft(items, groups, R.rank_groups(groups, np.zeros(7)), emb, 3, P)
    assert sum(i < 3 for i in draft) == 1 and sum(i >= 3 for i in draft) == 2


def test_fill_when_fewer_groups_than_k():
    items = items_at([0, 1, 2, 3600, 3601, 7200])
    emb = np.tile([1.0, 0.0], (6, 1))
    groups, _ = R.build_groups(items, emb, P)
    assert groups == [[0, 1, 2], [3, 4], [5]]
    ranked = R.rank_groups(groups, np.array([1.0, 3.0, 2.0, 5.0, 4.0, 1.0]))
    assert R.select_draft(items, groups, ranked, emb, 5, P) == [1, 2, 3, 4, 5]
    assert R.select_draft(items, groups, ranked, emb, 6, P) == [0, 1, 2, 3, 4, 5]


def test_k_is_min_10_n_and_draft_distinct():
    for n in (7, 10, 23):
        items = items_at([45 * i for i in range(n)])
        a = R.Analysis(items, np.zeros(n), rand_unit(n, seed=n), P, [], {}, "test")
        draft = a.run("time_clip")
        assert len(draft) == min(10, n) == len(set(draft))


def test_uniform_baseline():
    assert R.uniform_draft(300, 10) == [15, 45, 75, 105, 135, 165, 195, 225, 255, 285]
    assert R.uniform_draft(10, 10) == list(range(10))


def test_boundary_burst_301():
    """300·301번째가 같은 연사(같은 벡터, 1초 간격)면 한 묶음이 된다."""
    times = [40 * i for i in range(300)] + [40 * 299 + 1]
    items = items_at(times)
    emb = rand_unit(301, seed=3)
    emb[300] = emb[299]
    groups, _ = R.build_groups(items, emb, P)
    assert [299, 300] in groups and len(groups) == 300


def test_features_independent_of_batch_size():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        photos = []
        for i in range(37):
            im = Image.new("RGB", (120, 90), ((i * 37) % 255, (i * 91) % 255, 120))
            ImageDraw.Draw(im).rectangle((i, 10, i + 30, 60), fill=(255, 255, 255))
            p = d / f"IMG_{i:03d}.png"
            im.save(p)
            photos.append({"photo_id": p.name, "relpath": p.name, "path": str(p), "taken_at": None})
        items = R.prepare_items(photos)
        emb_obj, _ = R.get_embedder("tiny")
        s1, e1, _, _ = R.compute_features(items, emb_obj, d / "c1", batch=16)
        s2, e2, _, _ = R.compute_features(items, emb_obj, d / "c2", batch=64)
        assert np.allclose(s1, s2) and np.allclose(e1, e2)


# --- 내용 점수 ----------------------------------------------------------------
def _prompt_vec(name):
    names, vecs, _ = R.load_content_prompts()
    return vecs[names.index(name)]


def test_content_scores_prefer_people_over_road():
    emb = np.stack([_prompt_vec(n) for n in ("group", "landmark", "road", "document")])
    q = R.content_scores(emb)
    assert min(q[0], q[1]) > max(q[2], q[3])


def test_content_score_changes_pick():
    """같은 날 크기가 같은 두 묶음 중, 내용 점수가 높은 쪽(단체사진)을 고른다. 끄면 촬영순으로 앞의 도로 사진."""
    items = items_at([0, 3600])
    emb = np.stack([_prompt_vec("road"), _prompt_vec("group")])
    groups, _ = R.build_groups(items, emb, P)
    content = R.content_scores(emb)
    ranked = R.rank_groups(groups, np.zeros(2), content)
    assert R.select_draft(items, groups, ranked, emb, 1, P, content) == [1]
    p0 = dict(P, content_weight=0.0)
    assert R.select_draft(items, groups, R.rank_groups(groups, np.zeros(2)), emb, 1, p0, None) == [0]


def test_rank_within_group_by_sharpness_then_content():
    assert R.rank_groups([[0, 1, 2]], np.array([5.0, 1.0, 9.0]), np.array([0.1, 0.9, 0.1])) == [[2, 0, 1]]
    assert R.rank_groups([[0, 1, 2]], np.array([5.0, 5.0, 1.0]), np.array([0.1, 0.9, 0.5])) == [[1, 0, 2]]


# --- 화질 점수 (r3) ------------------------------------------------------------
def _texture(seed=0, side=128):
    return Image.fromarray(np.random.default_rng(seed).integers(0, 256, (side, side), dtype=np.uint8)).convert("RGB")


def _shake(im, n=9, axis=1):
    """한 방향으로 n픽셀 흔들린 사진 (평균 필터)."""
    a = np.asarray(im, dtype=np.float32)
    return Image.fromarray((sum(np.roll(a, k - n // 2, axis=axis) for k in range(n)) / n).astype(np.uint8))


def _laplacian_var(im):
    g = np.asarray(im.convert("L"), dtype=np.float32)
    return float((-4 * g[1:-1, 1:-1] + g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:]).var())


def test_sharpness_catches_one_direction_shake():
    """한 방향으로만 흔들려도 선명도가 크게 떨어지고, 네 방향을 합친 라플라시안(r2까지)보다 더 크게 떨어진다."""
    rows = np.tile(((np.arange(128) % 4 < 2) * 255).astype(np.uint8)[:, None], (1, 128))  # 가로 줄무늬
    for axis, stripes in ((1, rows), (0, rows.T)):  # 줄무늬와 같은 방향으로 흔들림: 줄무늬는 남고 디테일만 사라짐
        im = Image.blend(_texture(), Image.fromarray(stripes).convert("RGB"), 0.5)
        shaken = _shake(im, axis=axis)
        new, old = R.sharpness(shaken) / R.sharpness(im), _laplacian_var(shaken) / _laplacian_var(im)
        assert new < 0.1 and new < old, (axis, new, old)


def test_quality_scores_are_album_percentiles():
    assert np.allclose(R.quality_scores(np.array([30.0, 10.0, 20.0])), [1.0, 0.0, 0.5])
    assert np.allclose(R.quality_scores(np.array([7.0])), [1.0])


def test_quality_weight_prefers_sharper_scene():
    """같은 날 크기·내용이 같은 두 장면 중 화질 점수가 높은(선명한) 쪽. 화질 비중 0이면 촬영순."""
    items = items_at([0, 3600])
    emb = np.stack([unit(0), unit(90)])
    groups, _ = R.build_groups(items, emb, P)
    sharp = np.array([10.0, 50.0])
    ranked = R.rank_groups(groups, sharp)
    q = R.quality_scores(sharp)
    assert R.select_draft(items, groups, ranked, emb, 1, P, None, q) == [1]
    assert R.select_draft(items, groups, ranked, emb, 1, dict(P, quality_weight=0.0), None, q) == [0]


def test_analysis_uses_quality_only_when_weighted():
    items = items_at([0, 3600, 7200])
    emb = np.stack([unit(0), unit(60), unit(120)])
    sharp = np.array([1.0, 2.0, 3.0])
    assert R.Analysis(items, sharp, emb, P, [], {}, "t").quality is not None
    assert R.Analysis(items, sharp, emb, dict(P, quality_weight=0.0), [], {}, "t").quality is None


def test_content_skipped_when_dimension_differs():
    assert R.content_scores(rand_unit(5, dim=64)) is None


# --- 채점 ---------------------------------------------------------------------
def test_owner_csv_scoring():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "owner.csv"
        p.write_text("album_id,scene_id,relpath,owner_pick\n"
                     "jeju,S01_해변,a.jpg,1\njeju,S01_해변,b.jpg,0\n"
                     "jeju,S02_저녁,c.jpg,1\njeju,S03_야경,d\\e.jpg,0\n", encoding="utf-8-sig")
        owner = E.load_owner_csv(p)
    assert owner.scenes == {"S01_해변": {"a.jpg", "b.jpg"}, "S02_저녁": {"c.jpg"}, "S03_야경": {"d/e.jpg"}}
    assert owner.picks == {"a.jpg", "c.jpg"}
    r = E.score_draft(["b.jpg", "d/e.jpg", "x.jpg"], owner)
    assert (r["scene_hits"], r["scenes"], r["matched"], r["picks"]) == (2, 3, 0, 2)
    assert r["missed"] == ["S02_저녁"]


def test_moment_hits_same_photo_or_near_and_similar():
    """주인이 고른 사진마다: 초안에 같은 사진이 있거나, 10분 안에 찍은 유사도 0.80 이상 사진이 있으면 적중."""
    items = items_at([0, 300, 1000, 4000])
    items[3] = R.Item("u000", "zz.png", Path("x"), None, None)  # 촬영 시각 미상
    emb = np.stack([unit(0), unit(20), unit(5), unit(0)])  # cos(20도)=0.94, cos(5도)=0.996
    a = R.Analysis(items, np.ones(4), emb, P, [], {}, "t")
    owner = E.Owner({"x"}, {}, {"IMG_000.jpg", "IMG_002.jpg", "zz.png"})
    assert E.moment_hits(a, [1], owner) == 1   # 0번: 5분 차이, 0.94 -> 적중 / 2번: 10분 초과
    assert E.moment_hits(a, [2], owner) == 1   # 2번 자기 자신만 (0번과는 15분 차이)
    assert E.moment_hits(a, [3], owner) == 1   # 시각 미상은 같은 사진일 때만
    assert E.moment_hits(a, [1], owner, sim=0.95) == 0


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"{len(tests)}개 통과")
