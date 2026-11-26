#!/usr/bin/env python3
"""LAION-Aesthetics V1 선형층(.pth)을 aesthetic_vit_b_32.npz로 변환합니다. PyTorch 없이, pickle을 실행하지 않고 숫자만 읽습니다.

  원본: https://github.com/LAION-AI/aesthetic-predictor (MIT, LICENSE-laion-aesthetic.txt)
  py aesthetic_head.py sa_0_4_vit_b_32_linear.pth

.pth 안의 data.pkl은 {"weight": (1, 512) float32, "bias": (1,) float32}이고, 실제 값은 archive/data/0, archive/data/1에
리틀 엔디언 float32로 들어 있습니다. 입력은 L2 정규화한 CLIP ViT-B/32 이미지 벡터입니다.
"""
import sys
import zipfile
from pathlib import Path

import numpy as np


def convert(pth, out=Path(__file__).with_name("aesthetic_vit_b_32.npz")):
    with zipfile.ZipFile(pth) as z:
        names = z.namelist()
        root = names[0].split("/")[0]
        w = np.frombuffer(z.read(f"{root}/data/0"), "<f4").copy()
        b = np.frombuffer(z.read(f"{root}/data/1"), "<f4").copy()
    if w.shape != (512,) or b.shape != (1,):
        raise ValueError(f"예상과 다른 모양: weight {w.shape}, bias {b.shape}")
    np.savez(out, w=w, b=b)
    print(f"저장: {out} (가중치 노름 {np.linalg.norm(w):.3f}, 절편 {b[0]:.4f})")


if __name__ == "__main__":
    convert(sys.argv[1])
