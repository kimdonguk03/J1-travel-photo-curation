#!/usr/bin/env python3
"""모델 서버: 사진 읽기, 썸네일, 추천을 HTTP로 제공합니다. 백엔드(Spring)가 같은 PC에서 호출합니다.

  py server.py --root "C:\\j1_data\\albums"                 # http://127.0.0.1:8001, API 문서는 /docs
  py server.py --root D:\\uploads --port 8001 --cache D:\\j1_cache

엔드포인트 (요청·응답 예시는 docs/api.md)
  GET  /health                  모델 로딩 여부, rule_version
  POST /scan       {folder}     폴더 안 사진 목록, 촬영 시각, 동영상 수, 읽기 실패
  GET  /thumb?path=..&size=512  정방향 JPEG (목록 512, 큰 미리보기 1600)
  POST /recommend  {folder | photos, k}   묶음, 초안, rule_version

보안
  - 기본으로 127.0.0.1에만 열립니다. 바깥에 공개하지 말고, 백엔드만 이 서버를 부르게 하세요.
  - --root로 준 폴더(와 그 하위) 밖의 경로는 거부합니다(403). 여러 개 줄 수 있습니다.
"""
from __future__ import annotations

import argparse
import sys
import threading
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

import j1_image as J
import recommend as R

PARAMS_FILE = Path(__file__).with_name("params.json")
MIN_SIDE, MAX_SIDE = 64, 1600


class Settings:
    roots: list[Path] = []
    cache: Path = R.DEFAULT_CACHE
    embedder: str = "clip"
    clip_model: Optional[str] = None


settings = Settings()
_lock = threading.Lock()  # 추천은 CPU를 많이 써서 한 번에 하나씩 처리합니다

app = FastAPI(title="J-1 모델 서버", version="1.0",
              description="사진 읽기, 썸네일, 추천. 백엔드(Spring)가 같은 PC에서 호출합니다.")


# ---------------------------------------------------------------------------
# 요청·응답 모델
# ---------------------------------------------------------------------------
class ScanRequest(BaseModel):
    folder: str = Field(..., description="앨범 폴더의 절대 경로 (--root 안)")


class Photo(BaseModel):
    photo_id: str = Field(..., description="사진 ID. /scan은 상대 경로를 그대로 씁니다")
    relpath: str = Field(..., description="앨범 루트 기준 상대 경로 (구분자 /)")
    path: str = Field(..., description="원본 절대 경로")
    taken_at: Optional[str] = Field(None, description="EXIF 촬영 시각 (ISO 8601), 없으면 null")


class Failed(BaseModel):
    relpath: str
    reason: str


class ScanResponse(BaseModel):
    photos: list[Photo]
    video_count: int
    failed: list[Failed]


class RecommendRequest(BaseModel):
    folder: Optional[str] = Field(None, description="앨범 폴더. 주면 서버가 스캔합니다 (photos와 둘 중 하나)")
    photos: Optional[list[Photo]] = Field(None, description="/scan 결과의 photos (folder와 둘 중 하나)")
    k: Optional[int] = Field(None, ge=1, description="초안 장수. 생략하면 min(10, 읽을 수 있는 사진 수)")


class Cluster(BaseModel):
    cluster_id: str
    photo_ids: list[str] = Field(..., description="묶음 안 순위순. 첫 번째가 대표 컷")
    representative_id: str


class RecommendResponse(BaseModel):
    clusters: list[Cluster] = Field(..., description="모든 사진이 정확히 하나의 묶음에 들어갑니다")
    draft_ids: list[str] = Field(..., description="초안 k장, 촬영순 (시각 미상은 끝)")
    rule_version: str


# ---------------------------------------------------------------------------
# 경로 검사
# ---------------------------------------------------------------------------
def checked(path: str, *, folder: bool = False) -> Path:
    """--root 안의 실제 경로만 허용합니다."""
    p = Path(path)
    try:
        p = p.resolve(strict=True)
    except (OSError, RuntimeError):
        raise HTTPException(404, f"{'폴더' if folder else '파일'}를 찾을 수 없습니다: {path}")
    if settings.roots and not any(p == r or r in p.parents for r in settings.roots):
        raise HTTPException(403, "허용된 폴더(--root) 밖의 경로입니다.")
    if folder and not p.is_dir():
        raise HTTPException(400, f"폴더가 아닙니다: {path}")
    if not folder and (not p.is_file() or p.suffix.lower() not in J.PHOTO_EXTS):
        raise HTTPException(400, f"사진 파일이 아닙니다: {path}")
    return p


def scan(folder: str) -> ScanResponse:
    root = checked(folder, folder=True)
    photos, videos, failed = R.photos_from_folder(root)
    return ScanResponse(photos=[Photo(**p) for p in photos], video_count=videos,
                        failed=[Failed(relpath=str(r), reason=str(e)) for r, e in failed])


# ---------------------------------------------------------------------------
# 엔드포인트
# ---------------------------------------------------------------------------
@app.get("/health")
def health():
    """서버와 모델 상태. 백엔드가 시작할 때 한 번 부르면 됩니다."""
    loaded = any(k[0] == settings.embedder for k in R._EMBEDDERS)
    return {"status": "ok", "model_loaded": loaded, "embedder": settings.embedder,
            "rule_version": R.rule_version(R.load_params(PARAMS_FILE), _embedder_name()),
            "photo_exts": sorted(J.PHOTO_EXTS), "roots": [str(r) for r in settings.roots]}


@app.post("/scan", response_model=ScanResponse)
def post_scan(req: ScanRequest):
    """폴더 안 사진 목록. 하위 폴더도 읽고, 숨김 파일은 뺍니다. 동영상은 개수만 셉니다."""
    return scan(req.folder)


@app.get("/thumb", responses={200: {"content": {"image/jpeg": {}}}})
def get_thumb(path: str = Query(..., description="사진 절대 경로 (/scan의 path)"),
              size: int = Query(512, description="긴 변 픽셀. 목록 512, 큰 미리보기 1600")):
    """정방향 컬러 JPEG. HEIC도 JPEG로 바꿔 줍니다. 작은 사진은 키우지 않습니다."""
    p = checked(path)
    try:
        data = J.jpeg_bytes(p, max(MIN_SIDE, min(MAX_SIDE, size)))
    except Exception as e:  # 손상된 파일 등
        raise HTTPException(422, f"사진을 읽을 수 없습니다: {e}")
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})


@app.post("/recommend", response_model=RecommendResponse)
def post_recommend(req: RecommendRequest):
    """추천. folder 또는 photos 중 하나를 줍니다. 처음 보는 사진은 특징을 계산하고 캐시합니다
    (300장 기준 JPEG 약 30초, HEIC 약 2분, 캐시가 있으면 몇 초)."""
    if (req.folder is None) == (req.photos is None):
        raise HTTPException(400, "folder와 photos 중 하나만 주세요.")
    if req.folder is not None:
        photos = [p.model_dump() for p in scan(req.folder).photos]
    else:
        photos = []
        for p in req.photos:
            checked(p.path)
            photos.append(p.model_dump())
        if len({p["photo_id"] for p in photos}) != len(photos):
            raise HTTPException(400, "photo_id가 중복됩니다.")
    if not photos:
        raise HTTPException(400, "사진이 없습니다.")
    with _lock:
        try:
            out = R.recommend(photos, req.k, embedder=settings.embedder, clip_model=settings.clip_model,
                              cache_dir=settings.cache, params=str(PARAMS_FILE))
        except ValueError as e:
            raise HTTPException(400, str(e))
    return out


def _embedder_name():
    if settings.embedder == "clip":
        return Path(settings.clip_model).stem if settings.clip_model else "clip_vision_model_quantized"
    return settings.embedder


# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description="J-1 모델 서버")
    ap.add_argument("--host", default="127.0.0.1", help="기본 127.0.0.1 (같은 PC의 백엔드만 접근)")
    ap.add_argument("--port", type=int, default=8001)
    ap.add_argument("--root", action="append", default=[],
                    help="사진을 읽어도 되는 폴더 (여러 번 줄 수 있음). 주지 않으면 모든 경로를 허용합니다")
    ap.add_argument("--cache", default=str(R.DEFAULT_CACHE), help="특징 캐시 폴더 (사진 폴더 밖)")
    ap.add_argument("--embedder", choices=["clip", "tiny"], default="clip", help="tiny는 테스트용")
    ap.add_argument("--clip-model", help="CLIP .onnx 경로 (오프라인 실행)")
    args = ap.parse_args(argv)

    settings.roots = [Path(r).resolve() for r in args.root]
    settings.cache = Path(args.cache)
    settings.embedder = args.embedder
    settings.clip_model = args.clip_model
    if not settings.roots:
        print("경고: --root가 없어 모든 경로의 사진을 읽을 수 있습니다. 공개 배포에서는 반드시 --root를 주세요.")
    if args.host not in ("127.0.0.1", "localhost"):
        print(f"경고: {args.host}에 열립니다. 이 서버는 백엔드만 부르도록 바깥에 공개하지 마세요.")
    print("모델을 올리는 중...")
    R.get_embedder(settings.embedder, settings.clip_model)
    print(f"준비 완료 · rule_version {health()['rule_version']} · http://{args.host}:{args.port}/docs")

    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    sys.exit(main())
