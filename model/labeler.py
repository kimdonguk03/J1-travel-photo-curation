#!/usr/bin/env python3
"""앨범 주인이 owner.csv를 만드는 페이지를 생성합니다.

  py labeler.py "C:\\Photos\\제주" --album-id jeju

만들어진 label_*.html을 크롬이나 엣지로 열어 앨범 주인이 직접 표시합니다.
  1) 여행에 못 온 친구에게 보여줄 10장에 ★  -> owner_pick = 1
  2) [+ 새 장면]으로 중요 장면을 만들고, 그 장면을 대신할 수 있는 컷을 모두 '장면에 넣기'  -> scene_id
  3) [owner.csv 저장]  -> evaluate.py에 넣습니다

이 페이지에는 알고리즘 결과가 없습니다. 정답은 반드시 추천을 보여주기 전에 받으세요.
"""
from __future__ import annotations

import argparse
import base64
import html
import io
import json
import sys
from pathlib import Path

from PIL import Image

import recommend as R
from curation import album_out_dir

WEEKDAY = "월화수목금토일"

PAGE = r"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
:root{--bg:#f7f7f5;--fg:#1d1d1b;--muted:#6a6a64;--card:#fff;--line:#deded8;--accent:#b45309;--pick:#ca8a04;--btn:#ececE8}
@media (prefers-color-scheme:dark){:root{--bg:#151514;--fg:#ebebe8;--muted:#9b9b94;--card:#1f1f1d;--line:#36362f;--accent:#f59e0b;--pick:#facc15;--btn:#2c2c29}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,"Malgun Gothic",sans-serif}
header{position:sticky;top:0;z-index:5;background:var(--bg);border-bottom:1px solid var(--line);padding:8px 16px}
.bar{display:flex;gap:12px;align-items:center;flex-wrap:wrap}
.bar strong{font-size:16px}.stat b{color:var(--accent)}
button,.btn{font:inherit;border:1px solid var(--line);background:var(--btn);color:var(--fg);border-radius:6px;padding:3px 10px;cursor:pointer}
button.primary{background:var(--accent);border-color:var(--accent);color:#fff}
button[disabled]{opacity:.45;cursor:default}
.scenes{display:flex;gap:6px;flex-wrap:wrap;margin-top:6px;align-items:center}
.chip{border-radius:999px;padding:2px 10px;border:2px solid transparent;cursor:pointer;background:var(--btn)}
.chip.active{border-color:var(--accent);font-weight:700}
.edit{display:flex;gap:6px;align-items:center;margin-top:6px}
.edit input{font:inherit;width:260px;padding:3px 8px;border:1px solid var(--line);border-radius:6px;background:var(--card);color:var(--fg)}
main{max-width:1500px;margin:0 auto;padding:12px 16px 80px}
.help{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 14px;margin-bottom:14px}
.help ol{margin:6px 0 0;padding-left:20px}.help li{margin:2px 0}
h2{font-size:15px;margin:18px 0 8px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:8px}
.card{background:var(--card);border:2px solid transparent;border-radius:8px;padding:4px;border-top-width:6px}
.card.picked{border-color:var(--pick)}
.card img{width:100%;aspect-ratio:1/1;object-fit:cover;border-radius:5px;display:block;cursor:pointer}
.cap{font-size:12px;color:var(--muted);margin:3px 2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tag{font-size:12px;font-weight:700;margin:0 2px 3px;min-height:18px}
.acts{display:flex;gap:4px}.acts button{flex:1;font-size:12px;padding:3px 4px}
.card.picked .star{background:var(--pick);border-color:var(--pick);color:#000}
</style></head><body>
<header>
  <div class="bar">
    <strong>__ALBUM__</strong>
    <span class="stat">★ <b id="nPick">0</b>/__K__장</span>
    <span class="stat">중요 장면 <b id="nScene">0</b>개 · 인정 컷 <b id="nCut">0</b>장</span>
    <button id="addScene">+ 새 장면</button>
    <button class="primary" id="save">owner.csv 저장</button>
    <label class="btn">불러오기<input type="file" id="load" accept=".csv,text/csv" hidden></label>
  </div>
  <div class="scenes" id="scenes"></div>
  <div class="edit" id="edit"></div>
</header>
<main>
<details class="help" open><summary><b>표시 순서</b> (촬영 시각 순서입니다. 이 화면에는 알고리즘 결과가 없습니다.)</summary>
<ol>
<li><b>먼저</b> 이 여행에 못 온 친한 친구에게 보여줄 __K__장을 고르세요. 사진을 누르거나 ★ 버튼을 누릅니다. 휴대폰에서 이미 골랐다면 같은 사진에 ★를 표시하세요.</li>
<li>[+ 새 장면]을 눌러 꼭 들어가야 할 중요 장면을 만들고 이름을 적으세요(예: 해변 단체사진, 첫날 저녁 식사).</li>
<li>그 장면이 선택된 상태에서, <b>이 사진이 들어 있으면 그 장면을 담았다고 인정할 수 있는 컷</b>을 모두 '장면에 넣기' 하세요. ★ 사진도 해당 장면에 넣습니다. 한 사진은 한 장면에만 들어갑니다.</li>
<li>[owner.csv 저장]을 눌러 파일을 팀에 보내 주세요. 장면에 넣지 않은 ★ 사진은 각각 별도 장면으로 저장됩니다. 표시 내용은 이 브라우저에도 자동 저장됩니다.</li>
</ol></details>
<div id="list"></div>
</main>
<script>
const ALBUM = __ALBUM_JSON__;
const PHOTOS = __PHOTOS_JSON__;
const KEY = "j1-owner:" + ALBUM.file;
const INDEX = new Map(PHOTOS.map((p, i) => [p.r, i]));
let picks = new Set(), scenes = [], sceneOf = {}, active = null, nextId = 1;

function el(tag, cls, text) { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
function hue(id) { return (id * 67) % 360; }
function sceneById(id) { return scenes.find(s => s.id === id); }
function label(s) { return "S" + String(scenes.indexOf(s) + 1).padStart(2, "0") + (s.name.trim() ? " " + s.name.trim() : ""); }
function clean(name) { return name.replace(/[,"\r\n]+/g, " ").replace(/\s+/g, " ").trim(); }

function state() { return {picks: [...picks], scenes, sceneOf, nextId}; }
function persist() { try { localStorage.setItem(KEY, JSON.stringify(state())); } catch (e) { /* 저장소를 못 쓰면 내보내기만 */ } }
function restore(s) {
  picks = new Set((s.picks || []).filter(r => INDEX.has(r)));
  scenes = s.scenes || []; nextId = s.nextId || (Math.max(0, ...scenes.map(x => x.id)) + 1);
  sceneOf = {}; for (const [r, id] of Object.entries(s.sceneOf || {})) if (INDEX.has(r) && sceneById(id)) sceneOf[r] = id;
  active = scenes.length ? scenes[scenes.length - 1].id : null;
}

function buildRows() {
  const rows = [], orphan = PHOTOS.filter(p => picks.has(p.r) && !sceneOf[p.r]);
  scenes.forEach((s, n) => {
    const sid = "S" + String(n + 1).padStart(2, "0") + (clean(s.name) ? "_" + clean(s.name) : "");
    for (const p of PHOTOS) if (sceneOf[p.r] === s.id) rows.push([ALBUM.id, sid, p.r, picks.has(p.r) ? 1 : 0]);
  });
  orphan.forEach((p, n) => rows.push([ALBUM.id, "S" + String(scenes.length + n + 1).padStart(2, "0") + "_장면미지정선택", p.r, 1]));
  return {rows, orphan: orphan.length};
}

function toCsv(rows) {
  const q = v => { v = String(v); return /[",\r\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v; };
  return "\ufeff" + ["album_id,scene_id,relpath,owner_pick", ...rows.map(r => r.map(q).join(","))].join("\r\n") + "\r\n";
}

function parseCsv(text) {
  const rows = []; let row = [], cur = "", inQ = false;
  text = text.replace(/^\ufeff/, "");
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (inQ) { if (c === '"' && text[i + 1] === '"') { cur += '"'; i++; } else if (c === '"') inQ = false; else cur += c; }
    else if (c === '"') inQ = true;
    else if (c === ",") { row.push(cur); cur = ""; }
    else if (c === "\n" || c === "\r") { if (c === "\r" && text[i + 1] === "\n") i++; row.push(cur); rows.push(row); row = []; cur = ""; }
    else cur += c;
  }
  if (cur || row.length) { row.push(cur); rows.push(row); }
  return rows.filter(r => r.some(x => x.trim()));
}

function importCsv(text) {
  const rows = parseCsv(text), head = rows.shift().map(h => h.trim());
  const col = n => head.indexOf(n);
  if (["album_id", "scene_id", "relpath", "owner_pick"].some(n => col(n) < 0)) throw new Error("열 이름이 다릅니다");
  picks = new Set(); scenes = []; sceneOf = {}; nextId = 1;
  const byKey = new Map(); let missing = 0;
  for (const r of rows) {
    const rel = (r[col("relpath")] || "").trim().replace(/\\/g, "/"), sid = (r[col("scene_id")] || "").trim();
    if (!INDEX.has(rel)) { missing++; continue; }
    if (["1", "true", "y", "yes"].includes((r[col("owner_pick")] || "").trim().toLowerCase())) picks.add(rel);
    if (!sid || sid.endsWith("_장면미지정선택")) continue;
    if (!byKey.has(sid)) { const s = {id: nextId++, name: sid.replace(/^S\d+_?/, "")}; scenes.push(s); byKey.set(sid, s.id); }
    sceneOf[rel] = byKey.get(sid);
  }
  active = scenes.length ? scenes[0].id : null;
  return missing;
}

function counts() {
  nPick.textContent = picks.size; nScene.textContent = scenes.length; nCut.textContent = Object.keys(sceneOf).length;
}

function renderBar() {
  const box = document.getElementById("scenes"); box.textContent = "";
  if (!scenes.length) box.append(el("span", "cap", "아직 장면이 없습니다. [+ 새 장면]으로 만드세요."));
  for (const s of scenes) {
    const n = Object.values(sceneOf).filter(id => id === s.id).length;
    const c = el("span", "chip" + (s.id === active ? " active" : ""), `${label(s)} (${n})`);
    c.style.background = `hsl(${hue(s.id)} 70% 50% / .22)`;
    c.onclick = () => { active = s.id; persist(); renderAll(); };
    box.append(c);
  }
  const ed = document.getElementById("edit"); ed.textContent = "";
  const s = sceneById(active);
  if (!s) return;
  ed.append(el("span", null, "선택한 장면 이름"));
  const inp = el("input"); inp.value = s.name; inp.placeholder = "예: 해변 단체사진";
  inp.oninput = () => { s.name = inp.value; persist(); renderBarChipsOnly(); renderTags(); };
  const del = el("button", null, "장면 삭제");
  del.onclick = () => {
    for (const r of Object.keys(sceneOf)) if (sceneOf[r] === s.id) delete sceneOf[r];
    scenes = scenes.filter(x => x !== s); active = scenes.length ? scenes[scenes.length - 1].id : null;
    persist(); renderAll();
  };
  ed.append(inp, del);
}

function renderBarChipsOnly() {
  const chips = document.querySelectorAll("#scenes .chip");
  scenes.forEach((s, i) => { if (chips[i]) chips[i].textContent = `${label(s)} (${Object.values(sceneOf).filter(id => id === s.id).length})`; });
}

function renderTags() {
  document.querySelectorAll(".card").forEach(card => {
    const p = PHOTOS[+card.dataset.i], id = sceneOf[p.r], s = sceneById(id);
    card.style.borderTopColor = s ? `hsl(${hue(id)} 70% 50%)` : "transparent";
    card.querySelector(".tag").textContent = s ? label(s) : "";
    const b = card.querySelector(".scn");
    if (s) { b.textContent = "장면에서 빼기"; b.disabled = false; }
    else if (sceneById(active)) { b.textContent = label(sceneById(active)).split(" ")[0] + "에 넣기"; b.disabled = false; }
    else { b.textContent = "장면 먼저 만들기"; b.disabled = true; }
  });
}

function renderList() {
  const list = document.getElementById("list"); list.textContent = "";
  let grid = null, last = null;
  PHOTOS.forEach((p, i) => {
    const day = p.d || "촬영 시각 미상";
    if (day !== last) { list.append(el("h2", null, day)); grid = el("div", "grid"); list.append(grid); last = day; }
    const card = el("div", "card" + (picks.has(p.r) ? " picked" : "")); card.dataset.i = i;
    const img = el("img"); img.src = p.src; img.alt = p.r; img.title = p.r; img.loading = "lazy";
    const togglePick = () => { picks.has(p.r) ? picks.delete(p.r) : picks.add(p.r); card.classList.toggle("picked", picks.has(p.r)); persist(); counts(); };
    img.onclick = togglePick;
    const star = el("button", "star", "★ " + ALBUM.k + "장"); star.type = "button"; star.onclick = togglePick;
    const scn = el("button", "scn"); scn.type = "button";
    scn.onclick = () => {
      if (sceneOf[p.r]) delete sceneOf[p.r]; else if (sceneById(active)) sceneOf[p.r] = active;
      persist(); renderTags(); renderBarChipsOnly(); counts();
    };
    const acts = el("div", "acts"); acts.append(star, scn);
    card.append(img, el("div", "cap", (p.t || "촬영 시각 미상") + " · " + p.r), el("div", "tag"), acts);
    grid.append(card);
  });
}

function renderAll() { renderBar(); renderTags(); counts(); }

document.getElementById("addScene").onclick = () => {
  const s = {id: nextId++, name: ""}; scenes.push(s); active = s.id; persist(); renderAll();
  const inp = document.querySelector("#edit input"); if (inp) inp.focus();
};

document.getElementById("save").onclick = () => {
  const {rows, orphan} = buildRows();
  if (picks.size !== ALBUM.k && !confirm(`★가 ${picks.size}장입니다. 그래도 저장할까요?`)) return;
  if (orphan && !confirm(`장면에 넣지 않은 ★ 사진 ${orphan}장은 각각 별도 장면으로 저장됩니다. 계속할까요?`)) return;
  const a = el("a");
  a.href = URL.createObjectURL(new Blob([toCsv(rows)], {type: "text/csv"}));
  a.download = "owner_" + ALBUM.file + ".csv";
  document.body.append(a); a.click(); a.remove();
};

document.getElementById("load").onchange = async ev => {
  const f = ev.target.files[0]; if (!f) return;
  try { const miss = importCsv(await f.text()); persist(); renderList(); renderAll(); if (miss) alert(`이 앨범에 없는 사진 ${miss}장은 건너뛰었습니다.`); }
  catch (e) { alert("불러오지 못했습니다: " + e.message); }
  ev.target.value = "";
};

try { const s = JSON.parse(localStorage.getItem(KEY) || "null"); if (s) restore(s); } catch (e) { /* 무시 */ }
renderList(); renderAll();
</script>
</body></html>
"""


def _js(obj):
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")


def main(argv=None):
    ap = argparse.ArgumentParser(description="앨범 주인용 owner.csv 표시 페이지를 만듭니다.")
    ap.add_argument("album", help="원본 사진 폴더")
    ap.add_argument("--album-id", help="owner.csv의 album_id (기본: 폴더 이름)")
    ap.add_argument("--k", type=int, help="고를 장수 (기본 min(10, N))")
    ap.add_argument("--cache", default=str(R.DEFAULT_CACHE))
    ap.add_argument("--work", default="j1_out")
    ap.add_argument("--size", type=int, default=320, help="축소본 긴 변 (기본 320, 최대 512)")
    args = ap.parse_args(argv)

    root = Path(args.album).resolve()
    photos, videos, failed = R.photos_from_folder(root)
    items = R.prepare_items(photos)
    keys = {it.photo_id: R._photo_key(it.path) for it in items}
    bad, _ = R.ensure_work_images([(it.path, keys[it.photo_id]) for it in items], args.cache, log=print)
    items = [it for it in items if keys[it.photo_id] not in bad]
    if not items:
        raise SystemExit("표시할 사진이 없습니다.")
    data = []
    for it in items:
        with Image.open(R.work_image_path(args.cache, keys[it.photo_id])) as im:
            im = im.convert("RGB")
        im.thumbnail((args.size, args.size))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=75)
        d = it.local
        data.append({"r": it.relpath, "src": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode(),
                     "d": "" if d is None else f"{d:%m/%d}({WEEKDAY[d.weekday()]})",
                     "t": "" if d is None else f"{d:%H:%M:%S}"})
    out_dir = album_out_dir(args.work, root)
    out_dir.mkdir(parents=True, exist_ok=True)
    k = args.k or min(10, len(items))
    meta = {"name": root.name, "id": args.album_id or root.name, "file": out_dir.name, "k": k}
    page = (PAGE.replace("__TITLE__", html.escape(f"정답 표시 · {root.name}"))
                .replace("__ALBUM__", html.escape(root.name))
                .replace("__K__", str(k))
                .replace("__ALBUM_JSON__", _js(meta))
                .replace("__PHOTOS_JSON__", _js(data)))
    out = out_dir / f"label_{out_dir.name}.html"
    out.write_text(page, encoding="utf-8")
    print(f"사진 {len(items)}장 (동영상 {videos}개, 읽기 실패 {len(failed) + len(bad)}장), album_id={meta['id']}, K={k}")
    print(f"정답 표시 페이지: {out.resolve()}")
    print("앨범 주인에게 이 파일만 열어 주세요. compare.html(추천 결과)은 owner.csv를 받은 뒤에 보여줍니다.")


if __name__ == "__main__":
    sys.exit(main())
