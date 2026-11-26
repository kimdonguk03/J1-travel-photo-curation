#!/usr/bin/env python3
"""초안 평가: 앨범 주인이 추천 초안 사진을 직접 판정하는 페이지와 채점.

  py draft_review.py "C:\\Photos\\jeju_trip" --album-id jeju --owner owner_jeju.csv   # 평가 페이지 만들기
  py draft_review.py --score review_jeju.csv [review_busan.csv ...]                 # 방식별 채점

페이지에는 세 방식의 초안 사진을 섞어서, 어느 방식이 고른 사진인지 모르게 보여줍니다.
같은 사진을 여러 방식이 골랐으면 한 번만 보여주고, 그 판정을 고른 방식 모두에 씁니다.
  proposal    제안 방식 (params.json 그대로)
  no_quality  제안 방식에서 관련도의 화질·미적 점수를 끈 것 (quality_weight=0, aesthetic_weight=0).
              묶음 안 대표 컷 순위 모델(rank_model)은 그대로라 선명도는 대표 컷 고르기에 남습니다.
  uniform     촬영 순번 균등 추출 (기준선)

주인은 사진마다 따로 답합니다.
  1) 친구에게 보여줄 최종 10장에 이 사진을 그대로 넣어도 되나요?        예 / 아니오   -> 수용률
  2) 이 사진에서 흔들림이나 흐림이 눈에 띄나요?                         예 / 아니오   -> 흐림 수
  3) (--owner를 주면) 미리 정한 중요 장면 중 이 사진으로 대신 보여줄 수 있는 장면은?
     장면 번호 하나 또는 '해당 없음'                                              -> 인정 장면
두 질문을 나눠 받으므로, 조금 흔들렸지만 넣고 싶은 사진도 그대로 기록됩니다.

인정 장면 = 그 방식의 초안이 담은 서로 다른 장면 수 (같은 장면을 여러 장 담아도 한 번).
  장면은 정답 페이지(labeler.py)의 scene_id입니다. 기본 표시 방식에서는 ★ 하나마다 장면이 하나라,
  장면과 주인이 고른 사진이 일대일입니다.
자동 대응 = 페이지를 만들 때 사진마다 evaluate.py의 '같은 순간' 규칙(같은 사진, 또는 10분 이내이면서
  CLIP 유사도 0.80 이상)으로 대응되는 장면을 미리 계산해 CSV에 함께 남깁니다(화면에는 보이지 않음).
  채점할 때 주인 판정과 사진 단위로 대조합니다: 같은 장면 / 자동만 / 주인만 / 서로 다른 장면 / 둘 다 없음.

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
AGREE = ["same", "auto_only", "owner_only", "different", "neither"]
AGREE_KO = {"same": "같은 장면", "auto_only": "자동만", "owner_only": "주인만", "different": "서로 다른 장면", "neither": "둘 다 없음"}

PAGE = r"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
:root{--bg:#f7f7f5;--fg:#1d1d1b;--muted:#6a6a64;--card:#fff;--line:#deded8;--accent:#b45309;--yes:#16a34a;--no:#dc2626;--btn:#ececE8}
@media (prefers-color-scheme:dark){:root{--bg:#151514;--fg:#ebebe8;--muted:#9b9b94;--card:#1f1f1d;--line:#36362f;--accent:#f59e0b;--yes:#4ade80;--no:#f87171;--btn:#2c2c29}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,"Malgun Gothic",sans-serif}
header{position:sticky;top:0;z-index:5;background:var(--bg);border-bottom:1px solid var(--line);padding:8px 16px;display:flex;gap:12px;align-items:center;flex-wrap:wrap}
header strong{font-size:16px}.stat b{color:var(--accent)}
button{font:inherit;border:1px solid var(--line);background:var(--btn);color:var(--fg);border-radius:6px;padding:4px 12px;cursor:pointer}
button.primary{background:var(--accent);border-color:var(--accent);color:#fff}
main{max-width:1200px;margin:0 auto;padding:12px 16px 60px}
.help{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 14px;margin-bottom:14px}
.help ol{margin:4px 0;padding-left:20px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px}
.card{background:var(--card);border:3px solid transparent;border-radius:10px;padding:6px}
.card.done{border-color:var(--line)}
.card img{width:100%;aspect-ratio:4/3;object-fit:contain;background:rgba(127,127,127,.15);border-radius:6px;display:block}
.cap{font-size:12px;color:var(--muted);margin:4px 2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.q{display:flex;align-items:center;gap:6px;margin-top:4px;font-size:12px}.q span{flex:1}.q button{padding:2px 10px}
.q button.on.y{background:var(--yes);border-color:var(--yes);color:#fff}.q button.on.n{background:var(--no);border-color:var(--no);color:#fff}
.scenes{display:flex;gap:8px;overflow-x:auto;padding:4px 0 8px}.sc{flex:0 0 130px;font-size:12px;color:var(--muted)}
.sc img{width:130px;height:98px;object-fit:cover;border-radius:6px;display:block}.sc b{color:var(--accent);font-size:14px}
.scene{width:100%;margin-top:6px;font:inherit;padding:3px;border:1px solid var(--line);border-radius:6px;background:var(--btn);color:var(--fg)}
.scene.set{border-color:var(--accent)}
</style></head><body>
<header><strong>__ALBUM__</strong><span class="stat">다 답한 사진 <b id="done">0</b>/__N__장</span>
<button class="primary" id="save">저장</button></header>
<main>
<div class="help"><b>하는 법</b> · 아래는 추천 프로그램이 고른 사진들을 섞어 놓은 것입니다(순서는 무작위). 사진마다 아래 질문에 답해 주세요.
<ol><li><b>여행에 함께 가지 않은 친구에게 보여줄 최종 10장에 이 사진을 그대로 넣어도 되나요?</b> 내가 고른 10장과 달라도, 그대로 넣어도 되면 '예'입니다.</li>
<li><b>이 사진에서 흔들림이나 흐림이 눈에 띄나요?</b> 1번과 따로 답합니다. 조금 흔들렸지만 넣고 싶은 사진이면 1번 '예', 2번 '예'입니다.</li>
<li id="scenehelp" hidden><b>미리 정한 중요 장면 중 이 사진으로 대신 보여줄 수 있는 장면은 무엇인가요?</b> 바로 아래 번호 붙은 사진이 내가 정한 장면입니다. 어느 장면도 대신할 수 없으면 '해당 없음'을 고르세요.</li></ol>
다 답하면 [저장]을 누르고 파일을 보내 주세요.</div>
<div class="scenes" id="scenes" hidden></div>
<div class="grid" id="grid"></div>
</main>
<script>
const ALBUM = __META__;
const PHOTOS = __PHOTOS__;
const SCENES = __SCENES__;  // [{id, n, name, src}] 주인이 정한 중요 장면. 비어 있으면 장면 고르기 없음
const KEY = "j1-review2:" + ALBUM.file + ":" + ALBUM.rule_version;
let keep = {}, blur = {}, scene = {};
try { const s = JSON.parse(localStorage.getItem(KEY) || "{}") || {}; keep = s.keep || {}; blur = s.blur || {}; scene = s.scene || {}; } catch (e) {}
function persist() { try { localStorage.setItem(KEY, JSON.stringify({keep, blur, scene})); } catch (e) {} }
function el(t, c, x) { const e = document.createElement(t); if (c) e.className = c; if (x != null) e.textContent = x; return e; }
const answered = p => keep[p.r] && blur[p.r] && (!SCENES.length || scene[p.r]);
if (SCENES.length) {
  document.getElementById("scenehelp").hidden = false;
  const box = document.getElementById("scenes"); box.hidden = false;
  for (const s of SCENES) {
    const d = el("div", "sc"); const im = el("img"); im.src = s.src; im.alt = s.n + "번 장면";
    const cap = el("div"); cap.append(el("b", "", s.n + "번"), " " + s.name);
    d.append(im, cap); box.append(d);
  }
}
function yesno(label, store, p) {
  const row = el("div", "q"); row.append(el("span", "", label));
  for (const [v, t] of [["y", "예"], ["n", "아니오"]]) {
    const b = el("button", v + (store[p.r] === v ? " on" : ""), t);
    b.onclick = () => { store[p.r] = v; persist(); render(); };
    row.append(b);
  }
  return row;
}
function render() {
  const g = document.getElementById("grid"); g.textContent = "";
  for (const p of PHOTOS) {
    const card = el("div", "card" + (answered(p) ? " done" : ""));
    const img = el("img"); img.src = p.src; img.alt = p.r; img.loading = "lazy";
    card.append(img, el("div", "cap", p.t), yesno("1. 최종 10장에 넣어도 됨", keep, p), yesno("2. 흔들림·흐림이 눈에 띔", blur, p));
    if (SCENES.length) {
      const sel = el("select", "scene" + (scene[p.r] ? " set" : ""));
      sel.append(new Option("3. 대신 보여줄 수 있는 장면 고르기", ""), new Option("해당 없음", "none"));
      for (const s of SCENES) sel.append(new Option(s.n + "번 장면 (" + s.name + ")", s.id));
      sel.value = scene[p.r] || "";
      sel.onchange = () => { if (sel.value) scene[p.r] = sel.value; else delete scene[p.r]; persist(); render(); };
      card.append(sel);
    }
    g.append(card);
  }
  document.getElementById("done").textContent = PHOTOS.filter(answered).length;
}
document.getElementById("save").onclick = () => {
  const left = PHOTOS.filter(p => !answered(p)).length;
  if (left && !confirm(`아직 ${left}장에 다 답하지 않았습니다. 그래도 저장할까요?`)) return;
  const q = v => { v = String(v); return /[",\r\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v; };
  const lines = ["album_id,relpath,keep,blur,scene,auto_scenes," + ALBUM.methods.map(m => "in_" + m).join(",") + ",rule_version"];
  for (const p of PHOTOS) lines.push([ALBUM.id, p.r, keep[p.r] || "", blur[p.r] || "", scene[p.r] || "", p.a.join(";"),
    ...ALBUM.methods.map(m => p.m.includes(m) ? 1 : 0), ALBUM.rule_version].map(q).join(","));
  const a = el("a"); a.href = URL.createObjectURL(new Blob(["\ufeff" + lines.join("\r\n") + "\r\n"], {type: "text/csv"}));
  a.download = "review_" + ALBUM.file + ".csv"; document.body.append(a); a.click(); a.remove();
};
render();
</script></body></html>
"""


def drafts(a):
    """방식별 초안 인덱스. no_quality는 같은 묶음·선택 규칙에서 관련도의 화질·미적 점수를 끈 것."""
    nq = R.Analysis(a.items, a.sharp, a.emb, dict(a.params, quality_weight=0.0, aesthetic_weight=0.0),
                    a.failed, a.timing, a.embedder_name)
    return {"proposal": a.run("time_clip"), "no_quality": nq.run("time_clip"), "uniform": a.run("uniform")}


def scene_name(sid):
    """'S01_07/28(화) 09:46' -> '07/28(화) 09:46'. 이름이 없으면 scene_id 그대로."""
    head, _, name = sid.partition("_")
    return name or head


def owner_scenes(a, owner):
    """주인이 정한 중요 장면 [(대표 사진 인덱스, scene_id, 장면의 ★ 사진 인덱스들)]. 대표 사진의 촬영순으로 번호를 붙입니다."""
    index = {it.relpath: i for i, it in enumerate(a.items)}
    reps = []
    for sid, cuts in owner.scenes.items():
        picked = sorted(index[r] for r in cuts & owner.picks if r in index)
        if picked:
            reps.append((picked[0], sid, picked))
    reps.sort()
    if not reps:
        raise SystemExit("owner.csv에서 이 앨범의 사진과 맞는 owner_pick 사진을 찾지 못했습니다. 앨범 폴더와 정답 파일을 확인하세요.")
    return reps


def auto_scenes(a, i, reps, minutes=E.MOMENT_MINUTES, sim=E.MOMENT_SIM):
    """사진 i가 evaluate.py의 '같은 순간' 규칙으로 대응되는 장면 id 목록."""
    out = []
    for _, sid, picked in reps:
        for p in picked:
            tp, ti = a.items[p].t, a.items[i].t
            close = p == i or (tp is not None and ti is not None and abs(tp - ti) <= minutes * 60)
            if close and float(a.emb[p] @ a.emb[i]) >= sim:
                out.append(sid)
                break
    return out


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

    reps = owner_scenes(a, E.load_owner_csv(args.owner)) if args.owner else []
    data = []
    for i in order:
        it = a.items[i]
        data.append({"r": it.relpath, "m": member[i], "src": thumb(i, 480), "a": auto_scenes(a, i, reps),
                     "t": "촬영 시각 미상" if it.local is None else f"{it.local:%m/%d %H:%M}"})
    scenes = [{"id": sid, "n": n, "name": scene_name(sid), "src": thumb(i, 260)} for n, (i, sid, _) in enumerate(reps, 1)]
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
        multi = sum(len(p) > 1 for _, _, p in reps)
        print(f"장면 고르기: 중요 장면 {len(scenes)}개" + (f" (★ 사진이 2장 이상인 장면 {multi}개)" if multi else
                                                    " (장면과 주인이 고른 사진이 일대일)"))
    print(f"초안 평가 페이지: {path.resolve()}")
    print("정답(owner.csv) 표시를 마친 앨범 주인에게만 보여주세요.")


def scene_set(rows, col="scene"):
    """인정된 서로 다른 장면 id 집합 ('none'과 빈 칸 제외). auto_scenes 열은 ';'로 여러 개."""
    out = set()
    for r in rows:
        out |= set((r.get(col) or "").split(";"))
    return out - {"", "none"}


def scene_hits(rows):
    """주인이 인정한 서로 다른 장면 수. 같은 장면을 여러 장 담아도 한 번만 셉니다."""
    return len(scene_set(rows))


def agreement(row):
    """사진 하나에서 자동 대응과 주인 판정의 관계."""
    h = (row.get("scene") or "").strip()
    auto = scene_set([row], "auto_scenes")
    owner = h not in ("", "none")
    if owner and h in auto:
        return "same"
    if owner and auto:
        return "different"
    if owner:
        return "owner_only"
    if auto:
        return "auto_only"
    return "neither"


def method_stats(rows):
    """한 방식의 초안 사진 행들 -> 지표 dict."""
    st = {"n": len(rows), "keep": sum(r.get("keep") == "y" for r in rows), "blur": sum(r.get("blur") == "y" for r in rows),
          "missing": sum(not (r.get("keep") and r.get("blur")) for r in rows),
          "scenes": scene_hits(rows), "auto": len(scene_set(rows, "auto_scenes")),
          "unscened": sum(not r.get("scene") for r in rows)}
    st.update({k: 0 for k in AGREE})
    for r in rows:
        if r.get("scene"):
            st[agreement(r)] += 1
    return st


def score(paths):
    """방식별·앨범별 수용률, 흐림 수, 인정 장면(주인/자동)을 출력하고, 자동 대응과 주인 판정을 사진 단위로 대조합니다."""
    albums = []
    for p in paths:
        with open(p, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        if rows and "keep" not in rows[0]:
            raise SystemExit(f"{p}: 예전 형식의 CSV입니다(keep·blur 열 없음). 새 페이지로 다시 받아 주세요.")
        albums.append((rows[0]["album_id"] if rows else Path(p).stem,
                       {m: method_stats([r for r in rows if r.get(f"in_{m}") == "1"]) for m in METHODS}))

    print("### 수용률 · 흐림 · 인정 장면 (주인 / 자동)")
    print("| 앨범 | " + " | ".join(f"{m} 넣어도 됨 · 흐림 · 장면 주인/자동" for m in METHODS) + " |")
    print("|---|" + "---|" * len(METHODS))
    tot = {m: {k: 0 for k in ("n", "keep", "blur", "scenes", "auto")} for m in METHODS}
    for album, st in albums:
        cells = []
        for m in METHODS:
            s = st[m]
            for k in tot[m]:
                tot[m][k] += s[k]
            note = [f"미응답 {s['missing']}"] if s["missing"] else []
            if s["unscened"]:
                note.append(f"장면 미표시 {s['unscened']}")
            cells.append(f"{s['keep']}/{s['n']} · {s['blur']} · {s['scenes']}/{s['auto']}" + (f" ({', '.join(note)})" if note else ""))
        print(f"| {album} | " + " | ".join(cells) + " |")
    if len(albums) > 1:
        print("| 합계 | " + " | ".join(f"{t['keep']}/{t['n']} · {t['blur']} · {t['scenes']}/{t['auto']}" for t in tot.values()) + " |")

    print("\n### 흐림 수 차이 (no_quality - proposal, 클수록 제안 방식 초안에 흐린 컷이 적음)")
    for album, st in albums:
        print(f"- {album}: {st['no_quality']['blur']} - {st['proposal']['blur']} = {st['no_quality']['blur'] - st['proposal']['blur']}")

    print("\n### 자동 대응과 주인 판정 대조 (사진 단위, 장면을 표시한 사진만)")
    print("| 앨범 | 방식 | " + " | ".join(AGREE_KO[k] for k in AGREE) + " |")
    print("|---|---|" + "---|" * len(AGREE))
    for album, st in albums:
        for m in ("proposal", "uniform"):
            print(f"| {album} | {m} | " + " | ".join(str(st[m][k]) for k in AGREE) + " |")
    print()
    print("넣어도 됨 = 1번에 '예'인 사진 수 / 초안 수, 흐림 = 2번에 '예'인 사진 수, "
          "장면 주인/자동 = 그 초안이 담은 서로 다른 장면 수(주인 판정 / '같은 순간' 규칙). "
          "proposal=제안, no_quality=관련도의 화질·미적 점수 끔, uniform=균등 추출. "
          "판정은 docs/experiments.md의 판정 규칙(앨범별 방향)을 따릅니다.")


def main(argv=None):
    ap = argparse.ArgumentParser(description="초안 평가 페이지 만들기와 채점")
    ap.add_argument("album", nargs="?", help="평가 앨범 폴더")
    ap.add_argument("--album-id")
    ap.add_argument("--owner", help="이 앨범의 owner.csv. 주면 사진마다 '어느 중요 장면을 대신 보여줄 수 있는지'도 받습니다")
    ap.add_argument("--score", nargs="+", metavar="REVIEW_CSV", help="저장된 review_*.csv로 채점")
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
