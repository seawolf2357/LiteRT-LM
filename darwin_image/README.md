# Darwin Image — VLM-Guided Metacognitive Image Generation

**Darwin Image** integrates **Z-Image Turbo** (6B DiT text-to-image) with
**Darwin-4B-David** (Gemma4 multimodal VLM) to create a self-improving image
generation pipeline powered by the **AETHER metacognitive loop**.

## Architecture

```
User Prompt (Korean/English)
     ↓
[S1] VLM Prompt Enhancement (Darwin-4B-David)
     ↓
[S2] Image Generation (Z-Image Turbo + 4 LoRAs fused)
     ↓
[S3] VLM Quality Judge (Darwin-4B-David)
     ├── score ≥ 8.0 → pass
     └── score < 8.0 → critique → loop (max 3 iter)
     ↓
[S4] Korean Text Inpainting (Noto Sans KR + Z-Image inpaint)
     ↓
Final Image
```

## Directory Layout

```
darwin_image/
├── pipeline/         # Runtime library (shipped to Space)
│   ├── darwin_pipeline.py    # DarwinZImagePipeline with Korean auto-detect
│   ├── korean_inpaint.py     # 3-stage edge-mask Korean rendering
│   ├── vlm_judge.py          # Darwin-4B-David wrapper (enhance/score/critique)
│   ├── aether.py             # AETHER metacognitive loop
│   ├── mti.py                # Minimal Test-Time Intervention
│   └── config.py             # Dataclass configs
├── merge/            # LoRA fusing scripts (run in merger Space)
│   ├── fuse_loras.py
│   ├── lora_manifest.yaml
│   └── upload_merged.py
├── space_inference/  # → FINAL-Bench/darwin-image-gen (A100-large, private)
├── space_merger/     # → FINAL-Bench/darwin-image-merger (one-shot A100)
├── model_card/       # → FINAL-Bench/Darwin-Image-v1 README
└── scripts/          # HF repo creation + deployment orchestration
```

## HuggingFace Deployment

| Repo | Type | Purpose |
|---|---|---|
| `FINAL-Bench/Darwin-Image-v1` | model | Z-Image Turbo + 4 LoRAs fused (12GB) |
| `FINAL-Bench/darwin-image-merger` | space (A100) | One-shot LoRA merging |
| `FINAL-Bench/darwin-image-gen` | space (A100) | Main inference UI |
| `FINAL-Bench/Darwin-4B-David` | model (private) | VLM judge (existing) |

## AETHER 5 Pillars Mapping

| Pillar | Implementation |
|---|---|
| **Emergence** | Diverse seeds × prompt variations → VLM picks best |
| **Metacognition** | VLM critiques own generations → feedback loop |
| **Self-Evolution** | EvoQuality-style judge calibration (future work) |
| **Multi-Intelligence** | Z-Image + VLM + LoRAs + ControlNet team |
| **Harmony/Tension** | VLM checks generator hallucinations, rejects below threshold |

## License

Apache 2.0 (inherits from Z-Image Turbo and Darwin-4B-David base models).
