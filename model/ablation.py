#!/usr/bin/env python3
"""기여도 비교 (ablation): 점수를 하나씩 끄고 평가 앨범에서 지표가 어떻게 바뀌는지 봅니다.

  py ablation.py "C:\\Photos\\trip_a" owner_trip_a.csv "C:\\Photos\\trip_b" owner_trip_b.csv --out ablation.csv

설명용입니다. docs/experiments.md의 판정 규칙대로 이 결과로 추천 규칙을 바꾸지 않습니다.
특징(CLIP, 선명도)은 앨범마다 한 번만 계산하고, 변형마다 묶기·대표 컷·선택만 다시 합니다.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import evaluate as E
import recommend as R

# (이름, 기본 파라미터에서 바꿀 값)
VARIANTS = [
    ("제안 방식 (전체)", {}),
    ("미적 점수 끔", {"aesthetic_weight": 0.0}),
    ("화질 점수 끔", {"quality_weight": 0.0}),
    ("화질·미적 점수 끔 (초안 평가의 no_quality)", {"quality_weight": 0.0, "aesthetic_weight": 0.0}),
    ("내용 점수 끔", {"content_weight": 0.0}),
    ("순위 모델 대신 선명도 (r3 대표 컷)", {"rank_model": "sharpness"}),
    ("크기 점수만 (내용·화질·미적 끔)", {"content_weight": 0.0, "quality_weight": 0.0, "aesthetic_weight": 0.0}),
]


def main(argv=None):
    ap = argparse.ArgumentParser(description="기여도 비교 (점수를 하나씩 끄고 비교)")
    ap.add_argument("pairs", nargs="+", metavar="ALBUM OWNER_CSV")
    ap.add_argument("--params", help="기준 파라미터 JSON (기본 params.json)")
    ap.add_argument("--cache", default=str(R.DEFAULT_CACHE))
    ap.add_argument("--clip-model")
    ap.add_argument("--embedder", choices=["clip", "tiny"], default="clip")
    ap.add_argument("--out", help="결과 CSV")
    args = ap.parse_args(argv)
    if len(args.pairs) % 2:
        raise SystemExit("앨범 폴더와 owner.csv를 짝지어 넣어 주세요.")

    base_params = R.load_params(args.params or Path(__file__).with_name("params.json"))
    rows, totals = [], {}
    for album, owner_csv in zip(args.pairs[::2], args.pairs[1::2]):
        owner = E.load_owner_csv(owner_csv)
        photos, _, _ = R.photos_from_folder(album)
        a = R.analyze(photos, embedder=args.embedder, clip_model=args.clip_model, cache_dir=args.cache,
                      params=base_params, drop_failed=True)
        k = a.default_k()
        name = Path(album).name
        print(f"\n== {name}: 사진 {len(a.items)}장, K={k}, 중요 장면 {len(owner.scenes)}개, 주인 선택 {len(owner.picks)}장")
        print("| 변형 | 같은 순간 | 장면 적중 | 일치한 컷 | 선명도 백분위 | 제안 방식과 다른 초안 사진 |")
        print("|---|---|---|---|---|---|")
        base_draft = None
        for label, change in VARIANTS:
            params = R.load_params(dict(base_params, **change))
            v = R.Analysis(a.items, a.sharp, a.emb, params, a.failed, a.timing, a.embedder_name)
            draft = v.run("time_clip", k)
            base_draft = base_draft if base_draft is not None else set(draft)
            s = E.score_draft([v.items[i].relpath for i in draft], owner)
            moment = E.moment_hits(v, draft, owner)
            sp = E.sharp_percentile(v, draft)
            diff = len(set(draft) - base_draft)
            print(f"| {label} | {moment}/{s['picks']} | {s['scene_hits']}/{s['scenes']} | {s['matched']}/{s['picks']} | "
                  f"{sp:.0f} | {diff} |")
            t = totals.setdefault(label, [0, 0, 0, 0, 0])
            for j, x in enumerate((moment, s["picks"], s["scene_hits"], s["scenes"], s["matched"])):
                t[j] += x
            rows.append({"album": name, "variant": label, "rule_version": v.rule_version, "k": k, "moment_hits": moment,
                         "picks": s["picks"], "scene_hits": s["scene_hits"], "scenes": s["scenes"],
                         "matched": s["matched"], "sharp_pct": round(sp, 1), "changed_vs_full": diff})

    if len(args.pairs) > 2:
        print(f"\n### 앨범 {len(args.pairs) // 2}개 합계")
        print("| 변형 | 같은 순간 | 장면 적중 | 일치한 컷 |")
        print("|---|---|---|---|")
        for label, (mo, pk, sh, sc, mc) in totals.items():
            print(f"| {label} | {mo}/{pk} | {sh}/{sc} | {mc}/{pk} |")
    print("\n설명용 결과입니다. 이 결과로 추천 규칙을 바꾸지 않습니다 (docs/experiments.md 판정 규칙).")
    if args.out:
        with open(args.out, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        print(f"CSV: {args.out}")


if __name__ == "__main__":
    sys.exit(main())
