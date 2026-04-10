---
license: apache-2.0
language:
  - en
  - ko
library_name: diffusers
pipeline_tag: text-to-image
tags:
  - darwin-image
  - aether-metacognitive
  - z-image
  - lora-merge
  - korean-text
  - vlm-judge
base_model:
  - Tongyi-MAI/Z-Image-Turbo
  - Shakker-Labs/AWPortrait-Z
  - qqnyanddld/nsfw-z-image-lora
  - renderartist/Technically-Color-Z-Image-Turbo
  - wcde/Z-Image-Turbo-DeJPEG-Lora
inference: false
---

# Darwin-Image-v1 — Unified DiT + VLM

**Darwin-Image-v1** is a **physically unified** model repository that
combines two models into a single HF repo:

1. **Z-Image Turbo** (6B DiT) at the repo root, with 4 LoRAs fused into
   the transformer weights (no runtime adapter loading).
2. **Darwin-4B-David** (Gemma4 multimodal VLM, ~16GB bf16) inside the
   `vlm_judge/` subfolder.

Both models coexist as real safetensors files in this single repo, so a
single `from_pretrained()` call downloads everything needed for the
AETHER metacognitive image generation pipeline.

## Repo Layout

```
FINAL-Bench/Darwin-Image-v1/
├── model_index.json            # Z-Image pipeline manifest
├── scheduler/                  # Z-Image components
├── text_encoder/               #   (Qwen3)
├── tokenizer/
├── transformer/                # ★ DiT with 4 LoRAs fused
├── vae/
├── vlm_judge/                  # ★★ Darwin-4B-David
│   ├── config.json             #    Gemma4ForConditionalGeneration
│   ├── model.safetensors       #    ~16GB bfloat16
│   ├── tokenizer.json
│   ├── chat_template.jinja
│   └── generation_config.json
├── lora_manifest.yaml
├── aether_config.json
├── fuse_report.json
└── README.md  (this file)
```

## LoRA Stack Fused Into DiT

```
Z-Image Turbo (6B DiT, bf16)
    └── + Shakker-Labs/AWPortrait-Z (scale 0.7) → portrait quality
    └── + qqnyanddld/nsfw-z-image-lora (scale 0.5) → uncensored
    └── + renderartist/Technically-Color-Z-Image-Turbo (scale 0.4) → color
    └── + wcde/Z-Image-Turbo-DeJPEG-Lora (scale 0.3) → artifact removal
```

All LoRAs share Z-Image's DiT architecture (dim=3840), so direct
`fuse_lora()` works without SVD projection or information loss.

## Usage

### DiT only (text-to-image)
```python
from diffusers import DiffusionPipeline
import torch

pipe = DiffusionPipeline.from_pretrained(
    "FINAL-Bench/Darwin-Image-v1",
    torch_dtype=torch.bfloat16,
    token="hf_...",
).to("cuda")

image = pipe(
    prompt="cinematic portrait of a korean woman, golden hour, 85mm f1.4",
    num_inference_steps=8,
    guidance_scale=3.5,
    height=1024,
    width=1024,
).images[0]
```

### Load the bundled VLM judge (from subfolder)
```python
from transformers import AutoModel, AutoProcessor
import torch

judge = AutoModel.from_pretrained(
    "FINAL-Bench/Darwin-Image-v1",
    subfolder="vlm_judge",
    torch_dtype=torch.bfloat16,
    device_map="cuda",
    token="hf_...",
)
processor = AutoProcessor.from_pretrained(
    "FINAL-Bench/Darwin-Image-v1",
    subfolder="vlm_judge",
    token="hf_...",
)
```

## AETHER Integration

For the full metacognitive pipeline (VLM prompt enhancement + quality
judging + Korean text inpainting), use the Darwin Image pipeline code:

```python
from darwin_image.pipeline import DarwinZImagePipeline, DarwinJudge, run_aether, AetherConfig

pipe = DarwinZImagePipeline(base_model="FINAL-Bench/Darwin-Image-v1")
judge = DarwinJudge()  # loads Darwin-4B-David

result = run_aether(
    user_prompt='영화 포스터: "봄의 서울" 벚꽃 남산타워',
    pipe=pipe,
    judge=judge,
    config=AetherConfig(max_iter=3, threshold=8.0),
    seed=42,
)
result.final_image.save("out.png")
```

## Default AETHER Config

See `aether_config.json` for the default metacognitive loop parameters:
- `max_iter`: 3 (up to 3 retries)
- `threshold`: 8.0 (overall score threshold to exit early)
- `enable_vlm_enhance`: true (VLM rewrites prompts)
- `enable_vlm_judge`: true (VLM scores each iteration)
- `enable_mti`: false (experimental, off by default on 8-step distilled models)

## License

Apache 2.0 — inherits from Z-Image Turbo and all LoRA base models.

## Citation

If you use Darwin-Image-v1, please cite:

```bibtex
@misc{darwin-image-2026,
  title={Darwin Image: VLM-Guided Metacognitive Image Generation with Korean Text Integration},
  author={VIDRAFT and 지니젠AI and FINAL-Bench},
  year={2026},
  howpublished={\url{https://huggingface.co/FINAL-Bench/Darwin-Image-v1}},
}
```

## Safety Notice

This model includes an uncensored LoRA component. Use responsibly.
The AETHER pipeline Space (`darwin-image-gen`) is deployed as **private**
(FINAL-Bench org only) for this reason.
