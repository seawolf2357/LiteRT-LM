---
title: Darwin Image Merger
emoji: 🧬
colorFrom: purple
colorTo: pink
sdk: gradio
sdk_version: 6.11.0
app_file: app.py
pinned: false
hardware: a100-large
python_version: "3.11"
models:
  - Tongyi-MAI/Z-Image-Turbo
  - Shakker-Labs/AWPortrait-Z
  - qqnyanddld/nsfw-z-image-lora
  - renderartist/Technically-Color-Z-Image-Turbo
  - wcde/Z-Image-Turbo-DeJPEG-Lora
tags:
  - lora-merge
  - darwin-image
suggested_storage: medium
short_description: One-shot LoRA merger for Darwin-Image-v1
---

# Darwin Image Merger

**One-shot Space** for fusing the Darwin-Image-v1 LoRA stack into
Z-Image Turbo and uploading the merged pipeline to
`FINAL-Bench/Darwin-Image-v1`.

## Usage

1. Set `HF_TOKEN` secret (write access to FINAL-Bench)
2. Open the Space
3. Click "Run LoRA Merge"
4. Wait ~10 minutes for: download → fuse → upload
5. Merged model will be available at `FINAL-Bench/Darwin-Image-v1`

## What it does

Loads Z-Image Turbo in bf16, then sequentially fuses 4 LoRAs:

| LoRA | Scale | Purpose |
|---|---|---|
| Shakker-Labs/AWPortrait-Z | 0.7 | Portrait quality |
| qqnyanddld/nsfw-z-image-lora | 0.5 | Uncensored generation |
| renderartist/Technically-Color-Z-Image-Turbo | 0.4 | Enhanced color |
| wcde/Z-Image-Turbo-DeJPEG-Lora | 0.3 | Artifact removal |

All LoRAs share Z-Image's DiT architecture, so direct `fuse_lora()`
works with no information loss.

After fusing, uploads the full pipeline (transformer + vae + text_encoder
+ scheduler + tokenizer) to the target model repo.

## License

Apache 2.0.
