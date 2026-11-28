"""모델 서버 점검: py tests/test_server.py (fastapi, httpx 필요). tiny 임베더로 빠르게 돕니다."""
import sys
import tempfile
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fastapi.testclient import TestClient  # noqa: E402

import server as S  # noqa: E402


def main():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d) / "albums"
        album = root / "trip"
        album.mkdir(parents=True)
        for i in range(12):
            Image.new("RGB", (64, 48), (20 * i, 100, 200 - 10 * i)).save(album / f"IMG_{i:04d}.jpg")
        (album / "clip.mp4").write_bytes(b"")
        S.settings.roots = [root.resolve()]
        S.settings.cache = Path(d) / "cache"
        S.settings.embedder = "tiny"
        c = TestClient(S.app)

        assert c.get("/health").json()["status"] == "ok"
        scan = c.post("/scan", json={"folder": str(album)}).json()
        assert len(scan["photos"]) == 12 and scan["video_count"] == 1
        r = c.get("/thumb", params={"path": scan["photos"][0]["path"], "size": 32})
        assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
        assert c.get("/thumb", params={"path": str(Path(d) / "elsewhere.jpg")}).status_code in (403, 404)
        assert c.post("/scan", json={"folder": d}).status_code == 403  # root 밖
        rec = c.post("/recommend", json={"folder": str(album), "k": 5}).json()
        assert len(rec["draft_ids"]) == 5 and len({p for cl in rec["clusters"] for p in cl["photo_ids"]}) == 12
        rec2 = c.post("/recommend", json={"photos": scan["photos"], "k": 5}).json()
        assert rec2["draft_ids"] == rec["draft_ids"]
        assert c.post("/recommend", json={"photos": scan["photos"][:3], "k": 5}).status_code == 400
        assert c.post("/recommend", json={}).status_code == 400
    print("모델 서버 점검 통과")


if __name__ == "__main__":
    main()
