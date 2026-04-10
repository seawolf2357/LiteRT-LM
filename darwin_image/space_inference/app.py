"""Darwin Image Gen — HuggingFace Space main entry point.

Gradio UI for the full AETHER pipeline:
- Generate tab: Full pipeline (enhance → generate → judge → loop → Korean inpaint)
- Judge Only tab: Upload an image + prompt, get VLM scores and critique
- Korean Inpaint tab: Manual Korean text insertion into an uploaded image

Runs on A100-large (40GB). Both Z-Image (~12GB) and Darwin-4B-David (~16GB)
are loaded lazily on first use.
"""

import json
import os
import sys
import time
import traceback
from pathlib import Path

import gradio as gr
import torch
from PIL import Image

# Make pipeline importable whether running locally or inside the Space
HERE = Path(__file__).parent.resolve()
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from pipeline import (  # noqa: E402
    AetherConfig,
    DarwinJudge,
    DarwinZImagePipeline,
    JudgeConfig,
    PipelineConfig,
    detect_korean_in_prompt,
    render_text_with_mask,
    run_aether,
)

# ----------------------------------------------------------------- globals

_pipe = None
_judge = None
_load_error = None


def get_token() -> str:
    return os.environ.get("HF_TOKEN", "")


def _lazy_load():
    """Load Z-Image + Darwin-4B-David VLM on first inference call."""
    global _pipe, _judge, _load_error

    if _pipe is not None and _judge is not None:
        return True

    try:
        token = get_token()
        if not token:
            _load_error = "HF_TOKEN secret not set. Cannot load private Darwin-4B-David model."
            return False

        print("[app] Loading DarwinZImagePipeline (Z-Image Turbo + LoRAs fused)...")
        pipe_cfg = PipelineConfig(
            base_model="FINAL-Bench/Darwin-Image-v1",
            fallback_base_model="Tongyi-MAI/Z-Image-Turbo",
            font_path=str(HERE / "assets" / "NotoSansKR-Bold.ttf"),
        )
        _pipe = DarwinZImagePipeline(
            config=pipe_cfg,
            device="cuda",
            dtype=torch.bfloat16,
            token=token,
        )
        # Trigger eager load of the t2i pipeline
        _pipe._load_t2i()
        print("[app] Z-Image loaded.")

        print("[app] Loading Darwin-4B-David VLM judge from unified repo (subfolder='vlm_judge')...")
        judge_cfg = JudgeConfig(
            model_id="FINAL-Bench/Darwin-Image-v1",
            subfolder="vlm_judge",
            fallback_model_id="FINAL-Bench/Darwin-4B-David",
            dtype="bfloat16",
            device="cuda",
        )
        _judge = DarwinJudge(config=judge_cfg, token=token)
        _judge.load()
        print("[app] Darwin-4B-David loaded.")

        if torch.cuda.is_available():
            mem_gb = torch.cuda.memory_allocated() / (1024 ** 3)
            print(f"[app] GPU memory after load: {mem_gb:.2f} GB")

        return True
    except Exception as exc:
        _load_error = f"{type(exc).__name__}: {exc}\n\n{traceback.format_exc()}"
        print(f"[app] LOAD FAILED: {_load_error}")
        return False


# ---------------------------------------------------------------- handlers

def generate_handler(
    prompt: str,
    negative_prompt: str,
    seed: int,
    num_steps: int,
    guidance: float,
    height: int,
    width: int,
    max_iter: int,
    threshold: float,
    enable_vlm_enhance: bool,
    enable_vlm_judge: bool,
    enable_mti: bool,
    korean_override: str,
):
    if not _lazy_load():
        return None, None, f"Model load failed:\n{_load_error}", {}

    if not prompt or not prompt.strip():
        return None, None, "Please enter a prompt.", {}

    try:
        cfg = AetherConfig(
            max_iter=int(max_iter),
            threshold=float(threshold),
            enable_mti=bool(enable_mti),
            enable_vlm_enhance=bool(enable_vlm_enhance),
            enable_vlm_judge=bool(enable_vlm_judge),
        )

        # Allow manual Korean override
        korean_texts_override = None
        if korean_override and korean_override.strip():
            korean_texts_override = [
                {"text": line.strip(), "position": "auto"}
                for line in korean_override.strip().split("\n")
                if line.strip()
            ]

        start = time.time()
        result = run_aether(
            user_prompt=prompt,
            pipe=_pipe,
            judge=_judge if (enable_vlm_enhance or enable_vlm_judge) else None,
            config=cfg,
            seed=int(seed) if seed >= 0 else int(time.time()) & 0xFFFFFFFF,
            negative_prompt=negative_prompt or None,
            num_inference_steps=int(num_steps),
            guidance_scale=float(guidance),
            height=int(height),
            width=int(width),
        )
        elapsed = time.time() - start

        # Build gallery of intermediate iterations
        gallery = []
        for it in result.iterations:
            caption = f"iter {it['iter']+1} — overall {it['scores'].get('overall', '?')}"
            gallery.append((it["image"], caption))

        # Summary JSON
        summary = {
            "best_iter": result.best_iter + 1,
            "total_iterations": len(result.iterations),
            "time_sec": round(elapsed, 2),
            "korean_texts": result.korean_texts,
            "iterations": [
                {
                    "iter": it["iter"] + 1,
                    "scores": it["scores"],
                    "prompt": it["prompt"][:200],
                    "seed": it["seed"],
                }
                for it in result.iterations
            ],
        }

        status = (
            f"✓ Generated in {elapsed:.1f}s. "
            f"Best iter: {result.best_iter + 1}/{len(result.iterations)}. "
            f"Score: {result.iterations[result.best_iter]['scores'].get('overall', '?')}"
        )
        return result.final_image, gallery, status, summary

    except Exception as exc:
        err = f"{type(exc).__name__}: {exc}\n\n{traceback.format_exc()}"
        print(f"[app] generate failed: {err}")
        return None, None, f"Generation failed:\n{err}", {}


def judge_only_handler(image: Image.Image, prompt: str):
    if not _lazy_load():
        return f"Model load failed:\n{_load_error}", {}

    if image is None:
        return "Please upload an image.", {}
    if not prompt or not prompt.strip():
        return "Please enter the original prompt for this image.", {}

    try:
        scores = _judge.score(image, prompt)
        critique = _judge.critique(image, prompt, prompt, scores.get("issues", []))
        status = (
            f"Overall: {scores.get('overall', '?')}  |  "
            f"Fidelity: {scores.get('fidelity', '?')}  |  "
            f"Composition: {scores.get('composition', '?')}  |  "
            f"Faces/Hands: {scores.get('faces_hands', '?')}  |  "
            f"Technical: {scores.get('technical', '?')}  |  "
            f"Aesthetic: {scores.get('aesthetic', '?')}"
        )
        detail = {
            "scores": scores,
            "refined_prompt_suggestion": critique,
        }
        return status, detail
    except Exception as exc:
        return f"Judge failed: {exc}", {}


def korean_inpaint_handler(image: Image.Image, korean_text: str, position: str):
    if image is None:
        return None, "Please upload an image."
    if not korean_text.strip():
        return image, "No Korean text provided — returning original image."

    try:
        texts = [
            {"text": line.strip(), "position": position}
            for line in korean_text.strip().split("\n")
            if line.strip()
        ]
        font_path = str(HERE / "assets" / "NotoSansKR-Bold.ttf")
        composited, mask = render_text_with_mask(image, texts, font_path=font_path)

        # If pipe is loaded, do edge-blend inpainting; else return composited
        if _lazy_load() and _pipe is not None:
            final = _pipe._inpaint_blend(composited, mask, prompt="natural background", seed=42)
        else:
            final = composited

        return final, f"Rendered {len(texts)} Korean string(s)."
    except Exception as exc:
        return None, f"Inpaint failed: {exc}"


# -------------------------------------------------------------------- UI

TITLE = "# 🌌 Darwin Image Gen — AETHER Metacognitive Image Generation"

DESCRIPTION = """
**Darwin Image** combines **Z-Image Turbo** (6B DiT + 4 fused LoRAs) with
**Darwin-4B-David** (Gemma4 multimodal VLM) in a self-improving loop.

**How it works:**
1. Darwin-4B-David enhances your prompt (Korean → English, adds detail)
2. Z-Image generates the image
3. Darwin-4B-David scores it on 5 dimensions
4. If score < threshold, VLM critiques → prompt refined → regenerate (max 3 iter)
5. Korean text in quotes (e.g. `"봄의 서울"`) is rendered via Noto Sans KR + edge inpainting

Private org Space — requires `HF_TOKEN` secret with access to FINAL-Bench.
"""

EXAMPLES = [
    ["cinematic portrait of a korean woman, golden hour, 85mm f1.4", "", 42, 8, 3.5, 1024, 1024, 3, 8.0, True, True, False, ""],
    ['movie poster featuring cherry blossoms around Namsan Tower "봄의 서울"', "", 42, 8, 3.5, 1024, 1024, 3, 8.0, True, True, False, ""],
    ["vibrant tokyo street at night with neon lights, rain reflections", "", 7, 8, 3.5, 1024, 1024, 2, 7.5, True, True, False, ""],
    ["cute kitten drinking a tiny latte, warm window light, bokeh", "", 123, 8, 3.5, 1024, 1024, 1, 7.0, False, False, False, ""],
]


def build_ui():
    with gr.Blocks(title="Darwin Image Gen") as demo:
        gr.Markdown(TITLE)
        gr.Markdown(DESCRIPTION)

        with gr.Tabs():
            # ======================================================= Generate
            with gr.Tab("Generate"):
                with gr.Row():
                    with gr.Column(scale=2):
                        prompt = gr.Textbox(
                            label="Prompt (Korean or English)",
                            placeholder='e.g. 영화 포스터: "봄의 서울" 벚꽃, 남산타워',
                            lines=3,
                        )
                        negative_prompt = gr.Textbox(
                            label="Negative Prompt",
                            placeholder="(leave empty for default)",
                            lines=2,
                        )
                        korean_override = gr.Textbox(
                            label="Korean Text Override (optional, one per line)",
                            placeholder="봄의 서울\n벚꽃 축제",
                            lines=2,
                        )

                        with gr.Accordion("Generation Settings", open=False):
                            with gr.Row():
                                seed = gr.Number(label="Seed (-1 for random)", value=42, precision=0)
                                num_steps = gr.Slider(4, 16, value=8, step=1, label="Steps")
                                guidance = gr.Slider(1.0, 7.0, value=3.5, step=0.5, label="Guidance")
                            with gr.Row():
                                height = gr.Slider(512, 1536, value=1024, step=64, label="Height")
                                width = gr.Slider(512, 1536, value=1024, step=64, label="Width")

                        with gr.Accordion("AETHER Metacognitive Loop", open=True):
                            with gr.Row():
                                max_iter = gr.Slider(1, 4, value=3, step=1, label="Max Iterations")
                                threshold = gr.Slider(5.0, 9.5, value=8.0, step=0.5, label="Quality Threshold")
                            with gr.Row():
                                enable_vlm_enhance = gr.Checkbox(label="VLM Prompt Enhance", value=True)
                                enable_vlm_judge = gr.Checkbox(label="VLM Quality Judge", value=True)
                                enable_mti = gr.Checkbox(label="MTI (experimental)", value=False)

                        generate_btn = gr.Button("🌌 Generate", variant="primary", size="lg")

                    with gr.Column(scale=3):
                        final_image = gr.Image(label="Final Image", type="pil", height=512)
                        status = gr.Markdown("")
                        gallery = gr.Gallery(
                            label="AETHER Iterations",
                            columns=4,
                            height="auto",
                            object_fit="contain",
                        )
                        summary_json = gr.JSON(label="Run Details")

                generate_btn.click(
                    fn=generate_handler,
                    inputs=[
                        prompt, negative_prompt, seed, num_steps, guidance,
                        height, width, max_iter, threshold,
                        enable_vlm_enhance, enable_vlm_judge, enable_mti,
                        korean_override,
                    ],
                    outputs=[final_image, gallery, status, summary_json],
                )

                gr.Examples(
                    examples=EXAMPLES,
                    inputs=[
                        prompt, negative_prompt, seed, num_steps, guidance,
                        height, width, max_iter, threshold,
                        enable_vlm_enhance, enable_vlm_judge, enable_mti,
                        korean_override,
                    ],
                )

            # ===================================================== Judge Only
            with gr.Tab("Judge Only"):
                gr.Markdown("Upload any image and get Darwin-4B-David's critique.")
                with gr.Row():
                    with gr.Column():
                        judge_image = gr.Image(label="Image", type="pil")
                        judge_prompt = gr.Textbox(label="Original Prompt", lines=2)
                        judge_btn = gr.Button("Judge", variant="primary")
                    with gr.Column():
                        judge_status = gr.Markdown("")
                        judge_json = gr.JSON(label="Critique")

                judge_btn.click(
                    fn=judge_only_handler,
                    inputs=[judge_image, judge_prompt],
                    outputs=[judge_status, judge_json],
                )

            # ================================================== Korean Inpaint
            with gr.Tab("Korean Inpaint"):
                gr.Markdown("Manually add Korean text to an existing image.")
                with gr.Row():
                    with gr.Column():
                        ki_image = gr.Image(label="Background Image", type="pil")
                        ki_text = gr.Textbox(label="Korean Text (one per line)", lines=3)
                        ki_position = gr.Radio(
                            ["auto", "top", "center", "bottom"],
                            value="center",
                            label="Position",
                        )
                        ki_btn = gr.Button("Render", variant="primary")
                    with gr.Column():
                        ki_output = gr.Image(label="Result", type="pil")
                        ki_status = gr.Markdown("")

                ki_btn.click(
                    fn=korean_inpaint_handler,
                    inputs=[ki_image, ki_text, ki_position],
                    outputs=[ki_output, ki_status],
                )

        gr.Markdown("---")
        gr.Markdown(
            "**Darwin Image v1.0** — VIDRAFT / 지니젠AI / FINAL-Bench · "
            "Built on Z-Image Turbo + Darwin-4B-David · Apache 2.0"
        )

    return demo


if __name__ == "__main__":
    demo = build_ui()
    demo.queue(max_size=8).launch(
        server_name="0.0.0.0",
        server_port=7860,
        theme=gr.themes.Soft(),
    )
