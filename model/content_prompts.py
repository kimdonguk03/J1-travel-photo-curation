#!/usr/bin/env python3
"""내용 점수에 쓰는 문장과, 그 문장의 CLIP 글 벡터를 만드는 스크립트.

  py content_prompts.py        # content_prompts.npz를 다시 만듭니다 (문장을 바꿨을 때만)

앱 실행 때는 저장된 content_prompts.npz만 읽으므로 CLIP 글 모델이 필요 없습니다.
다시 만들 때만 추가 설치가 필요합니다:  py -m pip install tokenizers
"""
from pathlib import Path

import numpy as np

REPO = "Xenova/clip-vit-base-patch32"  # 이미지 인코더와 같은 CLIP (같은 벡터 공간)
OUT = Path(__file__).with_name("content_prompts.npz")

# 여행 사진 일반에 대한 문장. +1은 보여줄 만한 내용, -1은 빼고 싶은 내용입니다.
# 특정 앨범에 맞춘 문장은 넣지 않고, 가중치는 학습하지 않고 모두 같게 둡니다.
PROMPTS = [
    ("group", "a photo of friends posing together", +1),
    ("portrait", "a portrait photo of a smiling person", +1),
    ("selfie", "a selfie", +1),
    ("landmark", "a famous landmark or tourist attraction", +1),
    ("scenery", "a beautiful scenic landscape", +1),
    ("night", "a beautiful night view with lights", +1),
    ("food", "delicious food on a table", +1),
    ("cafe", "a cozy cafe interior", +1),
    ("aesthetic", "a beautiful, well-composed photo", +1),
    ("road", "a photo of an empty road or parking lot", -1),
    ("ground", "a photo of the ground or floor", -1),
    ("document", "a photo of a document, ticket or card", -1),
    ("screenshot", "a screenshot of a phone screen", -1),
    ("blurry", "a blurry photo", -1),
    ("boring", "a boring, ordinary snapshot", -1),
]


def encode(texts):
    import onnxruntime as ort
    from huggingface_hub import hf_hub_download
    from tokenizers import Tokenizer

    tok = Tokenizer.from_file(hf_hub_download(REPO, "tokenizer.json"))
    sess = ort.InferenceSession(hf_hub_download(REPO, "onnx/text_model_quantized.onnx"),
                                providers=["CPUExecutionProvider"])
    vecs = []
    for t in texts:  # 패딩 없이 한 문장씩
        ids = np.array([tok.encode(t).ids], dtype=np.int64)
        v = sess.run(["text_embeds"], {"input_ids": ids})[0][0]
        vecs.append(v / np.linalg.norm(v))
    return np.stack(vecs).astype(np.float32)


if __name__ == "__main__":
    names = [p[0] for p in PROMPTS]
    vecs = encode([p[1] for p in PROMPTS])
    np.savez(OUT, names=np.array(names), texts=np.array([p[1] for p in PROMPTS]),
             signs=np.array([p[2] for p in PROMPTS], dtype=np.int8), vecs=vecs)
    print(f"{OUT.name}: 문장 {len(names)}개, 벡터 {vecs.shape}")
