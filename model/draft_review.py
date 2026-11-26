#!/usr/bin/env python3
"""초안 수용률: 앨범 주인이 추천 초안 사진을 '건질 사진 / 별로 / 흔들림·흐림'으로 평가하는 페이지와 채점.

  py draft_review.py "C:\\Photos\\jeju_trip" --album-id jeju --owner owner_jeju.csv   # 평가 페이지 만들기
  py draft_review.py --score review_jeju.csv [review_busan.csv ...]                 # 방식별 채점

페이지에는 세 방식의 초안 사진을 섞어서, 어느 방식이 고른 사진인지 모르게 보여줍니다.
같은 사진을 여러 방식이 골랐으면 한 번만 보여주고, 그 판정을 고른 방식 모두에 씁니다.
  proposal    제안 방식 (params.json 그대로)
  no_quality  제안 방식에서 관련도의 화질·미적 점수를 끈 것 (quality_weight=0, aesthetic_weight=0).
              묶음 안 대표 컷 순위 모델(rank_model)은 그대로라 선명도는 대표 컷 고르기에 남습니다.
  uniform     촬영 순번 균등 추출 (기준선)
수용률 = 그 방식의 초안 K장 중 주인이 '건질 사진'으로 표시한 비율.
흔들림 = 그 방식의 초안 K장 중 주인이 '흔들림·흐림'으로 표시한 장수 (사람이 본 화질 지표).
인정 장면 (--owner를 주면) = 주인이 사진마다 '내가 고른 10장 중 어느 사진(장면)을 대신 보여줄 수 있는지'를
              고르고, 그 방식의 초안이 담은 서로 다른 장면 수를 셉니다. 한 사진은 한 장면만 대신하고,
              같은 장면을 여러 장 담아도 한 번만 셉니다. 자동 지표 '같은 순간'을 사람 판단으로 검증합니다.

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
import sys
from pathlib import Path

from PIL import Image

import evaluate as E
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
.picks{display:flex;gap:8px;overflow-x:auto;padding:4px 0 8px}.pick{flex:0 0 120px;text-align:center;font-size:12px;color:var(--muted)}
.pick img{width:120px;height:90px;object-fit:cover;border-radius:6px;display:block}.pick b{color:var(--accent);font-size:14px}
.scene{width:100%;margin-top:6px;font:inherit;padding:3px;border:1px solid var(--line);border-radius:6px;background:var(--btn);color:var(--fg)}
.scene.set{border-color:var(--accent)}
</style></head><body>
<header><strong>__ALBUM__</strong><span class="stat">평가 <b id="done">0</b>/__N__장 · 건질 사진 <b id="keeps">0</b>장</span>
<button class="primary" id="save">저장</button></header>
<main>
<div class="help"><b>하는 법</b> · 아래는 추천 프로그램이 고른 사진들을 섞어 놓은 것입니다(순서는 무작위).
사진마다 <b>여행에 함께 가지 않은 친구에게 보여줄 최종 10장에 이 사진을 그대로 넣어도 되면 '건질 사진'</b>, 흔들리거나 초점이 나갔으면 '흔들림·흐림', 그 밖의 이유로 빼고 싶으면 '별로'를 누르세요.
내가 고른 10장과 달라도 그대로 넣어도 되는 사진이면 '건질 사진'입니다.
<span id="scenehelp" hidden><br><b>장면 고르기</b> · 바로 아래 번호 붙은 사진은 내가 고른 10장입니다. 사진마다 아래 칸에서 <b>이 사진이 내가 고른 사진 중 어느 것을 대신 보여줄 수 있는지</b> 번호를 고르고, 어느 것도 대신할 수 없으면 '해당 없음'을 고르세요.</span>
다 누르면 [저장]을 누르고 파일을 보내 주세요.</div>
<div class="picks" id="picks" hidden></div>
<div class="grid" id="grid"></div>
</main>
<script>
const ALBUM = __META__;
const PHOTOS = __PHOTOS__;
const SCENES = __SCENES__;  // [{id, n, src}] 주인이 고른 사진(장면). 비어 있으면 장면 고르기 없음
const KEY = "j1-review:" + ALBUM.file + ":" + ALBUM.rule_version;
let verdict = {}, scene = {};
try { const s = JSON.parse(localStorage.getItem(KEY) || "{}") || {}; if (s.verdict || s.scene) { verdict = s.verdict || {}; scene = s.scene || {}; } else { verdict = s; } } catch (e) {}  // 예전 저장 형식도 읽음
function persist() { try { localStorage.setItem(KEY, JSON.stringify({verdict, scene})); } catch (e) {} }
function el(t, c, x) { const e = document.createElement(t); if (c) e.className = c; if (x != null) e.textContent = x; return e; }
function counts() {
  done.textContent = PHOTOS.filter(p => verdict[p.r] && (!SCENES.length || scene[p.r])).length;
  keeps.textContent = Object.values(verdict).filter(v => v === "keep").length;
}
if (SCENES.length) {
  document.getElementById("scenehelp").hidden = false;
  const box = document.getElementById("picks"); box.hidden = false;
  for (const s of SCENES) {
    const d = el("div", "pick"); const im = el("img"); im.src = s.src; im.alt = "내가 고른 사진 " + s.n;
    const cap = el("div"); cap.append(el("b", "", String(s.n)));
    d.append(im, cap); box.append(d);
  }
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
    if (SCENES.length) {
      const sel = el("select", "scene" + (scene[p.r] ? " set" : ""));
      sel.append(new Option("대신할 수 있는 내 사진 번호 고르기", ""), new Option("해당 없음", "none"));
      for (const s of SCENES) sel.append(new Option(s.n + "번 사진", s.id));
      sel.value = scene[p.r] || "";
      sel.onchange = () => { if (sel.value) scene[p.r] = sel.value; else delete scene[p.r]; persist(); render(); };
      card.append(sel);
    }
    g.append(card);
  }
  counts();
}
document.getElementById("save").onclick = () => {
  const left = PHOTOS.filter(p => !verdict[p.r] || (SCENES.length && !scene[p.r])).length;
  if (left && !confirm(`아직 ${left}장을 다 표시하지 않았습니다. 그래도 저장할까요?`)) return;
  const q = v => { v = String(v); return /[",\r\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v; };
  const lines = ["album_id,relpath,verdict,scene," + ALBUM.methods.map(m => "in_" + m).join(",") + ",rule_version"];
  for (const p of PHOTOS) lines.push([ALBUM.id, p.r, verdict[p.r] || "", scene[p.r] || "", ...ALBUM.methods.map(m => p.m.includes(m) ? 1 : 0), ALBUM.rule_version].map(q).join(","));
  const a = el("a"); a.href = URL.createObjectURL(new Blob(["\ufeff" + lines.join("\r\n") + "\r\n"], {type: "text/csv"}));
  a.download = "review_" + ALBUM.file + ".csv"; document.body.append(a); a.click(); a.remove();
};
render();
</script></body></html>
"""


def drafts(a):
    """방식별 초안 인덱스. no_quality는 같은 묶음·선택 규칙에서 화질·미적 점수를 끈 것."""
    nq = R.Analysis(a.items, a.sharp, a.emb, dict(a.params, quality_weight=0.0, aesthetic_weight=0.0),
                    a.failed, a.timing, a.embedder_name)
    return {"proposal": a.run("time_clip"), "no_quality": nq.run("time_clip"), "uniform": a.run("uniform")}


def owner_scenes(a, owner, thumb):
    """주인이 고른 장면 목록 [{id, n, src}]. 장면마다 주인이 ★를 누른 사진을 대표로 보여줍니다(촬영순 번호)."""
    index = {it.relpath: i for i, it in enumerate(a.items)}
    reps = []
    for sid, cuts in owner.scenes.items():
        picked = sorted((index[r] for r in cuts & owner.picks if r in index))
        if not picked:
            continue
        reps.append((picked[0], sid))
    reps.sort()
    if not reps:
        raise SystemExit("owner.csv에서 이 앨범의 사진과 맞는 owner_pick 사진을 찾지 못했습니다. --album과 정답 파일을 확인하세요.")
    return [{"id": sid, "n": n, "src": thumb(i, 240)} for n, (i, sid) in enumerate(reps, 1)]


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

    def thumb(i, side):
        with Image.open(R.work_image_path(args.cache, R._photo_key(a.items[i].path))) as im:
            im = im.convert("RGB")
        im.thumbnail((side, side))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=80)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()

    data = []
    for i in order:
        it = a.items[i]
        data.append({"r": it.relpath, "m": member[i], "src": thumb(i, 480),
                     "t": "촬영 시각 미상" if it.local is None else f"{it.local:%m/%d %H:%M}"})
    scenes = owner_scenes(a, E.load_owner_csv(args.owner), thumb) if args.owner else []
    out_dir = album_out_dir(args.work, root)
    out_dir.mkdir(parents=True, exist_ok=True)
    meta = {"id": args.album_id or root.name, "file": out_dir.name, "methods": METHODS, "rule_version": a.rule_version}
    js = lambda o: json.dumps(o, ensure_ascii=False).replace("</", "<\\/")  # noqa: E731
    page = (PAGE.replace("__TITLE__", html.escape(f"초안 평가 · {root.name}")).replace("__ALBUM__", html.escape(root.name))
                .replace("__N__", str(len(data))).replace("__META__", js(meta)).replace("__PHOTOS__", js(data))
                .replace("__SCENES__", js(scenes)))
    path = out_dir / f"review_{out_dir.name}.html"
    path.write_text(page, encoding="utf-8")
    print(f"초안 사진 {len(data)}장 (방식 {len(METHODS)}개의 초안을 섞음), rule_version {a.rule_version}")
    if scenes:
        print(f"장면 고르기: 주인이 고른 장면 {len(scenes)}개")
    print(f"초안 평가 페이지: {path.resolve()}")
    print("정답(owner.csv) 표시를 마친 앨범 주인에게만 보여주세요.")


def scene_hits(rows):
    """주인이 인정한 서로 다른 장면 수 ('none'과 빈 칸 제외). 같은 장면을 여러 장 담아도 한 번만 셉니다."""
    return len({r.get("scene", "") for r in rows} - {"", "none"})


def score(paths):
    """방식별로 앨범마다 '건질 사진 수/초안 수 · 흔들림 수 · 인정 장면 수'를 출력하고, 앨범 합계도 냅니다."""
    tot = {m: [0, 0, 0, 0] for m in METHODS}  # 건질, 초안 수, 흔들림, 인정 장면
    has_scene = False
    print("| 앨범 | " + " | ".join(f"{m} 건질 · 흔들림 · 장면" for m in METHODS) + " |")
    print("|---|" + "---|" * len(METHODS))
    for p in paths:
        with open(p, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        album = rows[0]["album_id"] if rows else Path(p).stem
        scene_col = bool(rows) and "scene" in rows[0]
        has_scene |= scene_col
        cells = []
        for m in METHODS:
            mine = [r for r in rows if r.get(f"in_{m}") == "1"]
            keep = sum(r["verdict"] == "keep" for r in mine)
            blur = sum(r["verdict"] == "blur" for r in mine)
            rated = sum(r["verdict"] in VERDICTS for r in mine)
            sc = scene_hits(mine) if scene_col else None
            unscened = sum(not r.get("scene") for r in mine) if scene_col else 0
            for j, v in enumerate((keep, len(mine), blur, sc or 0)):
                tot[m][j] += v
            note = []
            if rated < len(mine):
                note.append(f"미평가 {len(mine) - rated}")
            if unscened:
                note.append(f"장면 미표시 {unscened}")
            cells.append(f"{keep}/{len(mine)} · {blur} · {'-' if sc is None else sc}" + (f" ({', '.join(note)})" if note else ""))
        print(f"| {album} | " + " | ".join(cells) + " |")
    if len(paths) > 1:
        print("| 합계 | " + " | ".join(f"{t[0]}/{t[1]} · {t[2]} · {t[3] if has_scene else '-'}" for t in tot.values()) + " |")
    print()
    print("건질 = '건질 사진' 수 / 초안 수, 흔들림 = '흔들림·흐림' 수, 장면 = 주인이 인정한 서로 다른 장면 수. "
          "proposal=제안, no_quality=관련도의 화질·미적 점수 끔, uniform=균등 추출. "
          "판정은 docs/experiments.md의 판정 규칙(앨범별 방향)을 따릅니다.")


def main(argv=None):
    ap = argparse.ArgumentParser(description="초안 수용률 페이지 만들기와 채점")
    ap.add_argument("album", nargs="?", help="평가 앨범 폴더")
    ap.add_argument("--album-id")
    ap.add_argument("--owner", help="이 앨범의 owner.csv. 주면 사진마다 '내가 고른 10장 중 어느 장면을 대신하는지'도 받습니다")
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
