#!/usr/bin/env python3
"""평가 앨범에서 각 방식의 초안이 앨범 주인의 owner.csv를 얼마나 담았는지 계산합니다.

  py evaluate.py "C:\\Photos\\제주" owner_제주.csv "C:\\Photos\\부산" owner_부산.csv --params params.json

앨범 폴더와 owner.csv를 짝지어 여러 개 넣을 수 있습니다. 개발(튜닝)에 쓴 앨범은 넣지 마세요.

owner.csv: album_id, scene_id, relpath, owner_pick
  scene_id    앨범 주인이 인정하는 중요 장면. 같은 장면을 대신할 수 있는 컷은 같은 scene_id로 적습니다.
  relpath     앨범 루트 기준 상대 경로 (구분자 /)
  owner_pick  주인이 직접 고른 컷이면 1

지표
  장면 적중   초안 K장이 인정 컷을 하나 이상 담은 중요 장면 수 / 중요 장면 수
  일치한 컷   초안 K장 중 owner_pick=1인 사진과 같은 사진 수 / owner_pick 수

방식: uniform(촬영 순번 균등 추출), time(시간 묶기), time_clip(시간+CLIP 묶기, 제안), random(참고).
time과 time_clip은 묶기 이후의 선택 규칙이 같습니다.
"""
from __future__ import annotations

import argparse
import csv
import dataclasses
import statistics
import sys
from pathlib import Path

import recommend as R

ORDER = ["random", "uniform", "time", "time_clip"]


@dataclasses.dataclass
class Owner:
    album_ids: set
    scenes: dict   # scene_id -> {relpath}
    picks: set     # owner_pick = 1인 relpath


def load_owner_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        need = {"album_id", "scene_id", "relpath", "owner_pick"}
        if not need <= set(reader.fieldnames or []):
            raise SystemExit(f"{path}: 열이 {sorted(need)}여야 합니다 (현재 {reader.fieldnames}).")
        rows = list(reader)
    scenes, picks, albums = {}, set(), set()
    for r in rows:
        rel = (r["relpath"] or "").strip().replace("\\", "/")
        if not rel:
            continue
        sid = (r["scene_id"] or "").strip()
        if sid:
            scenes.setdefault(sid, set()).add(rel)
        if (r["owner_pick"] or "").strip().lower() in ("1", "true", "y", "yes"):
            picks.add(rel)
        albums.add((r["album_id"] or "").strip())
    return Owner(albums, scenes, picks)


def score_draft(draft_relpaths, owner):
    d = set(draft_relpaths)
    hit = {s for s, cuts in owner.scenes.items() if cuts & d}
    return {"scene_hits": len(hit), "scenes": len(owner.scenes),
            "matched": len(d & owner.picks), "picks": len(owner.picks),
            "missed": sorted(s for s in owner.scenes if s not in hit)}


def _ratio(a, b):
    return a / b if b else float("nan")


def main(argv=None):
    ap = argparse.ArgumentParser(description="초안 평가 (앨범 폴더와 owner.csv를 짝지어 입력)")
    ap.add_argument("pairs", nargs="+", metavar="ALBUM OWNER_CSV")
    ap.add_argument("--embedder", choices=["clip", "tiny", "none"], default="clip")
    ap.add_argument("--clip-model")
    ap.add_argument("--params", help="파라미터 JSON (평가 전에 고정)")
    ap.add_argument("--cache", default=str(R.DEFAULT_CACHE))
    ap.add_argument("--out", help="결과 CSV (기본 j1_out/eval_<rule hash>.csv)")
    args = ap.parse_args(argv)
    if len(args.pairs) % 2:
        raise SystemExit("앨범 폴더와 owner.csv를 짝지어 넣어 주세요.")

    rows, per_method, version = [], {}, None
    for album, owner_csv in zip(args.pairs[::2], args.pairs[1::2]):
        owner = load_owner_csv(owner_csv)
        photos, videos, failed = R.photos_from_folder(album)
        a = R.analyze(photos, embedder=args.embedder, clip_model=args.clip_model, cache_dir=args.cache,
                      params=args.params, drop_failed=True)
        version = a.rule_version
        k = a.default_k()
        rels = {it.relpath for it in a.items}
        listed = set().union(*owner.scenes.values()) | owner.picks if owner.scenes or owner.picks else set()
        print(f"\n== {Path(album).name} (album_id {', '.join(sorted(owner.album_ids)) or '-'}): "
              f"사진 {len(a.items)}장, K={k}, 중요 장면 {len(owner.scenes)}개, 주인 선택 {len(owner.picks)}장")
        if listed - rels:
            print(f"! owner.csv의 상대 경로 {len(listed - rels)}개가 앨범에 없습니다: {sorted(listed - rels)[:3]}")
        if not owner.scenes:
            print("! 중요 장면이 없어 장면 점수는 결측입니다.")

        methods = [m for m in ORDER if a.emb is not None or m not in R.NEEDS_EMBEDDING]
        print("| 방식 | 장면 적중 | 일치한 컷 | 놓친 장면 |")
        print("|---|---|---|---|")
        for m in methods:
            if m == "random":
                runs = [score_draft([a.items[i].relpath for i in a.run(m, k, seed=s)], owner)
                        for s in range(a.params["random_seeds"])]
                r = {key: statistics.fmean(x[key] for x in runs) for key in ("scene_hits", "matched")}
                r.update(scenes=len(owner.scenes), picks=len(owner.picks), missed=[])
                print(f"| random | {r['scene_hits']:.1f}/{r['scenes']} | {r['matched']:.1f}/{r['picks']} | (시드 평균) |")
            else:
                r = score_draft([a.items[i].relpath for i in a.run(m, k)], owner)
                print(f"| {m} | {r['scene_hits']}/{r['scenes']} | {r['matched']}/{r['picks']} | "
                      f"{', '.join(r['missed']) or '없음'} |")
            per_method.setdefault(m, []).append(r)
            rows.append({"album": Path(album).name, "album_id": ";".join(sorted(owner.album_ids)), "method": m,
                         "rule_version": version, "k": k, "scene_hits": r["scene_hits"], "scenes": r["scenes"],
                         "matched": r["matched"], "picks": r["picks"], "missed": " / ".join(r["missed"])})

    if len(args.pairs) > 2:
        print(f"\n### 앨범 {len(args.pairs) // 2}개 평균 (앨범별 비율의 평균)")
        print("| 방식 | 장면 적중률 | 일치한 컷 비율 |")
        print("|---|---|---|")
        for m, rs in per_method.items():
            sh = statistics.fmean(_ratio(x["scene_hits"], x["scenes"]) for x in rs)
            mc = statistics.fmean(_ratio(x["matched"], x["picks"]) for x in rs)
            print(f"| {m} | {sh:.2f} | {mc:.2f} |")

    out = Path(args.out) if args.out else Path("j1_out") / f"eval_{version.split('/')[-1]}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"\nrule_version: {version}\nCSV: {out.resolve()}")


if __name__ == "__main__":
    sys.exit(main())
