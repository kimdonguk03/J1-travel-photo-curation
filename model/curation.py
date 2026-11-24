#!/usr/bin/env python3
"""개발 앨범 점검 화면: 묶음, 기준값 근처 경계 사례, 방식별 초안, 처리 시간.

  py curation.py "C:\\Photos\\개발30장"
  py curation.py "C:\\Photos\\개발30장" --embedder tiny     # 모델 없이 흐름만 (보고용 아님)

결과는 j1_out\\<앨범>_<해시>\\ 에 저장합니다. 원본 폴더에는 아무것도 쓰지 않습니다.
  clusters.html          시간 구간·묶음·대표 컷 순위와 '0.92 근처' 경계 사례. 실제 연사가 갈라졌는지,
                         같은 장소의 다른 장면이 합쳐졌는지를 여기서 봅니다.
  compare.html           방식별 초안 (균등 추출 / 시간 묶기 / 시간+CLIP / 무작위)
  recommend_result.json  recommend() 반환 예시
  picks.json             방식별 초안 상대 경로
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import html
import io
import json
import re
import sys
from pathlib import Path

from PIL import Image

import recommend as R

CSS = """
:root{--bg:#f7f7f5;--fg:#1d1d1b;--muted:#6a6a64;--card:#fff;--line:#e2e2dd;--accent:#b45309;--ok:#15803d;--bad:#b91c1c}
@media (prefers-color-scheme:dark){:root{--bg:#151514;--fg:#ebebe8;--muted:#9b9b94;--card:#1f1f1d;--line:#33332f;--accent:#f59e0b;--ok:#4ade80;--bad:#f87171}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,"Malgun Gothic",sans-serif}
main{max-width:1400px;margin:0 auto;padding:16px}h1{font-size:20px;margin:0 0 4px}h2{font-size:16px;margin:22px 0 8px}
.meta{color:var(--muted);white-space:pre-wrap;margin:0 0 12px}.warn{color:var(--accent);font-weight:600}
section{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px;margin:0 0 10px}
h3{font-size:14px;margin:0 0 6px}h3 span{color:var(--muted);font-weight:400;margin-left:6px}
.row{display:flex;gap:8px;flex-wrap:wrap;align-items:flex-start}.grp{border:1px dashed var(--line);border-radius:8px;padding:6px;display:flex;gap:6px;flex-wrap:wrap}
figure{margin:0;width:132px}figure img{width:132px;height:132px;object-fit:cover;border-radius:6px;display:block}
figure.rep img{outline:3px solid var(--accent);outline-offset:-3px}
figcaption{font-size:11.5px;color:var(--muted);margin-top:2px;line-height:1.35;word-break:break-all}
.pair{display:flex;gap:6px;align-items:center;border:1px solid var(--line);border-radius:8px;padding:6px}
.sim{font-weight:700;font-variant-numeric:tabular-nums;min-width:110px;text-align:center}.in{color:var(--ok)}.out{color:var(--bad)}
"""


def album_out_dir(work, root):
    root = Path(root).resolve()
    base = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", root.name) or "album"
    return Path(work) / f"{base}_{hashlib.sha1(str(root).encode('utf-8')).hexdigest()[:6]}"


class Thumbs:
    def __init__(self, analysis, cache_dir, side=160):
        self.a, self.cache, self.side, self.memo = analysis, Path(cache_dir), side, {}

    def __call__(self, i):
        if i not in self.memo:
            path = R.work_image_path(self.cache, R._photo_key(self.a.items[i].path))
            with Image.open(path) as im:
                im = im.convert("RGB")
            im.thumbnail((self.side, self.side))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=72)
            self.memo[i] = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
        return self.memo[i]


def when(it):
    return "촬영 시각 미상" if it.local is None else f"{it.local:%m/%d %H:%M:%S}"


def fig(thumb, i, it, caption, rep=False):
    return (f'<figure class="{"rep" if rep else ""}"><img src="{thumb(i)}" alt="" loading="lazy" '
            f'title="{html.escape(it.relpath)}"><figcaption>{caption}</figcaption></figure>')


def page(title, meta, body):
    return (f'<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" '
            f'content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title><style>{CSS}</style>'
            f'</head><body><main><h1>{html.escape(title)}</h1><p class="meta">{meta}</p>{body}</main></body></html>')


def clusters_html(a, thumb, root_name):
    groups, ranked, diag = a.groups("time_clip")
    th = a.params["clip_sim"]
    segs = R.time_segments(a.items, a.params)
    seg_of = {i: n for n, seg in enumerate(segs) for i in seg}
    parts = []

    # 경계 사례: 기준 컷과의 유사도가 th-0.06 ~ th+0.04
    border = sorted((i for i, d in diag.items() if d["sim"] is not None and th - 0.06 <= d["sim"] < th + 0.04),
                    key=lambda i: -diag[i]["sim"])
    parts.append(f"<h2>경계 사례 ({th - 0.06:.2f} ~ {th + 0.04:.2f}) {len(border)}건</h2>")
    parts.append('<p class="meta">왼쪽이 묶음의 기준 컷, 오른쪽이 비교한 사진입니다. 초록은 같은 묶음에 들어간 경우, '
                 '빨강은 따로 남은 경우입니다. 같은 연사인데 빨강이거나 다른 장면인데 초록이면 기준값을 의심하세요.</p>')
    cells = []
    for i in border:
        d = diag[i]
        ref = groups[d["nearest"]][0]
        joined = d["group"] == d["nearest"]
        cells.append(f'<div class="pair">{fig(thumb, ref, a.items[ref], html.escape(a.items[ref].relpath))}'
                     f'<div class="sim {"in" if joined else "out"}">{d["sim"]:.3f}<br>{"같은 묶음" if joined else "따로"}</div>'
                     f'{fig(thumb, i, a.items[i], html.escape(a.items[i].relpath))}</div>')
    parts.append(f'<div class="row">{"".join(cells) or "<p class=meta>없음</p>"}</div>')

    # 시간 구간별 묶음
    parts.append(f"<h2>시간 구간 {len(segs)}개 · 묶음 {len(groups)}개</h2>")
    by_seg = {}
    for g, members in enumerate(groups):
        by_seg.setdefault(seg_of.get(members[0], "unknown"), []).append(g)
    for key in list(range(len(segs))) + (["unknown"] if "unknown" in by_seg else []):
        gs = by_seg.get(key, [])
        if key == "unknown":
            head = f"촬영 시각 미상 <span>{len(gs)}장, 각자 단독 후보</span>"
        else:
            first, last = a.items[segs[key][0]], a.items[segs[key][-1]]
            head = (f"구간 {key + 1} <span>{first.local:%m/%d %H:%M:%S} ~ {last.local:%H:%M:%S} · "
                    f"{len(segs[key])}장 → 묶음 {len(gs)}개</span>")
        rows = []
        for g in gs:
            figs = []
            for rank, i in enumerate(ranked[g], 1):
                s = diag[i]["sim"]
                if i == groups[g][0]:
                    rel = "기준 컷" + (f" (앞 기준과 {s:.3f})" if s is not None else "")
                else:
                    rel = f"기준과 {s:.3f}"
                cap = f"#{rank}{' 대표' if rank == 1 else ''} · 선명도 {a.sharp[i]:.0f}<br>{rel}<br>{when(a.items[i])}"
                figs.append(fig(thumb, i, a.items[i], cap, rep=(rank == 1)))
            rows.append(f'<div class="grp">{"".join(figs)}</div>')
        parts.append(f'<section><h3>{head}</h3><div class="row">{"".join(rows)}</div></section>')
    meta = (f"rule_version {html.escape(a.rule_version)} · 사진 {len(a.items)}장 · 기준값 {th} · "
            f"구간 한도 {a.params['seg_gap_sec']}초/{a.params['seg_span_sec']}초\n"
            "묶음 안 순서는 대표 컷 순위(선명도)이며 주황 테두리가 대표 컷입니다.")
    return page(f"묶음 점검 · {root_name}", meta, "".join(parts))


def compare_html(a, thumb, results, root_name, k):
    parts = []
    for m, draft in results.items():
        figs = "".join(fig(thumb, i, a.items[i], f"{when(a.items[i])}<br>{html.escape(a.items[i].relpath)}")
                       for i in draft)
        parts.append(f'<section><h3>{m}<span>{html.escape(R.METHODS[m])}</span></h3><div class="row">{figs}</div></section>')
    meta = (f"rule_version {html.escape(a.rule_version)} · 사진 {len(a.items)}장 · K={k}\n"
            '<span class="warn">평가 앨범이라면 앨범 주인의 owner.csv를 받기 전에는 이 화면을 보여주지 마세요.</span>')
    return page(f"초안 비교 · {root_name}", meta, "".join(parts))


def main(argv=None):
    ap = argparse.ArgumentParser(description="개발 앨범 점검: 묶음·경계 사례·방식별 초안")
    ap.add_argument("album")
    ap.add_argument("--embedder", choices=["clip", "tiny"], default="clip")
    ap.add_argument("--clip-model")
    ap.add_argument("--params")
    ap.add_argument("--cache", default=str(R.DEFAULT_CACHE))
    ap.add_argument("--work", default="j1_out")
    args = ap.parse_args(argv)
    if args.embedder == "tiny":
        print("! tiny 임베딩은 흐름 점검용입니다. 결과를 발표 수치로 쓰지 마세요.")

    photos, videos, failed = R.photos_from_folder(args.album)
    print(f"사진 {len(photos)}장, 동영상 {videos}개, 읽기 실패 {len(failed)}장")
    for rel, why in failed[:5]:
        print(f"  - {rel}: {why}")
    a = R.analyze(photos, embedder=args.embedder, clip_model=args.clip_model, cache_dir=args.cache,
                  params=args.params, drop_failed=True, log=print)
    if a.failed:
        print(f"디코딩 실패 {len(a.failed)}장 (제외): {', '.join(a.failed[:5])}")
    t = a.timing
    print(f"시간: 모델 로딩 {t['model_load_s']:.2f}s | 원본 디코딩 {t['decode_s']:.2f}s ({t['decoded']}장) | "
          f"CLIP 추론 {t['embed_s']:.2f}s ({t['embedded']}장)  * 캐시에 없던 사진만 계산")
    if t["decoded"]:
        print(f"      1장당 디코딩 {t['decode_s'] / t['decoded'] * 1000:.0f}ms(4스레드 병렬)", end="")
        print(f", 추론 {t['embed_s'] / t['embedded'] * 1000:.0f}ms" if t["embedded"] else "")
    unknown = sum(1 for it in a.items if it.t is None)
    k = a.default_k()
    g_time, g_clip = len(a.groups("time")[0]), len(a.groups("time_clip")[0])
    print(f"촬영 시각 미상 {unknown}장 | 시간 구간 {len(R.time_segments(a.items, a.params))}개 | "
          f"묶음: 시간 {g_time}개, 시간+CLIP {g_clip}개 | K={k}")

    results = {m: a.run(m, k) for m in ("uniform", "time", "time_clip", "random")}
    out = album_out_dir(args.work, args.album)
    out.mkdir(parents=True, exist_ok=True)
    thumb = Thumbs(a, args.cache)
    root_name = Path(args.album).resolve().name
    (out / "clusters.html").write_text(clusters_html(a, thumb, root_name), encoding="utf-8")
    (out / "compare.html").write_text(compare_html(a, thumb, results, root_name, k), encoding="utf-8")
    rec = {"clusters": a.clusters_json("time_clip"), "draft_ids": [a.items[i].photo_id for i in results["time_clip"]],
           "rule_version": a.rule_version}
    (out / "recommend_result.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    picks = {"rule_version": a.rule_version, "k": k,
             "methods": {m: [a.items[i].relpath for i in d] for m, d in results.items()}}
    (out / "picks.json").write_text(json.dumps(picks, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n결과: {out.resolve()}")
    print("  clusters.html (묶음·경계 사례), compare.html (방식별 초안), recommend_result.json (recommend 반환 예시)")
    print(f"rule_version: {a.rule_version}")


if __name__ == "__main__":
    sys.exit(main())
