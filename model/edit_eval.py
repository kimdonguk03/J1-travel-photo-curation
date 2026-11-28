#!/usr/bin/env python3
"""편집 실험 분석: 앱에 저장된 큐레이션 기록으로 편집 시간과 복구한 장면을 셉니다.

  # 1) 백엔드에서 기록 받기 (관리자 토큰은 환경 변수 J1_ADMIN_TOKEN과 같은 값)
  curl.exe -H "X-J1-Admin: <토큰>" http://localhost:8080/api/admin/curations.json -o curations.json

  # 2) 시간 비교 (모든 기록)
  py edit_eval.py curations.json

  # 3) 복구한 장면 (평가 앨범 편집 세션: 큐레이션 id와 그 앨범의 owner.csv를 짝지어)
  py edit_eval.py curations.json --pair 7 owner_trip_a.csv --pair 9 owner_trip_b.csv

시간 비교 (참가자 = 같은 브라우저의 게스트 ID)
  총시간     불러오기 시작 ~ 확정 (업로드·추천 대기 포함)
  편집 시간  편집 화면 준비 ~ 확정 (실제로 고른 시간)
  참가자마다 직접 고르기(manual)와 추천 편집(recommend)을 비교합니다. 둘 다 한 참가자만 짝으로 셉니다.

복구한 장면 (추천 편집 기록만)
  초안 장면    초안 사진이 인정 컷으로 들어 있는 중요 장면
  최종 장면    최종 사진이 인정 컷으로 들어 있는 중요 장면
  복구한 장면  최종에는 있고 초안에는 없던 장면 (빠진 장면 복구의 효과)
  잃은 장면    초안에는 있었는데 최종에서 빠진 장면
  컷 교체      초안 장면 안에서 다른 컷으로 바꾼 사진 수
  사진은 파일 이름(경로 없이, 대소문자 무시)으로 owner.csv와 맞춥니다.

받은 curations.json과 owner.csv에는 사진 파일 이름이 들어 있으므로 저장소에 올리지 않습니다.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime
from pathlib import Path

import evaluate as E


def seconds(start: str, end: str):
    if not start or not end:
        return None
    a = datetime.fromisoformat(start.replace("Z", "+00:00"))
    b = datetime.fromisoformat(end.replace("Z", "+00:00"))
    return (b - a).total_seconds()


def base(name: str) -> str:
    return name.replace("\\", "/").rsplit("/", 1)[-1].lower()


def scenes_of(names, owner) -> set:
    """사진 이름 목록이 인정 컷으로 들어 있는 중요 장면 id 집합."""
    have = {base(n) for n in names}
    return {sid for sid, cuts in owner.scenes.items() if any(base(c) in have for c in cuts)}


def scene_of_photo(name, owner):
    b = base(name)
    return {sid for sid, cuts in owner.scenes.items() if any(base(c) == b for c in cuts)}


def recovery(rec: dict, owner) -> dict:
    draft, final = rec.get("draftNames") or [], rec.get("finalNames") or []
    ds, fs = scenes_of(draft, owner), scenes_of(final, owner)
    draft_b = {base(n) for n in draft}
    swaps = sum(1 for n in final if base(n) not in draft_b and scene_of_photo(n, owner) & ds)
    known = {base(c) for cuts in owner.scenes.values() for c in cuts}
    matched = sum(1 for n in draft + final if base(n) in known)
    return {"scenes": len(owner.scenes), "draft": len(ds), "final": len(fs), "recovered": len(fs - ds),
            "lost": len(ds - fs), "swaps": swaps, "changed": len(set(map(base, final)) - draft_b),
            "matched_names": matched, "recovered_ids": sorted(fs - ds), "lost_ids": sorted(ds - fs)}


def fmt(x):
    return "-" if x is None else f"{x:.0f}"


def time_report(records):
    by_user = {}
    for r in records:
        r = dict(r, total=seconds(r.get("loadedAt"), r.get("confirmedAt")), edit=seconds(r.get("readyAt"), r.get("confirmedAt")))
        by_user.setdefault(r["owner"], {}).setdefault(r["mode"], []).append(r)

    print("### 편집 시간 (초, 참가자별)")
    print("| 참가자 | 직접 고르기 총시간 / 편집 | 추천 편집 총시간 / 편집 | 만족도 직접 / 추천 | 추천 편집이 빠름 (편집 시간) |")
    print("|---|---|---|---|---|")
    pairs = []
    for n, (user, modes) in enumerate(sorted(by_user.items()), 1):
        m = modes.get("manual", [None])[-1]   # 같은 모드를 여러 번 했으면 마지막 기록
        r = modes.get("recommend", [None])[-1]
        cell = lambda x: f"{fmt(x['total'])} / {fmt(x['edit'])}" if x else "-"  # noqa: E731
        sat = lambda x: str(x["satisfaction"]) if x and x.get("satisfaction") else "-"  # noqa: E731
        faster = "-"
        if m and r and m["edit"] is not None and r["edit"] is not None:
            pairs.append((m, r))
            faster = "예" if r["edit"] < m["edit"] else ("같음" if r["edit"] == m["edit"] else "아니오")
        print(f"| P{n} | {cell(m)} | {cell(r)} | {sat(m)} / {sat(r)} | {faster} |")
    if pairs:
        med = lambda xs: statistics.median(xs) if xs else None  # noqa: E731
        print(f"\n두 방식을 모두 한 참가자 {len(pairs)}명:")
        for key, label in [("total", "총시간"), ("edit", "편집 시간")]:
            mm = med([m[key] for m, _ in pairs if m[key] is not None])
            rr = med([r[key] for _, r in pairs if r[key] is not None])
            print(f"- {label} 중앙값: 직접 고르기 {fmt(mm)}초, 추천 편집 {fmt(rr)}초")
        faster = sum(1 for m, r in pairs if r["edit"] < m["edit"])
        print(f"- 추천 편집의 편집 시간이 더 짧았던 참가자: {faster}/{len(pairs)}명")
        sats = [(m.get("satisfaction"), r.get("satisfaction")) for m, r in pairs if m.get("satisfaction") and r.get("satisfaction")]
        if sats:
            print(f"- 만족도 평균: 직접 고르기 {statistics.fmean(s for s, _ in sats):.1f}, 추천 편집 {statistics.fmean(s for _, s in sats):.1f} ({len(sats)}명)")
    else:
        print("\n두 방식을 모두 한 참가자가 없어 짝 비교는 하지 않았습니다.")


def main(argv=None):
    ap = argparse.ArgumentParser(description="편집 실험 분석 (시간 비교, 복구한 장면)")
    ap.add_argument("curations", help="백엔드 /api/admin/curations.json으로 받은 파일")
    ap.add_argument("--pair", nargs=2, action="append", default=[], metavar=("CURATION_ID", "OWNER_CSV"),
                    help="복구한 장면을 셀 큐레이션 id와 그 앨범의 owner.csv")
    ap.add_argument("--skip-time", action="store_true", help="시간 비교를 건너뜀")
    args = ap.parse_args(argv)

    records = json.loads(Path(args.curations).read_text(encoding="utf-8"))
    print(f"기록 {len(records)}건 (직접 고르기 {sum(r['mode'] == 'manual' for r in records)}, "
          f"추천 편집 {sum(r['mode'] == 'recommend' for r in records)})\n")
    if not args.skip_time:
        time_report(records)

    if args.pair:
        by_id = {str(r["id"]): r for r in records}
        print("\n### 복구한 장면 (추천 초안 → 주인이 편집한 최종본)")
        print("| 큐레이션 | 중요 장면 | 초안 장면 | 최종 장면 | 복구한 장면 | 잃은 장면 | 컷 교체 | 바꾼 사진 |")
        print("|---|---|---|---|---|---|---|---|")
        tot = {k: 0 for k in ("scenes", "draft", "final", "recovered", "lost", "swaps", "changed")}
        notes = []
        for cid, owner_csv in args.pair:
            rec = by_id.get(cid)
            if rec is None:
                raise SystemExit(f"큐레이션 id {cid}가 기록에 없습니다.")
            if rec["mode"] != "recommend":
                raise SystemExit(f"큐레이션 {cid}는 직접 고르기 기록이라 초안이 없습니다.")
            owner = E.load_owner_csv(owner_csv)
            r = recovery(rec, owner)
            for k in tot:
                tot[k] += r[k]
            print(f"| {cid} ({rec['title']}) | {r['scenes']} | {r['draft']} | {r['final']} | {r['recovered']} | "
                  f"{r['lost']} | {r['swaps']} | {r['changed']} |")
            if r["matched_names"] == 0:
                notes.append(f"! 큐레이션 {cid}: 사진 이름이 owner.csv와 하나도 맞지 않습니다. 앨범과 정답 파일 짝을 확인하세요.")
            if r["recovered_ids"] or r["lost_ids"]:
                notes.append(f"- {cid}: 복구 {', '.join(r['recovered_ids']) or '없음'} / 잃음 {', '.join(r['lost_ids']) or '없음'}")
        if len(args.pair) > 1:
            print(f"| 합계 | {tot['scenes']} | {tot['draft']} | {tot['final']} | {tot['recovered']} | {tot['lost']} | "
                  f"{tot['swaps']} | {tot['changed']} |")
        if notes:
            print("\n" + "\n".join(notes))
        print("\n컷 교체 = 초안이 이미 담은 장면 안에서 다른 컷으로 바꾼 사진 수. 바꾼 사진 = 초안에 없던 최종 사진 수.")


if __name__ == "__main__":
    sys.exit(main())
