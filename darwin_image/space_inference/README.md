---
title: Darwin Image Gen
emoji: 🐨
colorFrom: gray
colorTo: green
sdk: gradio
sdk_version: 6.11.0
app_file: app.py
pinned: false
hardware: a100-large
python_version: "3.11"
models:
  - FINAL-Bench/Darwin-Image-v1
tags:
  - darwin-image
  - aether-metacognitive
  - text-to-image
  - vlm-judge
  - korean-text
suggested_storage: small
short_description: Darwin Image — VLM-guided AETHER metacognitive image gen
---

# Darwin Image Gen

**Darwin Image** is a **physically unified** model combining DiT image
generation and multimodal VLM judging into a single HuggingFace repo
(`FINAL-Bench/Darwin-Image-v1`):
- **Z-Image Turbo** (6B DiT, fused with 4 LoRAs) at the repo root
- **Darwin-4B-David** (Gemma4 multimodal, ~16GB) at `subfolder="vlm_judge"`
- **AETHER metacognitive loop** for self-improvement
- **Korean text inpainting** for 100% accurate Hangul rendering

Both models are downloaded in a single `from_pretrained` call:
```python
pipe = DiffusionPipeline.from_pretrained("FINAL-Bench/Darwin-Image-v1")
judge = AutoModel.from_pretrained("FINAL-Bench/Darwin-Image-v1",
                                   subfolder="vlm_judge")
```

## Features

1. **Auto prompt enhancement**: Darwin-4B-David converts Korean/rough prompts into detailed English DiT prompts
2. **AETHER loop**: Up to 3 iterations with VLM critique feedback when quality < 8.0
3. **Korean text rendering**: Extracts quoted Korean strings, renders via Noto Sans KR, blends edges via inpainting
4. **Judge Only mode**: Upload any image and get VLM critique + scores

## Hardware

Runs on A100-large (40GB). Loads both Z-Image Turbo (12GB bf16) and Darwin-4B-David (16GB bf16) simultaneously with ~12GB GPU headroom.

## Secrets

Requires `HF_TOKEN` secret with read access to `FINAL-Bench/Darwin-4B-David` (private model).

## License

Apache 2.0 — inherits from Z-Image Turbo and Darwin-4B-David base models.
