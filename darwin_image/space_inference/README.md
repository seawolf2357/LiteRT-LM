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
  - FINAL-Bench/Darwin-4B-David
  - Tongyi-MAI/Z-Image-Turbo
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

**Darwin Image** is a VLM-guided image generation system that combines:
- **Z-Image Turbo** (6B DiT, fused with 4 LoRAs) for generation
- **Darwin-4B-David** (Gemma4 multimodal) as the quality judge
- **AETHER metacognitive loop** for self-improvement
- **Korean text inpainting** for 100% accurate Hangul rendering

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
