#!/usr/bin/env python3
"""초안 수용률: 앨범 주인이 추천 초안 사진을 '건질 사진 / 별로 / 흔들림·흐림'으로 평가하는 페이지와 채점.

  py draft_review.py "C:\\Photos\\jeju_trip" --album-id jeju      # 평가 페이지 만들기
  py draft_review.py --score review_jeju.csv [review_busan.csv ...]  # 방식별 수용률 계산

페이지에는 세 방식의 초안 사진을 섞어서, 어느 방식이 고른 사진인지 모르게 보여줍니다.
  proposal    제안 방식 (params.json 그대로)
  no_quality  제안 방식에서 화질 점수만 끈 것 (quality_weight=0)
  uniform     촬영 순번 균등 추출 (기준선)
수용률 = 그 방식의 초안 K장 중 주인이 '건질 사진'으로 표시한 비율.
흔들림 = 그 방식의 초안 K장 중 주인이 '흔들림·흐림'으로 표시한 장수 (사람이 본 화질 지표).

이 페이지는 추천 결과를 보여주므로, 반드시 정답(owner.csv) 표시를 마친 뒤에 주인에게 보여주세요.
"""
from __future__ import annotations

import argparse
import base64
import csv
import html
import io
import json
import random
import statistics
import sys
from pathlib import Path

from PIL import Image

import recommend as R
from curation import album_out_dir

METHODS = ["proposal", "no_quality", "uniform"]
VERDICTS = ("keep", "drop", "blur")

PAGE = r"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
:root{--bg:#f7f7f5;--fg:#1d1d1b;--muted:#6a6a64;--card:#fff;--line:#deded8;--accent:#b45309;--keep:#16a34a;--drop:#dc2626;--blur:#7c3aed;--btn:#ececE8}
@media (prefers-color-scheme:dark){:root{--bg:#151514;--fg:#ebebe8;--muted:#9b9b94;--card:#1f1f1d;--line:#36362f;--accent:#f59e0b;--keep:#4ade80;--drop:#f87171;--blur:#a78bfa;--btn:#2c2c29}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,"Malgun Gothic",sans-serif}
header{position:sticky;top:0;z-index:5;background:var(--bg);border-bottom:1px solid var(--line);padding:8px 16px;display:flex;gap:12px;align-items:center;flex-wrap:wrap}
header strong{font-size:16px}.stat b{color:var(--accent)}
button{font:inherit;border:1px solid var(--line);background:var(--btn);color:var(--fg);border-radius:6px;padding:4px 12px;cursor:pointer}
button.primary{background:var(--accent);border-color:var(--accent);color:#fff}
main{max-width:1200px;margin:0 auto;padding:12px 16px 60px}
.help{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 14px;margin-bottom:14px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px}
.card{background:var(--card);border:3px solid transparent;border-radius:10px;padding:6px}
.card.keep{border-color:var(--keep)}.card.drop{border-color:var(--drop);opacity:.7}.card.blur{border-color:var(--blur);opacity:.7}
.card img{width:100%;aspect-ratio:4/3;object-fit:contain;background:rgba(127,127,127,.15);border-radius:6px;display:block}
.cap{font-size:12px;color:var(--muted);margin:4px 2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.acts{display:flex;gap:6px}.acts button{flex:1;padding:4px 6px}
.card.keep .k{background:var(--keep);border-color:var(--keep);color:#fff}.card.drop .d{background:var(--drop);border-color:var(--drop);color:#fff}.card.blur .b{background:var(--blur);border-color:var(--blur);color:#fff}
</style></head><body>
<header><strong>__ALBUM__</strong><span class="stat">평가 <b id="done">0</b>/__N__장 · 건질 사진 <b id="keeps">0</b>장</span>
<button class="primary" id="save">저장</button></header>
<main>
<div class="help"><b>하는 법</b> · 아래는 추천 프로그램이 고른 사진들을 섞어 놓은 것입니다(순서는 무작위).
사진마다 <b>이 여행을 친구에게 보여줄 10장에 넣어도 괜찮으면 '건질 사진'</b>, 흔들리거나 초점이 나갔으면 '흔들림·흐림', 그 밖의 이유로 빼고 싶으면 '별로'를 누르세요.
내가 고른 10장과 달라도 괜찮은 사진이면 '건질 사진'입니다. 다 누르면 [저장]을 누르고 파일을 보내 주세요.</div>
<div class="grid" id="grid"></div>
</main>
<script>
const ALBUM = __META__;
const PHOTOS = __PHOTOS__;
const KEY = "j1-review:" + ALBUM.file + ":" + ALBUM.rule_version;
let verdict = {};
try { verdict = JSON.parse(localStorage.getItem(KEY) || "{}") || {}; } catch (e) { verdict = {}; }
function persist() { try { localStorage.setItem(KEY, JSON.stringify(verdict)); } catch (e) {} }
function el(t, c, x) { const e = document.createElement(t); if (c) e.className = c; if (x != null) e.textContent = x; return e; }
function counts() {
  done.textContent = Object.keys(verdict).length;
  keeps.textContent = Object.values(verdict).filter(v => v === "keep").length;
}
function render() {
  const g = document.getElementById("grid"); g.textContent = "";
  for (const p of PHOTOS) {
    const card = el("div", "card " + (verdict[p.r] || ""));
    const img = el("img"); img.src = p.src; img.alt = p.r; img.loading = "lazy";
    const k = el("button", "k", "건질 사진"), b = el("button", "b", "흔들림·흐림"), d = el("button", "d", "별로");
    k.onclick = () => { verdict[p.r] = "keep"; persist(); render(); };
    b.onclick = () => { verdict[p.r] = "blur"; persist(); render(); };
    d.onclick = () => { verdict[p.r] = "drop"; persist(); render(); };
    const acts = el("div", "acts"); acts.append(k, b, d);
    card.append(img, el("div", "cap", p.t), acts);
    g.append(card);
  }
  counts();
}
document.getElementById("save").onclick = () => {
  const left = PHOTOS.filter(p => !verdict[p.r]).length;
  if (left && !confirm(`아직 ${left}장을 평가하지 않았습니다. 그래도 저장할까요?`)) return;
  const q = v => { v = String(v); return /[",\r\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v; };
  const lines = ["album_id,relpath,verdict," + ALBUM.methods.map(m => "in_" + m).join(",") + ",rule_version"];
  for (const p of PHOTOS) lines.push([ALBUM.id, p.r, verdict[p.r] || "", ...ALBUM.methods.map(m => p.m.includes(m) ? 1 : 0), ALBUM.rule_version].map(q).join(","));
  const a = el("a"); a.href = URL.createObjectURL(new Blob(["\ufeff" + lines.join("\r\n") + "\r\n"], {type: "text/csv"}));
  a.download = "review_" + ALBUM.file + ".csv"; document.body.append(a); a.click(); a.remove();
};
render();
</script></body></html>
"""


def drafts(a):
    """방식별 초안 인덱스. no_quality는 같은 묶음·선택 규칙에서 화질 점수만 끈 것."""
    nq = R.Analysis(a.items, a.sharp, a.emb, dict(a.params, quality_weight=0.0), a.failed, a.timing, a.embedder_name)
    return {"proposal": a.run("time_clip"), "no_quality": nq.run("time_clip"), "uniform": a.run("uniform")}


def make_page(args):
    root = Path(args.album).resolve()
    photos, _, _ = R.photos_from_folder(root)
    a = R.analyze(photos, embedder=args.embedder, clip_model=args.clip_model, cache_dir=args.cache,
                  params=args.params, drop_failed=True, log=print)
    if a.emb is None:
        raise SystemExit("초안을 만들려면 CLIP 임베딩이 필요합니다.")
    dr = drafts(a)
    member = {}
    for m in METHODS:
        for i in dr[m]:
            member.setdefault(i, []).append(m)
    order = sorted(member)
    random.Random(f"{root.name}-{a.rule_version}").shuffle(order)  # 방식을 알 수 없게 섞음
    data = []
    for i in order:
        it = a.items[i]
        with Image.open(R.work_image_path(args.cache, R._photo_key(it.path))) as im:
            im = im.convert("RGB")
        im.thumbnail((480, 480))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=80)
        data.append({"r": it.relpath, "m": member[i],
                     "src": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode(),
                     "t": "촬영 시각 미상" if it.local is None else f"{it.local:%m/%d %H:%M}"})
    out_dir = album_out_dir(args.work, root)
    out_dir.mkdir(parents=True, exist_ok=True)
    meta = {"id": args.album_id or root.name, "file": out_dir.name, "methods": METHODS, "rule_version": a.rule_version}
    js = lambda o: json.dumps(o, ensure_ascii=False).replace("</", "<\\/")  # noqa: E731
    page = (PAGE.replace("__TITLE__", html.escape(f"초안 평가 · {root.name}")).replace("__ALBUM__", html.escape(root.name))
                .replace("__N__", str(len(data))).replace("__META__", js(meta)).replace("__PHOTOS__", js(data)))
    path = out_dir / f"review_{out_dir.name}.html"
    path.write_text(page, encoding="utf-8")
    print(f"초안 사진 {len(data)}장 (방식 {len(METHODS)}개의 초안을 섞음), rule_version {a.rule_version}")
    print(f"초안 평가 페이지: {path.resolve()}")
    print("정답(owner.csv) 표시를 마친 앨범 주인에게만 보여주세요.")


def score(paths):
    """방식별로 앨범마다 '건질 사진 수/초안 수 · 흔들림 수'를 출력하고, 여러 앨범이면 평균 비율도 냅니다."""
    keep_rate = {m: [] for m in METHODS}
    blur_rate = {m: [] for m in METHODS}
    print("| 앨범 | " + " | ".join(f"{m} 건질 · 흔들림" for m in METHODS) + " |")
    print("|---|" + "---|" * len(METHODS))
    for p in paths:
        with open(p, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        album = rows[0]["album_id"] if rows else Path(p).stem
        cells = []
        for m in METHODS:
            mine = [r for r in rows if r.get(f"in_{m}") == "1"]
            keep = sum(r["verdict"] == "keep" for r in mine)
            blur = sum(r["verdict"] == "blur" for r in mine)
            rated = sum(r["verdict"] in VERDICTS for r in mine)
            keep_rate[m].append(keep / len(mine) if mine else float("nan"))
            blur_rate[m].append(blur / len(mine) if mine else float("nan"))
            cells.append(f"{keep}/{len(mine)} · {blur}" + ("" if rated == len(mine) else f" (미평가 {len(mine) - rated})"))
        print(f"| {album} | " + " | ".join(cells) + " |")
    if len(paths) > 1:
        print("| 평균 수용률 · 흔들림 비율 | " + " | ".join(
            f"{statistics.fmean(keep_rate[m]):.2f} · {statistics.fmean(blur_rate[m]):.2f}" for m in METHODS) + " |")
    print()
    print("건질 = '건질 사진' 수 / 초안 수, 흔들림 = '흔들림·흐림' 수. "
          "proposal=제안, no_quality=화질 점수 끔, uniform=균등 추출")


def main(argv=None):
    ap = argparse.ArgumentParser(description="초안 수용률 페이지 만들기와 채점")
    ap.add_argument("album", nargs="?", help="평가 앨범 폴더")
    ap.add_argument("--album-id")
    ap.add_argument("--score", nargs="+", metavar="REVIEW_CSV", help="저장된 review_*.csv로 수용률 계산")
    ap.add_argument("--embedder", choices=["clip", "tiny"], default="clip")
    ap.add_argument("--clip-model")
    ap.add_argument("--params")
    ap.add_argument("--cache", default=str(R.DEFAULT_CACHE))
    ap.add_argument("--work", default="j1_out")
    args = ap.parse_args(argv)
    if args.score:
        score(args.score)
    elif args.album:
        make_page(args)
    else:
        ap.error("앨범 폴더 또는 --score를 주세요.")


if __name__ == "__main__":
    sys.exit(main())
