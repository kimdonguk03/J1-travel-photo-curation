#!/usr/bin/env python3
"""앨범 주인이 정답을 표시하는 HTML 페이지를 만듭니다.

  py labeler.py "C:\\Photos\\여행원본"

만들어진 label_*.html을 크롬이나 엣지로 열어 표시하면 됩니다.
  1) 친구에게 보여줄 10장에 ★
  2) 장면이 바뀌는 첫 사진에서 '새 장면'을 누르고 장면 이름 입력
  3) 10장에 빠지면 아쉬운 장면에 '꼭 필요' 체크
  4) [라벨 저장]으로 labels_*.json 받기 -> evaluate.py에 넣습니다.

이 페이지에는 알고리즘 결과가 들어 있지 않습니다. 정답은 반드시 알고리즘 결과를 보기 전에 받으세요.
"""
from __future__ import annotations

import argparse
import html
import json
import sys

from curation import (DEFAULT_PARAMS, album_work_dir, day_key, ensure_work_images, image_data_uri, load_album,
                      load_work_image)

WEEKDAY = "월화수목금토일"

PAGE = r"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
:root{--bg:#f7f7f5;--fg:#1d1d1b;--muted:#6a6a64;--card:#fff;--line:#deded8;--a:#ffffff;--b:#efefeb;--accent:#b45309;--pick:#ca8a04;--btn:#ececE8}
@media (prefers-color-scheme:dark){:root{--bg:#151514;--fg:#ebebe8;--muted:#9b9b94;--card:#1f1f1d;--line:#36362f;--a:#1b1b1a;--b:#25251f;--accent:#f59e0b;--pick:#facc15;--btn:#2c2c29}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,"Malgun Gothic",sans-serif}
header{position:sticky;top:0;z-index:5;background:var(--bg);border-bottom:1px solid var(--line);padding:10px 16px;display:flex;gap:14px;align-items:center;flex-wrap:wrap}
header strong{font-size:16px}
.stat{font-variant-numeric:tabular-nums}
.stat b{color:var(--accent)}
button,.btn{font:inherit;border:1px solid var(--line);background:var(--btn);color:var(--fg);border-radius:6px;padding:4px 10px;cursor:pointer}
button.primary{background:var(--accent);border-color:var(--accent);color:#fff}
main{max-width:1500px;margin:0 auto;padding:12px 16px 80px}
.help{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 14px;margin-bottom:14px}
.help ol{margin:6px 0 0;padding-left:20px}.help li{margin:2px 0}
.scene{border:1px solid var(--line);border-radius:10px;padding:10px;margin:0 0 10px}
.scene.a{background:var(--a)}.scene.b{background:var(--b)}
.scene-head{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:8px}
.scene-head .no{font-weight:700;min-width:58px}
.scene-head input[type=text]{font:inherit;flex:1 1 220px;max-width:420px;padding:4px 8px;border:1px solid var(--line);border-radius:6px;background:var(--card);color:var(--fg)}
.scene-head label{display:flex;gap:4px;align-items:center;cursor:pointer}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:8px}
.card{background:var(--card);border:2px solid transparent;border-radius:8px;padding:4px}
.card.picked{border-color:var(--pick)}
.card img{width:100%;aspect-ratio:1/1;object-fit:cover;border-radius:5px;display:block;cursor:pointer}
.cap{font-size:12px;color:var(--muted);margin:3px 2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.acts{display:flex;gap:4px}
.acts button{flex:1;font-size:12px;padding:3px 4px}
.card.picked .star{background:var(--pick);border-color:var(--pick);color:#000}
.cut[disabled]{opacity:.45;cursor:default}
</style></head><body>
<header>
  <strong>__ALBUM__</strong>
  <span class="stat">★ <b id="nPick">0</b>/__K__장</span>
  <span class="stat">장면 <b id="nScene">1</b>개 · 꼭 필요 <b id="nMust">0</b>개</span>
  <button class="primary" id="save">라벨 저장 (JSON)</button>
  <label class="btn">불러오기<input type="file" id="load" accept=".json,application/json" hidden></label>
</header>
<main>
<details class="help" open><summary><b>표시 순서</b> (사진은 촬영 시각 순서입니다. 이 화면에는 알고리즘 결과가 없습니다.)</summary>
<ol>
<li><b>먼저</b> 이 여행에 못 온 친한 친구에게 보여줄 __K__장을 고르세요. 사진을 누르거나 ★ 버튼을 누릅니다. 휴대폰에서 이미 골랐다면 같은 사진에 ★를 표시하세요.</li>
<li>그다음 처음부터 훑으며 <b>장면이 바뀌는 첫 사진</b>에서 '새 장면'을 누르고 장면 이름을 적으세요. 잘못 나눴으면 '합치기'를 누릅니다.
장면은 친구에게 "이때는 뭐 했어"라고 따로 말할 만한 단위입니다(예: 공항, 해변 단체사진, 해변 산책, 저녁 식사). 보통 하루 5~10개입니다.</li>
<li>__K__장 안에 빠지면 아쉬운 장면에 '꼭 필요'를 체크하세요.</li>
<li>[라벨 저장]을 눌러 JSON 파일을 팀에 보내 주세요. 표시 내용은 이 브라우저에도 자동 저장됩니다.</li>
</ol></details>
<div id="list"></div>
</main>
<script>
const ALBUM = __ALBUM_JSON__;
const PHOTOS = __PHOTOS_JSON__;
const KEY = "j1-labels:" + ALBUM.id;
const INDEX = new Map(PHOTOS.map((p, i) => [p.n, i]));
let picks = new Set();
let starts = {};  // 사진 이름 -> {title, must}; 첫 사진은 항상 장면 시작

function el(tag, cls, text) { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }

function buildLabels() {
  const scenes = [];
  PHOTOS.forEach((p, i) => {
    if (i === 0 || starts[p.n]) { const s = starts[p.n] || {title: "", must: false}; scenes.push({start: p.n, title: s.title, must: !!s.must}); }
  });
  return {format: "j1-labels-v1", album: ALBUM.name, album_id: ALBUM.id, k: ALBUM.k,
          order: PHOTOS.map(p => p.n), picks: PHOTOS.filter(p => picks.has(p.n)).map(p => p.n),
          scenes, saved_at: new Date().toISOString()};
}

function applyLabels(d) {
  picks = new Set((d.picks || []).filter(n => INDEX.has(n)));
  starts = {};
  for (const s of (d.scenes || [])) if (INDEX.has(s.start)) starts[s.start] = {title: s.title || "", must: !!s.must};
}

function persist() { try { localStorage.setItem(KEY, JSON.stringify(buildLabels())); } catch (e) { /* 저장소를 못 쓰면 내보내기만 사용 */ } }

function updateCounts() {
  const d = buildLabels();
  document.getElementById("nPick").textContent = d.picks.length;
  document.getElementById("nScene").textContent = d.scenes.length;
  document.getElementById("nMust").textContent = d.scenes.filter(s => s.must).length;
}

function togglePick(name, card) {
  if (picks.has(name)) picks.delete(name); else picks.add(name);
  card.classList.toggle("picked", picks.has(name));
  persist(); updateCounts();
}

function toggleStart(name) {
  if (starts[name]) delete starts[name]; else starts[name] = {title: "", must: false};
  persist(); render();
  const c = document.querySelector(`[data-i="${INDEX.get(name)}"]`);
  if (c) c.scrollIntoView({block: "center"});
}

function render() {
  const list = document.getElementById("list");
  list.textContent = "";
  let grid = null, no = 0;
  PHOTOS.forEach((p, i) => {
    if (i === 0 || starts[p.n]) {
      no++;
      if (!starts[p.n]) starts[p.n] = {title: "", must: false};
      const st = starts[p.n];
      const sec = el("section", "scene " + (no % 2 ? "a" : "b"));
      const head = el("div", "scene-head");
      head.append(el("span", "no", "장면 " + no));
      const t = el("input"); t.type = "text"; t.placeholder = "장면 이름 (예: 해변 단체사진)"; t.value = st.title;
      t.oninput = () => { st.title = t.value; persist(); };
      const lab = el("label"); const cb = el("input"); cb.type = "checkbox"; cb.checked = st.must;
      cb.onchange = () => { st.must = cb.checked; persist(); updateCounts(); };
      lab.append(cb, document.createTextNode("꼭 필요"));
      head.append(t, lab);
      grid = el("div", "grid");
      sec.append(head, grid);
      list.append(sec);
    }
    const card = el("div", "card" + (picks.has(p.n) ? " picked" : ""));
    card.dataset.i = i;
    const img = el("img"); img.src = p.src; img.alt = p.n; img.title = p.n; img.loading = "lazy";
    img.onclick = () => togglePick(p.n, card);
    const acts = el("div", "acts");
    const star = el("button", "star", "★ " + ALBUM.k + "장"); star.type = "button";
    star.onclick = () => togglePick(p.n, card);
    const cut = el("button", "cut", i === 0 ? "첫 장면" : (starts[p.n] ? "합치기" : "새 장면"));
    cut.type = "button"; cut.disabled = i === 0;
    cut.title = i === 0 ? "" : (starts[p.n] ? "이 장면을 앞 장면과 합칩니다" : "이 사진부터 새 장면으로 나눕니다");
    cut.onclick = () => toggleStart(p.n);
    acts.append(star, cut);
    card.append(img, el("div", "cap", p.d + " " + p.t), acts);
    grid.append(card);
  });
  updateCounts();
}

document.getElementById("save").onclick = () => {
  const d = buildLabels();
  if (d.picks.length !== ALBUM.k && !confirm(`★가 ${d.picks.length}장입니다. 그래도 저장할까요?`)) return;
  const blank = d.scenes.filter(s => !s.title.trim()).length;
  if (blank && !confirm(`이름 없는 장면이 ${blank}개 있습니다. 그래도 저장할까요?`)) return;
  const a = el("a");
  a.href = URL.createObjectURL(new Blob([JSON.stringify(d, null, 2)], {type: "application/json"}));
  a.download = "labels_" + ALBUM.file + ".json";
  document.body.append(a); a.click(); a.remove();
};

document.getElementById("load").onchange = async (ev) => {
  const f = ev.target.files[0]; if (!f) return;
  try {
    const d = JSON.parse(await f.text());
    if (d.format !== "j1-labels-v1") throw new Error("형식이 다릅니다");
    if (d.album_id && d.album_id !== ALBUM.id && !confirm("다른 앨범의 라벨 같습니다. 그래도 불러올까요?")) return;
    applyLabels(d); persist(); render();
  } catch (e) { alert("불러오지 못했습니다: " + e.message); }
  ev.target.value = "";
};

try { const saved = JSON.parse(localStorage.getItem(KEY) || "null"); if (saved) applyLabels(saved); } catch (e) { /* 무시 */ }
render();
</script>
</body></html>
"""


def _js(obj):
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")


def main(argv=None):
    ap = argparse.ArgumentParser(description="앨범 주인용 정답 표시 페이지를 만듭니다.")
    ap.add_argument("album", help="미선별 원본 사진 폴더")
    ap.add_argument("--work", default="j1_out", help="결과 폴더 (기본 j1_out)")
    ap.add_argument("--k", type=int, default=DEFAULT_PARAMS["k"], help="고를 장수 (기본 10)")
    ap.add_argument("--size", type=int, default=320, help="축소본 긴 변 픽셀 (기본 320, 최대 448)")
    args = ap.parse_args(argv)

    album = load_album(args.album)
    out_dir = album_work_dir(args.work, album.root)
    out_dir.mkdir(parents=True, exist_ok=True)
    # 원본은 여기서 한 번만 디코딩하고 캐시합니다. curation.py / evaluate.py가 같은 캐시를 다시 씁니다.
    ensure_work_images(album, out_dir)
    start_hour = DEFAULT_PARAMS["day_start_hour"]
    days = sorted({day_key(p.local, start_hour) for p in album.photos})
    day_no = {d: i + 1 for i, d in enumerate(days)}

    items = []
    for p in album.photos:
        d = p.local
        items.append({"n": p.name, "src": image_data_uri(load_work_image(out_dir, p), args.size, quality=75),
                      "d": f"D{day_no[day_key(d, start_hour)]} {d:%m/%d}({WEEKDAY[d.weekday()]})",
                      "t": f"{d:%H:%M:%S}"})
    if not items:
        raise SystemExit("표시할 사진이 없습니다.")

    file_tag = out_dir.name
    meta = {"name": album.root.name, "id": file_tag, "file": file_tag, "k": args.k}
    page = (PAGE.replace("__TITLE__", html.escape(f"정답 표시 · {album.root.name}"))
                .replace("__ALBUM__", html.escape(album.root.name))
                .replace("__K__", str(args.k))
                .replace("__ALBUM_JSON__", _js(meta))
                .replace("__PHOTOS_JSON__", _js(items)))
    out = out_dir / f"label_{file_tag}.html"
    out.write_text(page, encoding="utf-8")
    print(f"사진 {len(items)}장, 실패 {len(album.failed)}장")
    for n, why in album.failed[:5]:
        print(f"  - {n}: {why}")
    print(f"정답 표시 페이지: {out.resolve()}")
    print("앨범 주인에게 이 파일만 열어 주세요. compare.html(알고리즘 결과)은 정답을 받은 뒤에 보여줍니다.")


if __name__ == "__main__":
    sys.exit(main())
