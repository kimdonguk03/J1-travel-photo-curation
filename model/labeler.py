#!/usr/bin/env python3
"""앨범 주인이 owner.csv를 만드는 페이지를 생성합니다.

  py labeler.py "C:\\Photos\\jeju_trip" --album-id jeju

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
.scenes{display:flex;gap:6px;flex-wrap:nowrap;overflow-x:auto;margin-top:6px;align-items:center;padding-bottom:2px}
.chip{flex:0 0 auto;white-space:nowrap;border-radius:999px;padding:1px 9px;border:2px solid transparent;cursor:pointer;background:var(--btn);font-size:13px}
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
.card img{width:100%;aspect-ratio:1/1;object-fit:contain;background:rgba(127,127,127,.15);border-radius:5px;display:block;cursor:pointer}
.cap{font-size:12px;color:var(--muted);margin:3px 2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tag{font-size:12px;font-weight:700;margin:0 2px 3px;min-height:18px}
.acts{display:flex;gap:4px}.acts button{flex:1;font-size:12px;padding:3px 4px}
.card.picked .star{background:var(--pick);border-color:var(--pick);color:#000}
.card.member{opacity:.92;outline:2px dashed var(--line);outline-offset:-2px}
.more{width:100%;margin-top:4px;font-size:12px;padding:2px 4px}
body.simple .adv{display:none !important}
.card img{cursor:default}
#toast{position:fixed;left:50%;bottom:20px;transform:translateX(-50%);background:var(--accent);color:#fff;padding:8px 14px;border-radius:8px;display:none;z-index:9}
.over b{color:#dc2626}
#step2{position:fixed;inset:0;z-index:20;background:var(--bg);overflow:auto;display:none;padding:12px 16px 40px}
#step2 .top{position:sticky;top:0;background:var(--bg);padding:6px 0 10px;border-bottom:1px solid var(--line);display:flex;gap:10px;align-items:center;flex-wrap:wrap;z-index:2}
#step2 .pick{display:flex;gap:14px;align-items:flex-start;margin:12px 0}
#step2 .pick img{width:260px;height:260px;object-fit:contain;background:rgba(127,127,127,.15);border-radius:8px;border:3px solid var(--pick)}
#step2 .grid{grid-template-columns:repeat(auto-fill,minmax(150px,1fr))}
#step2 .card.alt{border-color:#16a34a}
#step2 .card.alt .altbtn{background:#16a34a;border-color:#16a34a;color:#fff}
</style></head><body class="simple">
<header>
  <div class="bar">
    <strong>__ALBUM__</strong>
    <span class="stat" id="pickStat">★ <b id="nPick">0</b>/__K__장</span>
    <button class="primary" id="save">저장</button>
    <button id="clearAll">모두 지우기</button>
    <button id="step2Btn" hidden>2단계: 대신 써도 되는 사진 (선택)</button>
    <span class="stat" id="shown"></span>
    <button class="adv" id="advToggle" hidden>고급</button>
    <span class="stat adv">중요 장면 <b id="nScene">0</b>개 · 인정 컷 <b id="nCut">0</b>장</span>
    <button class="adv" id="addScene">+ 새 장면</button>
    <label class="btn adv">불러오기<input type="file" id="load" accept=".csv,text/csv" hidden></label>
  </div>
  <div class="scenes adv" id="scenes"></div>
  <div class="edit adv" id="edit"></div>
</header>
<div id="toast"></div>
<div id="step2"></div>
<main>
<details class="help" open><summary><b>하는 법</b></summary>
<ol>
<li>처음에는 아무것도 골라져 있지 않습니다. 이 여행에 못 온 친한 친구에게 보여줄 사진 __K__장에서만 <b>☆ 고르기</b>를 누르세요. 다시 누르면 취소됩니다.</li>
<li>'+3 펼치기'가 붙은 사진은 거의 같은 연사를 한 장으로 접어 둔 것입니다. 묶음 안의 다른 컷이 더 좋으면 펼쳐서 그 컷을 고르세요.</li>
<li>(선택) __K__장을 다 고르면 위에 <b>[2단계]</b> 버튼이 생깁니다. 고른 사진마다 앞뒤 사진을 보여주니, <b>그 사진 대신 보여줘도 괜찮은 사진</b>만 골라 주세요. 평가가 더 정확해집니다.</li>
<li><b>[저장]</b>을 누르고 내려받은 파일을 보내 주세요. 고른 내용은 이 브라우저에 자동 저장됩니다.</li>
</ol>
<p class="cap">사진 순서는 촬영 시각 순서이고, 이 화면에는 추천 결과가 없습니다.</p></details>
<div id="list"></div>
</main>
<script>
const ALBUM = __ALBUM_JSON__;
const PHOTOS = __PHOTOS_JSON__;
const KEY = "j1-owner-v2:" + ALBUM.file;  // 예전 페이지에서 표시한 내용은 불러오지 않음
const INDEX = new Map(PHOTOS.map((p, i) => [p.r, i]));
let picks = new Set(), scenes = [], sceneOf = {}, active = null, nextId = 1, expanded = new Set();
const GROUPS = {}; PHOTOS.forEach((p, i) => { (GROUPS[p.g] = GROUPS[p.g] || []).push(i); });

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
  nPick.textContent = picks.size;
  document.getElementById("pickStat").classList.toggle("over", picks.size > ALBUM.k);
  document.getElementById("step2Btn").hidden = picks.size < Math.min(ALBUM.k, PHOTOS.length) || picks.size === 0; nScene.textContent = scenes.length; nCut.textContent = Object.keys(sceneOf).length;
}

function renderBar() {
  const box = document.getElementById("scenes"); box.textContent = "";
  if (!scenes.length) box.append(el("span", "cap", "아직 장면이 없습니다. [+ 새 장면]으로 만드세요."));
  for (const s of scenes) {
    const n = Object.values(sceneOf).filter(id => id === s.id).length;
    const c = el("span", "chip" + (s.id === active ? " active" : ""), `${label(s).split(" ")[0]} (${n})`);
    c.title = label(s);
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
  scenes.forEach((s, i) => { if (chips[i]) { chips[i].textContent = `${label(s).split(" ")[0]} (${Object.values(sceneOf).filter(id => id === s.id).length})`; chips[i].title = label(s); } });
}

function renderTags() {
  document.querySelectorAll(".card").forEach(card => {
    const p = PHOTOS[+card.dataset.i], id = sceneOf[p.r], s = sceneById(id);
    card.style.borderTopColor = s && !document.body.classList.contains("simple") ? `hsl(${hue(id)} 70% 50%)` : "transparent";
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
  let shown = 0;
  PHOTOS.forEach((p, i) => {
    if (p.n > 1 && !p.lead && !expanded.has(p.g)) return;  // 접힌 연사
    shown++;
    const day = p.d || "촬영 시각 미상";
    if (day !== last) { list.append(el("h2", null, day)); grid = el("div", "grid"); list.append(grid); last = day; }
    const card = el("div", "card" + (picks.has(p.r) ? " picked" : "") + (p.n > 1 && !p.lead ? " member" : "")); card.dataset.i = i;
    const img = el("img"); img.src = p.src; img.alt = p.r; img.title = p.r; img.loading = "lazy";
    const togglePick = () => {
      if (picks.has(p.r)) {
        picks.delete(p.r);
        // ★로 자동 생성한 장면에 이 사진만 있으면 장면도 지움
        // ★로 자동 생성한 장면에 이 묶음 사진만 있고 ★가 하나도 없으면 장면도 지움
        const id = sceneOf[p.r], s = sceneById(id);
        const inScene = Object.keys(sceneOf).filter(r => sceneOf[r] === id);
        if (s && s.auto && inScene.every(r => PHOTOS[INDEX.get(r)].g === p.g && !picks.has(r))) {
          for (const r of inScene) delete sceneOf[r];
          scenes = scenes.filter(x => x !== s);
          if (active === id) active = scenes.length ? scenes[scenes.length - 1].id : null;
        }
      } else {
        if (picks.size >= ALBUM.k) { toast(`★는 ${ALBUM.k}장까지예요. 먼저 하나를 빼 주세요.`); return; }
        picks.add(p.r);
        if (picks.size === ALBUM.k) toast(`${ALBUM.k}장을 다 골랐어요. [저장]하거나 [2단계]로 넘어가세요.`);
        // ★를 누르면 그 사진의 장면을 자동으로 만들고 선택 -> 비슷한 컷은 '넣기'만 누르면 됨
        if (!sceneOf[p.r]) {
          const s = {id: nextId++, name: p.d ? `${p.d} ${p.t.slice(0, 5)}` : "", auto: true};
          scenes.push(s); active = s.id;
          for (const j of GROUPS[p.g]) if (!sceneOf[PHOTOS[j].r]) sceneOf[PHOTOS[j].r] = s.id;  // 접힌 연사 전체
        } else active = sceneOf[p.r];
      }
      card.classList.toggle("picked", picks.has(p.r)); star.textContent = picks.has(p.r) ? "★ 골랐음" : "☆ 고르기"; persist(); renderBar(); renderTags(); renderBarChipsOnly(); counts();
    };
    const star = el("button", "star", picks.has(p.r) ? "★ 골랐음" : "☆ 고르기"); star.type = "button"; star.onclick = togglePick;
    const scn = el("button", "scn adv"); scn.type = "button";
    scn.onclick = () => {
      if (sceneOf[p.r]) delete sceneOf[p.r]; else if (sceneById(active)) sceneOf[p.r] = active;
      persist(); renderTags(); renderBarChipsOnly(); counts();
    };
    const acts = el("div", "acts"); acts.append(star, scn);
    card.append(img, el("div", "cap", (p.t || "촬영 시각 미상") + " · " + p.r), el("div", "tag adv"), acts);
    if (p.n > 1 && p.lead) {
      const more = el("button", "more", expanded.has(p.g) ? "접기" : `+${p.n - 1} 펼치기 (거의 같은 연사)`); more.type = "button";
      more.onclick = () => {
        expanded.has(p.g) ? expanded.delete(p.g) : expanded.add(p.g);
        renderList(); renderAll();
        const c = document.querySelector(`[data-i="${i}"]`); if (c) c.scrollIntoView({block: "center"});
      };
      card.append(more);
    }
    grid.append(card);
  });
  const groupsN = Object.keys(GROUPS).length;
  document.getElementById("shown").textContent = groupsN < PHOTOS.length ? `· 사진 ${PHOTOS.length}장 → 묶어서 ${groupsN}개` : "";
}

function renderAll() { renderBar(); renderTags(); counts(); }
let toastTimer = null;
function toast(msg) {
  const t = document.getElementById("toast"); t.textContent = msg; t.style.display = "block";
  clearTimeout(toastTimer); toastTimer = setTimeout(() => { t.style.display = "none"; }, 2500);
}
// ---- 2단계: 고른 사진마다 '대신 보여줘도 괜찮은 사진' 고르기 ----
let step2At = 0;
function pickOrder() { return PHOTOS.map((p, i) => i).filter(i => picks.has(PHOTOS[i].r)); }
function sceneForPick(i) {
  const p = PHOTOS[i];
  if (!sceneOf[p.r]) {
    const s = {id: nextId++, name: p.d ? `${p.d} ${p.t.slice(0, 5)}` : "", auto: true};
    scenes.push(s); sceneOf[p.r] = s.id;
  }
  return sceneOf[p.r];
}
function neighbors(i) {
  const p = PHOTOS[i], out = [];
  for (let j = Math.max(0, i - 12); j <= Math.min(PHOTOS.length - 1, i + 12); j++) {
    if (j === i) continue;
    const q = PHOTOS[j];
    if (p.ts != null && q.ts != null) { if (p.d !== q.d || Math.abs(q.ts - p.ts) > 1800) continue; }
    else if (p.ts != null || q.ts != null) continue;
    out.push(j);
  }
  return out;
}
function renderStep2() {
  const box = document.getElementById("step2"), order = pickOrder();
  if (!order.length) { box.style.display = "none"; return; }
  step2At = Math.max(0, Math.min(step2At, order.length - 1));
  const i = order[step2At], p = PHOTOS[i], sid = sceneForPick(i);
  box.textContent = "";
  const top = el("div", "top");
  top.append(el("b", null, `2단계 (${step2At + 1}/${order.length})`),
             el("span", null, "노란 테두리 사진 대신 보여줘도 괜찮은 사진만 고르세요. 없으면 [다음]."));
  const prev = el("button", null, "◀ 이전"), next = el("button", "primary", step2At + 1 < order.length ? "다음 ▶" : "끝내기"),
        done = el("button", null, "닫기");
  prev.disabled = step2At === 0;
  prev.onclick = () => { step2At--; renderStep2(); box.scrollTop = 0; };
  next.onclick = () => { if (step2At + 1 < order.length) { step2At++; renderStep2(); box.scrollTop = 0; } else closeStep2(); };
  done.onclick = closeStep2;
  top.append(prev, next, done);
  const pick = el("div", "pick"), big = el("img"); big.src = p.src; big.alt = p.r;
  pick.append(big, el("div", "cap", `고른 사진 · ${p.t || "촬영 시각 미상"} · ${p.r}`));
  const grid = el("div", "grid");
  const ns = neighbors(i);
  for (const j of ns) {
    const q = PHOTOS[j], mine = sceneOf[q.r] === sid, other = !mine && (picks.has(q.r) || (sceneOf[q.r] && sceneOf[q.r] !== sid));
    const card = el("div", "card" + (mine ? " alt" : ""));
    const im = el("img"); im.src = q.src; im.alt = q.r; im.loading = "lazy";
    const b = el("button", "altbtn", other ? (picks.has(q.r) ? "다른 고른 사진" : "다른 사진의 대안") : (mine ? "✓ 대신 써도 됨" : "대신 써도 됨"));
    b.type = "button"; b.disabled = other;
    b.onclick = () => { if (sceneOf[q.r] === sid) delete sceneOf[q.r]; else sceneOf[q.r] = sid; persist(); renderStep2(); };
    card.append(im, el("div", "cap", (q.t || "촬영 시각 미상") + " · " + q.r), b);
    grid.append(card);
  }
  box.append(top, pick, ns.length ? grid : el("p", "cap", "앞뒤로 비교할 사진이 없습니다. [다음]을 누르세요."));
  box.style.display = "block";
}
function closeStep2() {
  document.getElementById("step2").style.display = "none";
  persist(); renderTags(); renderBarChipsOnly(); counts();
  toast("[저장]을 눌러 파일을 내려받으세요.");
}
document.getElementById("step2Btn").onclick = () => { step2At = 0; renderStep2(); };

document.getElementById("clearAll").onclick = () => {
  if (!picks.size || !confirm(`고른 ${picks.size}장을 모두 지울까요?`)) return;
  picks = new Set(); scenes = []; sceneOf = {}; active = null;
  persist(); renderList(); renderAll();
};
// 장면·인정 컷 편집 화면은 주소 끝에 #advanced를 붙여 열 때만 보입니다 (평소에는 숨김)
if (location.hash === "#advanced") document.body.classList.remove("simple");

document.getElementById("addScene").onclick = () => {
  const s = {id: nextId++, name: ""}; scenes.push(s); active = s.id; persist(); renderAll();
  const inp = document.querySelector("#edit input"); if (inp) inp.focus();
};

document.getElementById("save").onclick = () => {
  const {rows, orphan} = buildRows();
  if (picks.size !== ALBUM.k && !confirm(`★가 ${picks.size}장입니다. 그래도 저장할까요?`)) return;
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


DUP_SIM = 0.96      # 정답 화면에서 접을 '거의 같은 연사'의 유사도 하한 (추천 기준값보다 엄격하게)
DUP_GAP_SEC = 10    # 접을 연사의 연속 촬영 간격 상한(초)


def dup_groups(a, sim_th, gap_sec):
    """촬영순으로 보며 직전 사진과 gap_sec 이내, 묶음 첫 사진과 유사도 sim_th 이상이면 같은 묶음."""
    groups = []
    for i, it in enumerate(a.items):
        if groups:
            g = groups[-1]
            prev = a.items[g[-1]]
            if (it.t is not None and prev.t is not None and it.t - prev.t <= gap_sec
                    and R.day_of(it, a.params) == R.day_of(prev, a.params)
                    and float(a.emb[g[0]] @ a.emb[i]) >= sim_th):
                g.append(i)
                continue
        groups.append([i])
    return groups


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
    ap.add_argument("--embedder", choices=["clip", "tiny", "none"], default="clip",
                    help="거의 같은 연사를 접을 때 쓰는 임베딩 (none이면 접지 않음)")
    ap.add_argument("--clip-model")
    ap.add_argument("--dup-sim", type=float, default=DUP_SIM, help=f"접을 연사의 유사도 하한 (기본 {DUP_SIM})")
    ap.add_argument("--dup-gap", type=float, default=DUP_GAP_SEC, help=f"접을 연사의 촬영 간격 상한(초, 기본 {DUP_GAP_SEC})")
    args = ap.parse_args(argv)

    root = Path(args.album).resolve()
    photos, videos, failed = R.photos_from_folder(root)
    try:
        a = R.analyze(photos, embedder=args.embedder, clip_model=args.clip_model, cache_dir=args.cache,
                      drop_failed=True, log=print)
    except ValueError:
        raise SystemExit("표시할 사진이 없습니다.")
    items = a.items
    groups = dup_groups(a, args.dup_sim, args.dup_gap) if a.emb is not None else [[i] for i in range(len(items))]
    info = {}
    for gi, g in enumerate(groups):
        lead = max(g, key=lambda i: (a.sharp[i], -i))
        for i in g:
            info[i] = (gi, i == lead, len(g))
    data = []
    for i, it in enumerate(items):
        with Image.open(R.work_image_path(args.cache, R._photo_key(it.path))) as im:
            im = im.convert("RGB")
        im.thumbnail((args.size, args.size))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=75)
        d = it.local
        data.append({"r": it.relpath, "src": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode(),
                     "d": "" if d is None else f"{d:%m/%d}({WEEKDAY[d.weekday()]})",
                     "t": "" if d is None else f"{d:%H:%M:%S}",
                     "g": info[i][0], "lead": info[i][1], "n": info[i][2], "ts": it.t})
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
    print(f"사진 {len(items)}장 (동영상 {videos}개, 읽기 실패 {len(failed) + len(a.failed)}장), album_id={meta['id']}, K={k}")
    if len(groups) < len(items):
        print(f"거의 같은 연사(유사도 {args.dup_sim} 이상, {args.dup_gap:g}초 이내)를 접어서 {len(groups)}개로 표시합니다.")
    print(f"정답 표시 페이지: {out.resolve()}")
    print("앨범 주인에게 이 파일만 열어 주세요. compare.html(추천 결과)은 owner.csv를 받은 뒤에 보여줍니다.")


if __name__ == "__main__":
    sys.exit(main())
