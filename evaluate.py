#!/usr/bin/env python3
"""평가용 앨범에서 각 방식의 초안 10장이 앨범 주인의 정답을 얼마나 담았는지 계산합니다.

  py evaluate.py "C:\\Photos\\제주" labels_제주.json "C:\\Photos\\부산" labels_부산.json --params params.json

앨범 폴더와 labeler.py로 받은 라벨 파일을 짝지어 여러 개 넣을 수 있습니다.
튜닝에 쓴 개발용 앨범은 넣지 마세요. 평가 전에 params.json을 고정하고, 결과의 params_hash를 함께 보고하세요.

지표 (장면은 모두 앨범 주인이 나눈 장면 기준이며, 우리 묶음 결과는 채점에 쓰지 않습니다)
  주인 장면 적중  주인이 고른 10장이 속한 장면 중 초안도 한 장 이상 담은 장면 수 / 그 장면 수
  필수 장면 적중  '꼭 필요' 장면 중 초안이 담은 장면 수 / 필수 장면 수
  장면 중복      초안 10장 중 이미 들어간 장면과 겹치는 장 수 (낮을수록 다양)
  같은 사진      주인이 고른 사진과 정확히 같은 사진 수 (참고용, 같은 장면의 다른 컷이면 0)
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from pathlib import Path

from curation import METHODS, add_common_args, available_methods, build_engine, params_hash

FIELDS = ["owner_scenes", "owner_hit", "owner_recall", "must_scenes", "must_hit", "must_recall",
          "dup", "exact", "unlabeled"]


def load_labels(path):
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    if d.get("format") != "j1-labels-v1":
        raise SystemExit(f"labeler.py로 만든 라벨 파일이 아닙니다: {path}")
    return d


def scene_map(labels):
    """사진 이름 -> 장면 번호. 장면은 촬영 순서상 연속 구간이며, 시작 사진으로 표시돼 있습니다."""
    starts = {s["start"]: s for s in labels.get("scenes", [])}
    smap, scenes = {}, []
    for i, name in enumerate(labels["order"]):
        if i == 0 or name in starts:
            s = starts.get(name, {})
            scenes.append({"title": (s.get("title") or "").strip() or f"장면 {len(scenes) + 1}",
                           "must": bool(s.get("must")), "start": name})
        smap[name] = len(scenes) - 1
    return smap, scenes


def score(picks, owner_picks, smap, scenes):
    alg = [smap.get(n) for n in picks]
    alg_set = {s for s in alg if s is not None}
    owner = {smap[n] for n in owner_picks if n in smap}
    must = {i for i, s in enumerate(scenes) if s["must"]}
    labeled = [s for s in alg if s is not None]
    return {
        "owner_scenes": len(owner),
        "owner_hit": len(owner & alg_set),
        "owner_recall": len(owner & alg_set) / len(owner) if owner else math.nan,
        "must_scenes": len(must),
        "must_hit": len(must & alg_set),
        "must_recall": len(must & alg_set) / len(must) if must else math.nan,
        "dup": len(labeled) - len(alg_set),
        "exact": len(set(picks) & set(owner_picks)),
        "unlabeled": len(alg) - len(labeled),
        "missed_owner": [scenes[i]["title"] for i in sorted(owner - alg_set)],
        "missed_must": [scenes[i]["title"] for i in sorted(must - alg_set)],
    }


def _mean(xs):
    xs = [x for x in xs if not (isinstance(x, float) and math.isnan(x))]
    return statistics.fmean(xs) if xs else math.nan


def average_random(engine, owner_picks, smap, scenes, seeds):
    runs = []
    for seed in range(seeds):
        names = [engine.photos[i].name for i in engine.run("random", seed=seed)["picks"]]
        runs.append(score(names, owner_picks, smap, scenes))
    out = {f: _mean([r[f] for r in runs]) for f in FIELDS}
    recalls = [r["owner_recall"] for r in runs if not math.isnan(r["owner_recall"])]
    out["owner_recall_sd"] = statistics.pstdev(recalls) if recalls else math.nan
    out["missed_owner"], out["missed_must"] = [], []
    return out


def _fmt_ratio(hit, total, recall, is_avg):
    if isinstance(total, float) and math.isnan(total) or not total:
        return "-"
    if is_avg:
        return f"{recall:.2f}"
    return f"{hit}/{total} ({recall:.2f})"


def print_table(rows, title):
    print(f"\n### {title}")
    print("| 방식 | 주인 장면 적중 | 필수 장면 적중 | 장면 중복 | 같은 사진 |")
    print("|---|---|---|---|---|")
    for m, r in rows:
        avg = m == "random" or r.get("_macro")
        own = _fmt_ratio(r["owner_hit"], r["owner_scenes"], r["owner_recall"], avg)
        if m == "random" and not r.get("_macro") and not math.isnan(r.get("owner_recall_sd", math.nan)):
            own += f" ± {r['owner_recall_sd']:.2f}"
        must = _fmt_ratio(r["must_hit"], r["must_scenes"], r["must_recall"], avg)
        dup = f"{r['dup']:.1f}" if avg else str(r["dup"])
        exact = f"{r['exact']:.1f}" if avg else str(r["exact"])
        print(f"| {m} | {own} | {must} | {dup} | {exact} |")


def main(argv=None):
    ap = argparse.ArgumentParser(description="초안 10장 평가 (앨범 폴더와 라벨 파일을 짝지어 입력)")
    ap.add_argument("pairs", nargs="+", metavar="ALBUM LABELS", help="앨범 폴더 라벨.json [앨범 폴더 라벨.json ...]")
    add_common_args(ap)
    ap.add_argument("--methods", default="all", help="쉼표로 구분 (기본 all)")
    ap.add_argument("--out", help="결과 CSV 경로 (기본 <work>/eval_<params_hash>.csv)")
    args = ap.parse_args(argv)
    if len(args.pairs) % 2:
        raise SystemExit("앨범 폴더와 라벨 파일을 짝지어 넣어 주세요.")

    all_rows, per_method = [], {}
    phash = emb_name = None
    for album_dir, labels_path in zip(args.pairs[::2], args.pairs[1::2]):
        labels = load_labels(labels_path)
        engine, _, emb_name = build_engine(album_dir, args.embedder, args.params, args.work, args.clip_model)
        phash = params_hash(engine.p)
        smap, scenes = scene_map(labels)
        owner_picks = labels.get("picks", [])
        names = {p.name for p in engine.photos}
        not_labeled = names - set(smap)
        missing = set(labels["order"]) - names
        print(f"\n== {engine.album.root.name}: 사진 {len(engine.photos)}장, 장면 {len(scenes)}개, "
              f"주인 선택 {len(owner_picks)}장, 필수 장면 {sum(s['must'] for s in scenes)}개")
        if not_labeled:
            print(f"! 라벨에 없는 사진 {len(not_labeled)}장 (초안에 들어가면 'unlabeled'로 셉니다)")
        if missing:
            print(f"! 라벨에는 있지만 지금 앨범에 없는 사진 {len(missing)}장")
        if len(owner_picks) != labels.get("k", engine.p["k"]):
            print(f"! 주인이 고른 사진이 {len(owner_picks)}장입니다.")

        rows = []
        for m in available_methods(engine.emb is not None, args.methods):
            if m == "random":
                r = average_random(engine, owner_picks, smap, scenes, engine.p["random_seeds"])
            else:
                picks = [engine.photos[i].name for i in engine.run(m)["picks"]]
                r = score(picks, owner_picks, smap, scenes)
            rows.append((m, r))
            per_method.setdefault(m, []).append(r)
            all_rows.append({"album": engine.album.root.name, "method": m, "embedder": emb_name,
                             "params_hash": phash, **{f: r[f] for f in FIELDS},
                             "missed_owner": " / ".join(r["missed_owner"]),
                             "missed_must": " / ".join(r["missed_must"])})
        print_table(rows, f"{engine.album.root.name} (임베딩 {emb_name}, 파라미터 {phash})")
        print("\n놓친 장면 (주인이 고른 장면 기준)")
        for m, r in rows:
            if m != "random":
                print(f"  {m}: {', '.join(r['missed_owner']) or '없음'}")

    if len(args.pairs) > 2:
        macro = []
        for m, rs in per_method.items():
            r = {f: _mean([x[f] for x in rs]) for f in FIELDS}
            r["_macro"] = True
            macro.append((m, r))
        print_table(macro, f"앨범 {len(args.pairs) // 2}개 평균 (앨범별 비율의 평균)")

    out = Path(args.out) if args.out else Path(args.work) / f"eval_{phash}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(all_rows[0]))
        w.writeheader()
        w.writerows(all_rows)
    print(f"\nCSV: {out.resolve()}")
    print("방식 설명: " + "; ".join(f"{m}={METHODS[m]['desc']}" for m in per_method))


if __name__ == "__main__":
    sys.exit(main())
