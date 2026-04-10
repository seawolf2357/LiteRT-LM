"""Darwin Image Merger — one-shot LoRA merger Space.

Click "Run LoRA Merge" to:
1. Download Z-Image Turbo (~12GB)
2. Sequentially fuse 4 LoRAs
3. Save merged pipeline locally
4. Upload to FINAL-Bench/Darwin-Image-v1

Runs on A100-large (40GB). Total time: ~10 minutes.
"""

import json
import os
import shutil
import sys
import time
import traceback
from pathlib import Path

import gradio as gr
import torch
import yaml

HERE = Path(__file__).parent.resolve()
OUTPUT_DIR = HERE / "Darwin-Image-v1-merged"
MANIFEST_PATH = HERE / "lora_manifest.yaml"
TARGET_REPO = "FINAL-Bench/Darwin-Image-v1"


# The manifest is shipped alongside the app file
DEFAULT_MANIFEST = {
    "base_model": "Tongyi-MAI/Z-Image-Turbo",
    "output_repo": TARGET_REPO,
    "loras": [
        {"repo_id": "Shakker-Labs/AWPortrait-Z", "adapter_name": "portrait", "scale": 0.7},
        {"repo_id": "qqnyanddld/nsfw-z-image-lora", "adapter_name": "nsfw", "scale": 0.5},
        {"repo_id": "renderartist/Technically-Color-Z-Image-Turbo", "adapter_name": "color", "scale": 0.4},
        {"repo_id": "wcde/Z-Image-Turbo-DeJPEG-Lora", "adapter_name": "dejpeg", "scale": 0.3},
    ],
}


def load_manifest():
    if MANIFEST_PATH.exists():
        with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    return DEFAULT_MANIFEST


def run_merge_and_upload(
    private: bool,
    progress: gr.Progress = gr.Progress(),
):
    """Main merge pipeline. Yields log lines to the UI."""
    token = os.environ.get("HF_TOKEN")
    if not token:
        yield "❌ HF_TOKEN secret not set. Go to Space Settings → Variables and secrets.", ""
        return

    logs = []

    def log(msg):
        logs.append(msg)
        print(msg)
        return "\n".join(logs)

    try:
        from diffusers import DiffusionPipeline
        from huggingface_hub import HfApi, upload_folder

        manifest = load_manifest()
        base_model = manifest["base_model"]

        yield log(f"🧬 Darwin Image Merger"), ""
        yield log(f"Base model: {base_model}"), ""
        yield log(f"Target repo: {TARGET_REPO}"), ""
        yield log(f"LoRAs to fuse: {len(manifest['loras'])}"), ""
        yield log(""), ""

        # Step 1: load base
        progress(0.05, desc="Downloading Z-Image Turbo...")
        yield log(f"[1/3] Loading {base_model}..."), ""
        start = time.time()
        pipe = DiffusionPipeline.from_pretrained(
            base_model,
            torch_dtype=torch.bfloat16,
            token=token,
        ).to("cuda")
        yield log(f"  ✓ Loaded in {time.time() - start:.1f}s"), ""

        # Step 2: fuse LoRAs
        yield log(""), ""
        yield log(f"[2/3] Fusing {len(manifest['loras'])} LoRAs..."), ""

        fuse_report = {"base_model": base_model, "loras_applied": [], "loras_skipped": []}

        for i, entry in enumerate(manifest["loras"]):
            repo_id = entry["repo_id"]
            scale = float(entry["scale"])
            adapter_name = entry.get("adapter_name", repo_id.split("/")[-1])
            progress_val = 0.2 + (0.5 * (i + 1) / len(manifest["loras"]))
            progress(progress_val, desc=f"Fusing {adapter_name}...")

            yield log(f"  → {adapter_name} ({repo_id}) scale={scale}"), ""

            try:
                try:
                    pipe.load_lora_weights(repo_id, adapter_name=adapter_name, token=token)
                except TypeError:
                    pipe.load_lora_weights(repo_id, token=token)
                pipe.fuse_lora(lora_scale=scale)
                pipe.unload_lora_weights()
                fuse_report["loras_applied"].append({
                    "repo_id": repo_id,
                    "scale": scale,
                })
                yield log(f"    ✓ Fused at scale {scale}"), ""
            except Exception as exc:
                yield log(f"    ⚠ Failed: {exc}"), ""
                fuse_report["loras_skipped"].append({"repo_id": repo_id, "reason": str(exc)})
                try:
                    pipe.unload_lora_weights()
                except Exception:
                    pass

        yield log(""), ""
        yield log(f"  Applied: {len(fuse_report['loras_applied'])}, "
                  f"Skipped: {len(fuse_report['loras_skipped'])}"), ""

        # Step 3: save + upload
        yield log(""), ""
        progress(0.75, desc="Saving merged pipeline to disk...")
        yield log(f"[3/3] Saving to {OUTPUT_DIR}..."), ""
        if OUTPUT_DIR.exists():
            shutil.rmtree(OUTPUT_DIR)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        pipe.save_pretrained(str(OUTPUT_DIR), safe_serialization=True)

        # Free GPU before upload
        del pipe
        torch.cuda.empty_cache()

        # Write fuse report
        report_path = OUTPUT_DIR / "fuse_report.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(fuse_report, f, indent=2, ensure_ascii=False)

        # Copy the manifest too
        if MANIFEST_PATH.exists():
            shutil.copy(MANIFEST_PATH, OUTPUT_DIR / "lora_manifest.yaml")

        yield log(f"  ✓ Saved. Size: {_dir_size_gb(OUTPUT_DIR):.2f} GB"), ""

        # Upload
        progress(0.85, desc=f"Uploading to {TARGET_REPO}...")
        yield log(""), ""
        yield log(f"Uploading to {TARGET_REPO} (private={private})..."), ""

        api = HfApi(token=token)
        api.create_repo(
            repo_id=TARGET_REPO,
            repo_type="model",
            private=private,
            exist_ok=True,
        )
        upload_folder(
            folder_path=str(OUTPUT_DIR),
            repo_id=TARGET_REPO,
            repo_type="model",
            commit_message="Upload Darwin-Image-v1 fused pipeline (LoRA merge)",
            token=token,
            ignore_patterns=["*.tmp", "__pycache__", "*.pyc"],
        )

        progress(1.0, desc="Done!")
        yield log(""), ""
        yield log(f"✓ Upload complete!"), f"https://huggingface.co/{TARGET_REPO}"
        yield log(f"  View: https://huggingface.co/{TARGET_REPO}"), f"https://huggingface.co/{TARGET_REPO}"

    except Exception as exc:
        err = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
        yield log(f"❌ ERROR:\n{err}"), ""


def _dir_size_gb(path: Path) -> float:
    total = 0
    for p in path.rglob("*"):
        if p.is_file():
            total += p.stat().st_size
    return total / (1024 ** 3)


def build_ui():
    with gr.Blocks(title="Darwin Image Merger", theme=gr.themes.Soft()) as demo:
        gr.Markdown("# 🧬 Darwin Image Merger")
        gr.Markdown("""
One-shot LoRA merger for **Darwin-Image-v1**.

This Space fuses 4 LoRAs into Z-Image Turbo and uploads the result to
`FINAL-Bench/Darwin-Image-v1`. Total time: ~10 minutes on A100.

**Requirements:**
- `HF_TOKEN` secret must be set (write access to FINAL-Bench)
- A100-large hardware (40GB GPU)
""")

        with gr.Row():
            private = gr.Checkbox(label="Upload as private repo", value=True)
        with gr.Row():
            run_btn = gr.Button("🧬 Run LoRA Merge", variant="primary", size="lg")

        with gr.Row():
            logs = gr.Textbox(label="Logs", lines=20, interactive=False)
        with gr.Row():
            result_url = gr.Textbox(label="Result URL", interactive=False)

        run_btn.click(
            fn=run_merge_and_upload,
            inputs=[private],
            outputs=[logs, result_url],
        )

        gr.Markdown("---")
        gr.Markdown("**Darwin Image v1.0** — VIDRAFT / 지니젠AI / FINAL-Bench · Apache 2.0")

    return demo


if __name__ == "__main__":
    demo = build_ui()
    demo.queue(max_size=2).launch(server_name="0.0.0.0", server_port=7860)
