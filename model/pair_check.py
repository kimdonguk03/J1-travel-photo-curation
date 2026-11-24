#!/usr/bin/env python3
"""기준값 점검: 사진 쌍을 '연사 / 다른 장면'으로 표시하면 유사도 분포와 기준값별 정답률을 계산합니다.

  py pair_check.py "C:\\Photos\\dev_album"

j1_out\\<album>\\pairs.html을 브라우저로 열어 표시합니다.
  - 연사: 한 장만 남겨도 되는 같은 컷 (같은 묶음이어야 함)
  - 다른 장면: 같은 장소라도 둘 다 남겨야 하는 사진 (따로 남아야 함)
표시하는 동안에는 유사도를 보여주지 않습니다(판단이 숫자에 끌리지 않도록). 결과 표는 페이지 아래에 바로 계산되고,
CSV로 내보낼 수 있습니다.
"""
from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path

import numpy as np

import recommend as R
from curation import Thumbs, album_out_dir

CANDIDATE_GAP_SEC = 600  # 이 간격 안의 연속 사진을 표시 후보로 보여줍니다

PAGE = r"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
:root{--bg:#f7f7f5;--fg:#1d1d1b;--muted:#6a6a64;--card:#fff;--line:#e2e2dd;--accent:#b45309;--ok:#15803d;--bad:#b91c1c;--btn:#ececE8;--sel:#2563eb}
@media (prefers-color-scheme:dark){:root{--bg:#151514;--fg:#ebebe8;--muted:#9b9b94;--card:#1f1f1d;--line:#33332f;--accent:#f59e0b;--ok:#4ade80;--bad:#f87171;--btn:#2c2c29;--sel:#60a5fa}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,"Malgun Gothic",sans-serif}
header{position:sticky;top:0;z-index:5;background:var(--bg);border-bottom:1px solid var(--line);padding:8px 16px;display:flex;gap:14px;align-items:center;flex-wrap:wrap}
header strong{font-size:16px}.stat b{color:var(--accent);font-variant-numeric:tabular-nums}
main{max-width:1300px;margin:0 auto;padding:12px 16px 120px}
h2{font-size:16px;margin:24px 0 8px;scroll-margin-top:64px}.meta{color:var(--muted);margin:4px 0 10px}
button{font:inherit;border:1px solid var(--line);background:var(--btn);color:var(--fg);border-radius:6px;padding:3px 10px;cursor:pointer}
button.on-burst{background:var(--ok);border-color:var(--ok);color:#fff}button.on-diff{background:var(--bad);border-color:var(--bad);color:#fff}
button.on-skip{background:var(--muted);border-color:var(--muted);color:#fff}button.primary{background:var(--accent);border-color:var(--accent);color:#fff}
.help{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 14px}
.help ol{margin:6px 0 0;padding-left:20px}
.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:8px;margin-bottom:8px}
.row img,.grid img{width:150px;height:150px;object-fit:contain;background:rgba(127,127,127,.15);border-radius:6px;display:block}
.info{min-width:120px;color:var(--muted);font-size:12.5px}.acts{display:flex;gap:6px;flex-wrap:wrap}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:8px}
.grid figure{margin:0;border:3px solid transparent;border-radius:9px;cursor:pointer}.grid figure.sel{border-color:var(--sel)}
.grid img{width:100%;height:auto;aspect-ratio:1/1}
figcaption{font-size:11.5px;color:var(--muted);padding:2px 3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#selbar{position:fixed;left:50%;bottom:16px;transform:translateX(-50%);background:var(--card);border:1px solid var(--line);border-radius:12px;padding:8px 12px;display:none;gap:8px;align-items:center;box-shadow:0 6px 24px rgba(0,0,0,.25)}
table{border-collapse:collapse;background:var(--card);margin:6px 0 12px}td,th{border:1px solid var(--line);padding:4px 10px;text-align:right;font-variant-numeric:tabular-nums}
th{background:var(--btn)}td:first-child,th:first-child{text-align:left}tr.cur td{font-weight:700;color:var(--accent)}
.err .row{border-color:var(--bad)}
</style></head><body>
<header>
  <strong>__ALBUM__</strong>
  <span class="stat">연사 <b id="nB">0</b>쌍 · 다른 장면 <b id="nD">0</b>쌍</span>
  <span class="stat">기준값 __TH__에서 정답 <b id="acc">-</b></span>
  <button class="primary" id="csv">CSV 내보내기</button>
</header>
<main>
<details class="help" open><summary><b>표시 방법</b> (유사도는 표시하는 동안 숨겨 둡니다)</summary>
<ol>
<li><b>연사</b>: 한 장만 남겨도 되는 같은 컷입니다. 같은 묶음으로 묶여야 합니다.</li>
<li><b>다른 장면</b>: 같은 장소라도 둘 다 남겨야 하는 사진입니다(예: 단체사진과 바다 풍경). 따로 남아야 합니다.</li>
<li>애매하면 <b>모름</b>을 누르세요. 결과 계산에서 빠집니다.</li>
<li>아래 목록에 없는 쌍은 '직접 고르기'에서 사진 두 장을 눌러 추가합니다.</li>
</ol></details>

<h2>1. 시간이 가까운 연속 사진 쌍 <span class="meta" id="candInfo"></span></h2>
<div id="cand"></div>

<h2>2. 직접 고르기</h2>
<p class="meta">사진 두 장을 누르면 아래에 버튼이 나타납니다. 직접 추가한 쌍은 이 목록 아래에 보입니다.</p>
<div class="grid" id="grid"></div>
<div id="manual" style="margin-top:10px"></div>

<h2 id="res">3. 결과</h2>
<div id="results"><p class="meta">쌍을 표시하면 여기에 계산됩니다.</p></div>
</main>
<div id="selbar"><span id="selinfo"></span><button id="sb">연사</button><button id="sd">다른 장면</button><button id="sc">취소</button></div>
<script>
const TH = __TH__, P = __PHOTOS__, SIM = __SIM__, CAND = __CAND__, ALBUM = __META__;
const KEY = "j1-pairs:" + ALBUM.id;
const NAME = {burst: "연사", diff: "다른 장면", skip: "모름"};
let labels = {}, sel = [];
const k = (i, j) => i < j ? i + "-" + j : j + "-" + i;
const candSet = new Set(CAND.map(([i, j]) => k(i, j)));
function el(t, c, x) { const e = document.createElement(t); if (c) e.className = c; if (x != null) e.textContent = x; return e; }
function img(i) { const m = el("img"); m.src = P[i].src; m.alt = P[i].r; m.title = P[i].r; m.loading = "lazy"; return m; }
function persist() { try { localStorage.setItem(KEY, JSON.stringify(labels)); } catch (e) {} }
function setLabel(i, j, v) { const key = k(i, j); if (labels[key] === v) delete labels[key]; else labels[key] = v; persist(); render(); }
function fmt(x) { return x == null ? "-" : x.toFixed(3); }
function pct(a, b) { return b ? `${a}/${b} (${Math.round(100 * a / b)}%)` : "-"; }
function gapText(i, j) {
  if (P[i].ts == null || P[j].ts == null) return "촬영 시각 미상 포함";
  const g = Math.abs(P[j].ts - P[i].ts); return g < 60 ? `${g.toFixed(1)}초 간격` : `${(g / 60).toFixed(1)}분 간격`;
}

function pairRow(i, j, removable) {
  const row = el("div", "row"), key = k(i, j);
  const info = el("div", "info"); info.innerHTML = `${P[i].t}<br>${P[j].t}<br>${gapText(i, j)}`;
  const acts = el("div", "acts");
  for (const v of ["burst", "diff", "skip"]) {
    const b = el("button", labels[key] === v ? "on-" + v : "", NAME[v]); b.onclick = () => setLabel(i, j, v); acts.append(b);
  }
  if (removable) { const b = el("button", null, "삭제"); b.onclick = () => { delete labels[key]; persist(); render(); }; acts.append(b); }
  row.append(img(i), img(j), info, acts);
  return row;
}

function renderCand() {
  const box = document.getElementById("cand"); box.textContent = "";
  document.getElementById("candInfo").textContent =
    `${CAND.length}쌍 · 연속 사진 ${ALBUM.total}쌍 중 판단이 필요한 유사도 ${ALBUM.low}~${ALBUM.high} 구간만 (약 10분)`;
  if (!CAND.length) box.append(el("p", "meta", "후보가 없습니다. 직접 고르기를 쓰세요."));
  for (const [i, j] of CAND) box.append(pairRow(i, j, false));
}

function renderGrid() {
  const g = document.getElementById("grid"); g.textContent = "";
  P.forEach((p, i) => {
    const f = el("figure", sel.includes(i) ? "sel" : ""); f.append(img(i), el("figcaption", null, p.t));
    f.onclick = () => { sel = sel.includes(i) ? sel.filter(x => x !== i) : [...sel, i].slice(-2); renderGrid(); renderSel(); };
    g.append(f);
  });
}

function renderSel() {
  const bar = document.getElementById("selbar");
  bar.style.display = sel.length === 2 ? "flex" : "none";
  if (sel.length === 2) document.getElementById("selinfo").textContent = `${P[sel[0]].t} ↔ ${P[sel[1]].t}`;
}
function addSel(v) { if (sel.length === 2) { labels[k(sel[0], sel[1])] = v; persist(); sel = []; renderGrid(); renderSel(); render(); } }
document.getElementById("sb").onclick = () => addSel("burst");
document.getElementById("sd").onclick = () => addSel("diff");
document.getElementById("sc").onclick = () => { sel = []; renderGrid(); renderSel(); };

function rows() {
  return Object.entries(labels).filter(([, v]) => v === "burst" || v === "diff").map(([key, v]) => {
    const [i, j] = key.split("-").map(Number);
    return {i, j, v, sim: SIM[i][j], sameGroup: P[i].g === P[j].g, sameSeg: P[i].s >= 0 && P[i].s === P[j].s};
  });
}

function stats(list) {
  if (!list.length) return [null, null, null];
  const s = list.map(r => r.sim).sort((a, b) => a - b), m = s.length;
  return [s[0], m % 2 ? s[(m - 1) / 2] : (s[m / 2 - 1] + s[m / 2]) / 2, s[m - 1]];
}

function renderResults() {
  const rs = rows(), B = rs.filter(r => r.v === "burst"), D = rs.filter(r => r.v === "diff");
  document.getElementById("nB").textContent = B.length; document.getElementById("nD").textContent = D.length;
  const box = document.getElementById("results"); box.textContent = "";
  if (!rs.length) { box.append(el("p", "meta", "쌍을 표시하면 여기에 계산됩니다.")); document.getElementById("acc").textContent = "-"; return; }
  const bOk = B.filter(r => r.sim >= TH).length, dOk = D.filter(r => r.sim < TH).length;
  document.getElementById("acc").textContent = pct(bOk + dOk, rs.length);
  const [b0, b1, b2] = stats(B), [d0, d1, d2] = stats(D);
  const t1 = `<table><tr><th>표시</th><th>쌍</th><th>최소</th><th>중앙</th><th>최대</th></tr>
    <tr><td>연사</td><td>${B.length}</td><td>${fmt(b0)}</td><td>${fmt(b1)}</td><td>${fmt(b2)}</td></tr>
    <tr><td>다른 장면</td><td>${D.length}</td><td>${fmt(d0)}</td><td>${fmt(d1)}</td><td>${fmt(d2)}</td></tr></table>`;
  const rB = B.filter(r => r.sameGroup).length, rD = D.filter(r => !r.sameGroup).length;
  const t2 = `<table><tr><th>판정</th><th>연사 → 묶임</th><th>다른 장면 → 따로</th><th>전체</th></tr>
    <tr><td>두 사진의 유사도 ≥ ${TH}</td><td>${pct(bOk, B.length)}</td><td>${pct(dOk, D.length)}</td><td>${pct(bOk + dOk, rs.length)}</td></tr>
    <tr><td>실제 묶기 결과 (시간 구간 + 기준 컷)</td><td>${pct(rB, B.length)}</td><td>${pct(rD, D.length)}</td><td>${pct(rB + rD, rs.length)}</td></tr></table>`;
  let sweep = `<table><tr><th>기준값</th><th>연사 → 묶임</th><th>다른 장면 → 따로</th><th>평균</th></tr>`;
  const vals = [];
  for (let t = 80; t <= 98; t++) {
    const th = t / 100, a = B.length ? B.filter(r => r.sim >= th).length / B.length : null, b = D.length ? D.filter(r => r.sim < th).length / D.length : null;
    const avg = a == null ? b : b == null ? a : (a + b) / 2; vals.push([th, a, b, avg]);
  }
  const best = Math.max(...vals.map(v => v[3]));
  const bestTh = vals.filter(v => v[3] === best).map(v => v[0]);
  const ranges = [];
  for (const th of bestTh) {
    const last = ranges[ranges.length - 1];
    if (last && Math.abs(th - last[1] - 0.01) < 1e-9) last[1] = th; else ranges.push([th, th]);
  }
  const bestText = ranges.map(([a, b]) => a === b ? a.toFixed(2) : `${a.toFixed(2)}~${b.toFixed(2)}`).join(", ");
  for (const [th, a, b, avg] of vals) {
    const cls = Math.abs(th - TH) < 1e-9 ? "cur" : "";
    const f = x => x == null ? "-" : Math.round(100 * x) + "%";
    sweep += `<tr class="${cls}"><td>${th.toFixed(2)}${cls === "cur" ? " (현재)" : ""}</td><td>${f(a)}</td><td>${f(b)}</td><td>${f(avg)}</td></tr>`;
  }
  sweep += "</table>";
  box.innerHTML = `<h3>유사도 분포</h3>${t1}<h3>현재 기준값 ${TH}</h3>${t2}
    <p class="meta">실제 묶기는 같은 시간 구간 안에서 묶음의 첫 컷과만 비교하므로, 두 사진의 유사도만으로 본 결과와 다를 수 있습니다.</p>
    <h3>기준값을 바꾸면</h3><p class="meta">평균이 가장 높은 기준값: <b>${bestText}</b> (${Math.round(100 * best)}%).
    쌍이 적으면 우연에 크게 좌우되니 참고로만 보세요.</p>${sweep}
    <h3>현재 기준값에서 틀린 쌍</h3>`;
  const errs = rs.filter(r => (r.v === "burst") !== (r.sim >= TH)).sort((a, b) => b.sim - a.sim);
  const wrap = el("div", "err");
  if (!errs.length) wrap.append(el("p", "meta", "없음"));
  for (const r of errs) {
    const row = el("div", "row");
    const info = el("div", "info");
    info.innerHTML = `<b>${NAME[r.v]}</b>로 표시<br>유사도 ${r.sim.toFixed(3)}<br>${gapText(r.i, r.j)}<br>` +
      `실제 묶기: ${r.sameGroup ? "같은 묶음" : (r.sameSeg ? "따로 (같은 구간)" : "따로 (구간이 다름)")}`;
    row.append(img(r.i), img(r.j), info); wrap.append(row);
  }
  box.append(wrap);
}

function render() { renderCand(); renderManual(); renderResults(); }
function renderManual() {
  const box = document.getElementById("manual"); box.textContent = "";
  const extra = Object.keys(labels).filter(key => !candSet.has(key));
  if (extra.length) box.append(el("p", "meta", `직접 추가한 쌍 ${extra.length}개`));
  for (const key of extra) { const [i, j] = key.split("-").map(Number); box.append(pairRow(i, j, true)); }
}

document.getElementById("csv").onclick = () => {
  const q = v => { v = String(v); return /[",\r\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v; };
  const lines = ["relpath_a,relpath_b,label,similarity,gap_sec,same_segment,same_group,threshold"];
  for (const r of rows()) {
    const gap = P[r.i].ts == null || P[r.j].ts == null ? "" : Math.abs(P[r.j].ts - P[r.i].ts).toFixed(2);
    lines.push([P[r.i].r, P[r.j].r, NAME[r.v], r.sim.toFixed(4), gap, r.sameSeg ? 1 : 0, r.sameGroup ? 1 : 0, TH].map(q).join(","));
  }
  const a = el("a"); a.href = URL.createObjectURL(new Blob(["\ufeff" + lines.join("\r\n") + "\r\n"], {type: "text/csv"}));
  a.download = "pairs_" + ALBUM.id + ".csv"; document.body.append(a); a.click(); a.remove();
};

try { labels = JSON.parse(localStorage.getItem(KEY) || "{}") || {}; } catch (e) { labels = {}; }
for (const key of Object.keys(labels)) { const [i, j] = key.split("-").map(Number); if (!(i < P.length && j < P.length)) delete labels[key]; }
renderGrid(); render();
</script>
</body></html>
"""


def _js(obj):
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")


def main(argv=None):
    ap = argparse.ArgumentParser(description="사진 쌍 표시로 기준값(clip_sim)을 점검하는 페이지를 만듭니다.")
    ap.add_argument("album")
    ap.add_argument("--embedder", choices=["clip", "tiny"], default="clip")
    ap.add_argument("--clip-model")
    ap.add_argument("--params")
    ap.add_argument("--cache", default=str(R.DEFAULT_CACHE))
    ap.add_argument("--work", default="j1_out")
    ap.add_argument("--low", type=float, default=0.84, help="표시할 유사도 구간 아래 끝 (기본 0.84)")
    ap.add_argument("--high", type=float, default=0.96, help="표시할 유사도 구간 위 끝 (기본 0.96)")
    args = ap.parse_args(argv)

    photos, _, failed = R.photos_from_folder(args.album)
    a = R.analyze(photos, embedder=args.embedder, clip_model=args.clip_model, cache_dir=args.cache,
                  params=args.params, drop_failed=True, log=print)
    groups, _, _ = a.groups("time_clip")
    group_of = {i: g for g, members in enumerate(groups) for i in members}
    seg_of = {i: s for s, seg in enumerate(R.time_segments(a.items, a.params)) for i in seg}
    sim = np.clip(a.emb @ a.emb.T, -1, 1)

    thumb = Thumbs(a, args.cache, side=300)
    data = []
    for i, it in enumerate(a.items):
        data.append({"r": it.relpath, "src": thumb(i), "g": group_of[i], "s": seg_of.get(i, -1),
                     "t": "촬영 시각 미상" if it.local is None else f"{it.local:%m/%d %H:%M:%S}", "ts": it.t})
    cand = []
    for i in range(len(a.items) - 1):
        x, y = a.items[i], a.items[i + 1]
        if (x.t is not None and y.t is not None and y.t - x.t <= CANDIDATE_GAP_SEC
                and R.day_of(x, a.params) == R.day_of(y, a.params)):
            cand.append([i, i + 1])
    total = len(cand)
    # 확실한 쌍(아주 비슷하거나 확실히 다른 쌍)은 빼고, 판단이 필요한 구간만 보여줍니다
    cand = [[i, j] for i, j in cand if args.low <= sim[i][j] < args.high]

    out = album_out_dir(args.work, args.album)
    out.mkdir(parents=True, exist_ok=True)
    name = Path(args.album).resolve().name
    page = (PAGE.replace("__TITLE__", html.escape(f"기준값 점검 · {name}"))
                .replace("__ALBUM__", html.escape(name))
                .replace("__TH__", repr(float(a.params["clip_sim"])))
                .replace("__PHOTOS__", _js(data))
                .replace("__SIM__", _js(np.round(sim, 4).tolist()))
                .replace("__CAND__", _js(cand))
                .replace("__META__", _js({"id": out.name, "rule_version": a.rule_version,
                                           "low": args.low, "high": args.high, "total": total})))
    path = out / "pairs.html"
    path.write_text(page, encoding="utf-8")
    print(f"사진 {len(a.items)}장, 연속 사진 쌍 {total}개 중 유사도 {args.low}~{args.high} 구간 {len(cand)}쌍을 표시, "
          f"기준값 {a.params['clip_sim']}")
    print(f"기준값 점검 페이지: {path.resolve()}")


if __name__ == "__main__":
    sys.exit(main())
