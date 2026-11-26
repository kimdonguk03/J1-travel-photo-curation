#!/usr/bin/env python3
"""연사 중 한 장 고르기를 외부 사람 선호 데이터로 검증하고 학습합니다.

데이터: Princeton/Adobe Photo Triage (Chang et al., SIGGRAPH 2016). 개인 앨범의 비슷한 사진 묶음(series) 안에서
사람들이 두 사진 중 어느 쪽을 더 좋아했는지 모은 데이터입니다. 라벨이 공개된 train_val만 씁니다.
이미지는 연구용·비상업 라이선스이므로 저장소에 올리지 않습니다.

  py triage_eval.py /content/triage/train_val --cache /content/cache_triage --out triage_result.csv

pairlist 열: series photo1 photo2 pref(photo1을 고른 비율) rank1 rank2 (묶음 안 순위, 1이 최고)
이미지 이름: {series:06d}-{photo:02d}.JPG

평가 (train 묶음의 15%를 떼어 둔 시험 묶음 + 공식 val):
  쌍 정확도      사람 다수가 고른 쪽을 맞힌 비율 (전체 / 70% 이상 합의한 쌍)
  1등 정확도     묶음마다 점수가 가장 높은 사진이 사람 순위 1등인 비율
비교: 선명도(우리 대표 컷 규칙), 미적 점수, 내용 점수, 그리고 학습한 쌍 비교 로지스틱 회귀.
학습은 떼어 둔 시험 묶음을 전혀 보지 않습니다 (규제 세기는 train 안에서 다시 나눈 검증 묶음으로 고름).

표준화 통계: 내용 점수와 문장 점수는 문장마다 평균·표준편차로 표준화합니다. 기본(--stats train)은 학습 묶음
사진만으로 이 통계를 냅니다. 비교를 위해 예전 방식(train_val 사진 전체, 시험 묶음과 공식 val 포함)으로도 같은
분할·시드에서 다시 학습·평가해 표를 함께 냅니다. --save-ranker는 --stats로 고른 방식의 모델을 저장합니다.
사람 선호가 정확히 반반(pref=0.5)인 쌍은 정답이 없어 학습과 평가에서 뺍니다.
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

import recommend as R

PHOTO_EXTS = {".jpg", ".jpeg", ".png"}
LAMBDAS = [0.01, 0.1, 1.0, 10.0, 100.0]


# ---------------------------------------------------------------------------
# 데이터 읽기
# ---------------------------------------------------------------------------
def read_pairlist(path):
    """[(series, p1, p2, pref, rank1, rank2)]. 숫자로 시작하지 않는 줄은 건너뜁니다."""
    rows = []
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        f = line.replace(",", " ").split()
        if len(f) < 4 or not f[0].isdigit():
            continue
        s, a, b = int(f[0]), int(f[1]), int(f[2])
        pref = float(f[3])
        r1 = int(float(f[4])) if len(f) > 4 else None
        r2 = int(float(f[5])) if len(f) > 5 else None
        rows.append((s, a, b, pref, r1, r2))
    return rows


def index_images(root):
    """파일 이름(확장자 제외, 소문자) -> 경로. test 폴더는 제외합니다."""
    out = {}
    for p in Path(root).rglob("*"):
        if p.suffix.lower() in PHOTO_EXTS and "test" not in {x.lower() for x in p.relative_to(root).parts[:-1]}:
            out[p.stem.lower()] = p
    return out


def photo_name(series, photo, offset):
    return f"{series:06d}-{photo + offset:02d}"


def pick_offset(pairs, images):
    """pairlist의 사진 번호가 0부터인지 1부터인지 파일 이름과 맞춰 봅니다."""
    best = max((0, 1), key=lambda o: sum(photo_name(s, a, o) in images and photo_name(s, b, o) in images
                                         for s, a, b, *_ in pairs[:500]))
    return best


# ---------------------------------------------------------------------------
# 특징
# ---------------------------------------------------------------------------
def photo_features(paths, cache, clip_model=None, log=print):
    """이름 -> 특징 dict. 우리 추천과 같은 계산(512px 축소본, 방향별 선명도, CLIP ViT-B/32)을 씁니다."""
    names = sorted(paths)
    photos = [{"photo_id": n, "relpath": n, "path": str(paths[n]), "taken_at": None} for n in names]
    items = R.prepare_items(photos)
    emb_obj, _ = R.get_embedder("clip", clip_model)
    sharp, emb, failed, _ = R.compute_features(items, emb_obj, cache, log=log)
    ok = [i for i in range(len(items)) if i not in failed]
    items, sharp, emb = [items[i] for i in ok], sharp[ok], emb[ok]
    aes = R.aesthetic_scores(emb)
    S = emb @ R.load_content_prompts()[1].T  # 문장 15개와의 유사도 (표준화 전)
    feats = {}
    for i, it in enumerate(items):
        feats[it.photo_id] = {"sharp_raw": float(sharp[i]), "sharp": float(np.log1p(sharp[i])), "aes": float(aes[i]),
                              "emb": emb[i], "S": S[i]}
    if failed:
        log(f"디코딩 실패 {len(failed)}장은 뺐습니다.")
    return feats


def build_vectors(feats, stat_names):
    """stat_names 사진들의 문장 유사도 평균·표준편차로 표준화해 내용 점수와 순위 모델 입력(vec_*)을 만듭니다.
    추천과 같은 함수(R.ranker_features)를 씁니다."""
    names = sorted(feats)
    S = np.array([feats[n]["S"] for n in names])
    ref = np.array([feats[n]["S"] for n in sorted(stat_names) if n in feats])
    sd = ref.std(axis=0)
    Z = (S - ref.mean(axis=0)) / np.where(sd > 1e-9, sd, 1.0)
    signs = R.load_content_prompts()[2]
    content = Z[:, signs > 0].mean(axis=1) - Z[:, signs < 0].mean(axis=1)
    sharp = np.array([feats[n]["sharp_raw"] for n in names])
    emb = np.array([feats[n]["emb"] for n in names])
    aes = np.array([feats[n]["aes"] for n in names])
    vecs = {kind: R.ranker_features(kind, sharp, emb, aes, content, Z) for kind in R.RANK_MODELS}
    for i, n in enumerate(names):
        feats[n]["content"] = float(content[i])
        for kind in R.RANK_MODELS:
            feats[n][f"vec_{kind}"] = vecs[kind][i]


SMALL = ["sharp", "aes", "content"]


def vector(f, kind):
    return f[f"vec_{kind}"]


# ---------------------------------------------------------------------------
# 쌍 비교 로지스틱 회귀 (절편 없음: 두 사진의 순서를 바꾸면 확률도 1-p)
# ---------------------------------------------------------------------------
def fit_pairwise(X, y, lam, iters=50):
    """X: 사진1 특징 - 사진2 특징 (표준화된 값), y: 사람이 사진1을 골랐으면 1. L2 규제 뉴턴법."""
    n, d = X.shape
    w = np.zeros(d)
    for _ in range(iters):
        p = 1 / (1 + np.exp(-(X @ w)))
        g = X.T @ (p - y) / n + lam * w / n
        H = (X * (p * (1 - p))[:, None]).T @ X / n + lam * np.eye(d) / n
        step = np.linalg.solve(H, g)
        w -= step
        if np.abs(step).max() < 1e-8:
            break
    return w


def pair_arrays(pairs, feats, kind, offset):
    X, y, conf, keep = [], [], [], []
    for s, a, b, pref, *_ in pairs:
        na, nb = photo_name(s, a, offset), photo_name(s, b, offset)
        if na not in feats or nb not in feats or pref == 0.5:
            continue
        X.append(vector(feats[na], kind) - vector(feats[nb], kind))
        y.append(1.0 if pref > 0.5 else 0.0)
        conf.append(abs(pref - 0.5) >= 0.2)
        keep.append((s, na, nb))
    return np.array(X), np.array(y), np.array(conf, bool), keep


def split_series(pairs, frac, seed):
    series = sorted({p[0] for p in pairs})
    rng = np.random.default_rng(seed)
    held = set(rng.choice(series, size=max(1, int(round(frac * len(series)))), replace=False).tolist())
    return [p for p in pairs if p[0] not in held], [p for p in pairs if p[0] in held]


class Learned:
    """특징 묶음 하나로 학습한 순위 모델. score(f)가 클수록 사람이 더 좋아할 사진."""

    def __init__(self, kind, train_pairs, feats, offset, seed=0):
        self.kind = kind
        inner_tr, inner_va = split_series(train_pairs, 0.15, seed + 1)
        Xtr, ytr, _, _ = pair_arrays(inner_tr, feats, kind, offset)
        Xva, yva, _, _ = pair_arrays(inner_va, feats, kind, offset)
        Xall, yall, _, _ = pair_arrays(train_pairs, feats, kind, offset)
        self.scale = Xall.std(0) + 1e-9  # 차이의 표준편차로 나눔 (평균은 대칭이라 0 근처)
        best = max(LAMBDAS, key=lambda lam: np.mean(((Xva / self.scale) @ fit_pairwise(Xtr / self.scale, ytr, lam) > 0) == (yva > 0.5)))
        self.lam = best
        self.w = fit_pairwise(Xall / self.scale, yall, best)

    def score(self, f):
        return float((vector(f, self.kind) / self.scale) @ self.w)


# ---------------------------------------------------------------------------
# 평가
# ---------------------------------------------------------------------------
def evaluate(pairs, feats, offset, scorers):
    """방식별 (쌍 정확도, 합의 쌍 정확도, 1등 정확도, 쌍 수, 합의 쌍 수, 묶음 수)."""
    ranks = defaultdict(dict)  # series -> 이름 -> 순위
    for s, a, b, pref, r1, r2 in pairs:
        if r1 is not None:
            ranks[s][photo_name(s, a, offset)] = r1
        if r2 is not None:
            ranks[s][photo_name(s, b, offset)] = r2
    out = {}
    for name, fn in scorers.items():
        right, conf_right, n, nc = 0, 0, 0, 0
        for s, a, b, pref, *_ in pairs:
            na, nb = photo_name(s, a, offset), photo_name(s, b, offset)
            if na not in feats or nb not in feats or pref == 0.5:
                continue
            da, db = fn(feats[na]), fn(feats[nb])
            ok = 0.5 if da == db else float((da > db) == (pref > 0.5))
            right += ok
            n += 1
            if abs(pref - 0.5) >= 0.2:
                conf_right += ok
                nc += 1
        top, m = 0, 0
        for s, rk in ranks.items():
            names = [x for x in rk if x in feats]
            if len(names) < 2:
                continue
            m += 1
            top += rk[max(names, key=lambda x: fn(feats[x]))] == min(rk[x] for x in names)
        out[name] = (right / max(n, 1), conf_right / max(nc, 1), top / max(m, 1), n, nc, m)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Photo Triage로 연사 대표 컷 고르기 검증·학습")
    ap.add_argument("root", help="train_val 폴더 (train_pairlist.txt, val_pairlist.txt, 이미지)")
    ap.add_argument("--cache", default=str(R.DEFAULT_CACHE))
    ap.add_argument("--clip-model")
    ap.add_argument("--holdout", type=float, default=0.15, help="train에서 시험용으로 떼어 둘 묶음 비율")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", help="결과 CSV")
    ap.add_argument("--stats", choices=["train", "all"], default="train",
                    help="표준화 통계를 낼 사진: train(학습 묶음만, 기본) 또는 all(예전 방식). 둘 다 평가하고, 이 값으로 저장 모델을 고릅니다")
    ap.add_argument("--save-ranker", help="학습한 순위 모델 3종(small·prompts·clip)을 저장할 npz. "
                    "model/triage_ranker.npz로 두고 params.json의 rank_model로 고릅니다")
    args = ap.parse_args(argv)

    root = Path(args.root)
    train_file = next(root.rglob("train_pairlist.txt"), None)
    val_file = next(root.rglob("val_pairlist.txt"), None)
    if train_file is None:
        raise SystemExit(f"{root} 아래에 train_pairlist.txt가 없습니다.")
    train_all = read_pairlist(train_file)
    val = read_pairlist(val_file) if val_file else []
    images = index_images(root)
    offset = pick_offset(train_all, images)
    need = {photo_name(s, x, offset) for s, a, b, *_ in train_all + val for x in (a, b)}
    paths = {n: images[n] for n in need if n in images}
    print(f"쌍 train {len(train_all)}, val {len(val)} / 필요한 사진 {len(need)}장 중 찾은 사진 {len(paths)}장 (번호 시작 {offset})")

    feats = photo_features(paths, args.cache, args.clip_model)
    train, test = split_series(train_all, args.holdout, args.seed)
    print(f"학습 묶음 쌍 {len(train)}, 떼어 둔 시험 묶음 쌍 {len(test)}")

    rng = np.random.default_rng(args.seed)
    for f in feats.values():
        f["rand"] = rng.random()
    train_names = {photo_name(s, x, offset) for s, a, b, *_ in train for x in (a, b)}
    stat_sets = {"train": ("학습 묶음 사진만", train_names), "all": ("train_val 사진 전체 (예전 방식)", set(feats))}
    order = [args.stats] + [k for k in stat_sets if k != args.stats]

    rows, saved = [], None
    for mode in order:
        label_mode, names = stat_sets[mode]
        build_vectors(feats, names)
        scorers = {
            "무작위": lambda f: f["rand"],
            "선명도 (r3 대표 컷 규칙)": lambda f: f["sharp"],
            "미적 점수 (LAION)": lambda f: f["aes"],
            "내용 점수": lambda f: f["content"],
        }
        models = {}
        for kind, label in [("small", "학습: 선명도+미적+내용"), ("prompts", "학습: 선명도+미적+문장 15개"),
                            ("clip", "학습: 선명도+미적+내용+CLIP 512")]:
            models[kind] = Learned(kind, train, feats, offset, args.seed)
            scorers[label] = models[kind].score
        if saved is None:
            saved = models
        print(f"\n## 표준화 통계: {label_mode} (사진 {len(names & set(feats))}장)")
        for split_name, pairs in [("시험 묶음 (train에서 떼어 둠)", test), ("공식 val", val)]:
            if not pairs:
                continue
            res = evaluate(pairs, feats, offset, scorers)
            first = next(iter(res.values()))
            print(f"\n### {split_name}: 쌍 {first[3]}개 (합의 쌍 {first[4]}개), 묶음 {first[5]}개")
            print("| 방식 | 쌍 정확도 | 합의 쌍 정확도 | 1등 정확도 |")
            print("|---|---|---|---|")
            for name, (acc, cacc, top, n, nc, m) in res.items():
                print(f"| {name} | {acc:.3f} | {cacc:.3f} | {top:.3f} |")
                rows.append({"stats": mode, "split": split_name, "method": name, "pair_acc": round(acc, 4),
                             "confident_acc": round(cacc, 4), "top1_acc": round(top, 4), "pairs": n,
                             "confident_pairs": nc, "series": m})

    models = saved
    build_vectors(feats, stat_sets[args.stats][1])
    sm = models["small"]
    print("\n작은 학습 모델 가중치 (표준화 후):", {k: round(float(v), 3) for k, v in zip(SMALL, sm.w)}, f"λ={sm.lam}")
    print("참고: 70% 이상 합의 쌍 기준 원 논문 최고 모델(미세 조정한 Siamese VGG) 0.73")
    print(f"저장·가중치 출력은 표준화 통계 '{args.stats}' 모델입니다. 사람 선호가 반반(pref=0.5)인 쌍은 정답이 없어 뺐습니다.")
    if args.out:
        with open(args.out, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        print(f"CSV: {args.out}")
    if args.save_ranker:
        out = {}
        for kind, m in models.items():
            out.update({f"{kind}_scale": m.scale, f"{kind}_w": m.w, f"{kind}_lam": np.array(m.lam)})
        np.savez(args.save_ranker, **out)
        print(f"순위 모델 3종: {args.save_ranker} -> model/triage_ranker.npz로 두고 params.json의 rank_model을 "
              "small / prompts / clip 중 하나로 바꾸면 묶음 안 대표 컷을 학습한 점수로 고릅니다")


if __name__ == "__main__":
    sys.exit(main())
