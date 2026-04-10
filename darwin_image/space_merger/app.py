"""Darwin Image Unified Merger — one-shot physical integration Space.

Click "Run Merge" to:
1. Download Z-Image Turbo (~12GB) and fuse 4 LoRAs
2. Download Darwin-4B-David VLM (~16GB) into vlm_judge/ subfolder
3. Upload the unified model (Z-Image + VLM physically co-located) to
   FINAL-Bench/Darwin-Image-v1

Result: a single HF repo containing BOTH the DiT image generator and
the VLM judge as actual safetensors files, loadable via:
    pipe = DiffusionPipeline.from_pretrained("FINAL-Bench/Darwin-Image-v1")
    judge = AutoModel.from_pretrained(
        "FINAL-Bench/Darwin-Image-v1", subfolder="vlm_judge")

Runs on A100-large (40GB). Total time: ~15-20 minutes (~28GB upload).
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


VLM_SOURCE = "FINAL-Bench/Darwin-4B-David"


def run_merge_and_upload(
    private: bool,
    include_vlm: bool,
    progress: gr.Progress = gr.Progress(),
):
    """Unified merge pipeline. Yields (logs, result_url) pairs to the UI.

    Steps:
      1. Load Z-Image Turbo + fuse 4 LoRAs
      2. Save merged pipeline
      3. Download Darwin-4B-David snapshot into vlm_judge/ subfolder
      4. Upload unified folder (Z-Image + VLM) to FINAL-Bench/Darwin-Image-v1
    """
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
        from huggingface_hub import HfApi, snapshot_download, upload_folder

        manifest = load_manifest()
        base_model = manifest["base_model"]

        yield log(f"🧬 Darwin Image Unified Merger"), ""
        yield log(f"Base DiT: {base_model}"), ""
        yield log(f"VLM source: {VLM_SOURCE if include_vlm else '(skipped)'}"), ""
        yield log(f"Target repo: {TARGET_REPO}"), ""
        yield log(f"LoRAs to fuse: {len(manifest['loras'])}"), ""
        yield log(""), ""

        # ------------------------------------------------------------- Step 1
        progress(0.03, desc="Downloading Z-Image Turbo...")
        yield log(f"[1/4] Loading {base_model}..."), ""
        start = time.time()
        pipe = DiffusionPipeline.from_pretrained(
            base_model,
            torch_dtype=torch.bfloat16,
            token=token,
        ).to("cuda")
        yield log(f"  ✓ Loaded in {time.time() - start:.1f}s"), ""

        # ------------------------------------------------------------- Step 2
        yield log(""), ""
        yield log(f"[2/4] Fusing {len(manifest['loras'])} LoRAs..."), ""

        fuse_report = {
            "base_model": base_model,
            "target_repo": TARGET_REPO,
            "loras_applied": [],
            "loras_skipped": [],
            "vlm_bundled": None,
        }

        for i, entry in enumerate(manifest["loras"]):
            repo_id = entry["repo_id"]
            scale = float(entry["scale"])
            adapter_name = entry.get("adapter_name", repo_id.split("/")[-1])
            progress_val = 0.1 + (0.25 * (i + 1) / len(manifest["loras"]))
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

        # ------------------------------------------------------------- Step 3
        yield log(""), ""
        progress(0.4, desc="Saving Z-Image pipeline to disk...")
        yield log(f"[3/4] Saving Z-Image pipeline to {OUTPUT_DIR}..."), ""
        if OUTPUT_DIR.exists():
            shutil.rmtree(OUTPUT_DIR)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        pipe.save_pretrained(str(OUTPUT_DIR), safe_serialization=True)

        # Free GPU before VLM download
        del pipe
        torch.cuda.empty_cache()

        yield log(f"  ✓ Z-Image saved ({_dir_size_gb(OUTPUT_DIR):.2f} GB)"), ""

        # ------------------------------------------------------------- Step 4
        if include_vlm:
            yield log(""), ""
            progress(0.5, desc=f"Downloading VLM {VLM_SOURCE}...")
            yield log(f"[4/4] Bundling VLM {VLM_SOURCE} → vlm_judge/..."), ""
            vlm_dir = OUTPUT_DIR / "vlm_judge"
            vlm_dir.mkdir(parents=True, exist_ok=True)
            try:
                vlm_start = time.time()
                snapshot_download(
                    repo_id=VLM_SOURCE,
                    repo_type="model",
                    local_dir=str(vlm_dir),
                    token=token,
                    ignore_patterns=[
                        "*.png", "*.jpg", "*.jpeg", "*.gif",
                        "README.md", ".gitattributes",
                    ],
                )
                vlm_elapsed = time.time() - vlm_start
                vlm_size = sum(
                    f.stat().st_size for f in vlm_dir.rglob("*") if f.is_file()
                ) / (1024 ** 3)
                fuse_report["vlm_bundled"] = {
                    "source": VLM_SOURCE,
                    "size_gb": round(vlm_size, 2),
                    "download_sec": round(vlm_elapsed, 1),
                }
                yield log(f"  ✓ VLM bundled ({vlm_size:.2f} GB in {vlm_elapsed:.1f}s)"), ""
            except Exception as exc:
                yield log(f"  ⚠ VLM bundling failed: {exc}"), ""
                fuse_report["vlm_bundled"] = {"source": VLM_SOURCE, "error": str(exc)}
        else:
            yield log(""), ""
            yield log(f"[4/4] Skipping VLM bundle (include_vlm=False)"), ""
            fuse_report["vlm_bundled"] = {"skipped": True}

        # Write fuse report
        report_path = OUTPUT_DIR / "fuse_report.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(fuse_report, f, indent=2, ensure_ascii=False)

        # Copy the manifest
        if MANIFEST_PATH.exists():
            shutil.copy(MANIFEST_PATH, OUTPUT_DIR / "lora_manifest.yaml")

        total_gb = _dir_size_gb(OUTPUT_DIR)
        yield log(""), ""
        yield log(f"  Total unified bundle: {total_gb:.2f} GB"), ""

        # ----------------------------------------------------------- Upload
        progress(0.75, desc=f"Uploading to {TARGET_REPO}...")
        yield log(""), ""
        yield log(f"Uploading to {TARGET_REPO} (private={private})..."), ""
        yield log(f"  This can take 5-10 minutes for {total_gb:.1f} GB..."), ""

        api = HfApi(token=token)
        api.create_repo(
            repo_id=TARGET_REPO,
            repo_type="model",
            private=private,
            exist_ok=True,
        )
        upload_start = time.time()
        upload_folder(
            folder_path=str(OUTPUT_DIR),
            repo_id=TARGET_REPO,
            repo_type="model",
            commit_message=f"Upload unified Darwin-Image-v1 (Z-Image fused + VLM bundled, {total_gb:.1f}GB)",
            token=token,
            ignore_patterns=["*.tmp", "__pycache__", "*.pyc"],
        )
        upload_elapsed = time.time() - upload_start

        progress(1.0, desc="Done!")
        yield log(""), ""
        yield log(f"✓ Upload complete in {upload_elapsed:.1f}s!"), f"https://huggingface.co/{TARGET_REPO}"
        yield log(f"  View: https://huggingface.co/{TARGET_REPO}"), f"https://huggingface.co/{TARGET_REPO}"
        yield log(""), f"https://huggingface.co/{TARGET_REPO}"
        yield log(f"Usage:"), f"https://huggingface.co/{TARGET_REPO}"
        yield log(f"  pipe = DiffusionPipeline.from_pretrained('{TARGET_REPO}')"), f"https://huggingface.co/{TARGET_REPO}"
        if include_vlm:
            yield log(f"  judge = AutoModel.from_pretrained('{TARGET_REPO}', subfolder='vlm_judge')"), f"https://huggingface.co/{TARGET_REPO}"

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
    with gr.Blocks(title="Darwin Image Unified Merger", theme=gr.themes.Soft()) as demo:
        gr.Markdown("# 🧬 Darwin Image Unified Merger")
        gr.Markdown(f"""
**One-shot physical integration** of Z-Image Turbo + Darwin-4B-David VLM into a
single unified model repo at `{TARGET_REPO}`.

**What it does:**
1. Downloads Z-Image Turbo and sequentially fuses 4 LoRAs (portrait / nsfw / color / dejpeg)
2. Saves the merged DiT pipeline
3. Downloads Darwin-4B-David VLM (~16GB Gemma4 multimodal) into a `vlm_judge/` subfolder
4. Uploads the unified folder (~28GB total) to `{TARGET_REPO}`

**Result:** a single HF repo containing BOTH the DiT image generator and the VLM judge
as actual safetensors files, loadable via:
```python
pipe = DiffusionPipeline.from_pretrained("{TARGET_REPO}")
judge = AutoModel.from_pretrained("{TARGET_REPO}", subfolder="vlm_judge")
```

**Requirements:**
- `HF_TOKEN` secret set (write access to FINAL-Bench, read access to Darwin-4B-David)
- A100-large hardware (40GB GPU)
- ~60GB disk (download + output + upload staging)

**Total time:** ~15-20 minutes.
""")

        with gr.Row():
            private = gr.Checkbox(label="Upload as private repo", value=True)
            include_vlm = gr.Checkbox(label="Bundle Darwin-4B-David VLM (physical integration)", value=True)
        with gr.Row():
            run_btn = gr.Button("🧬 Run Unified Merge", variant="primary", size="lg")

        with gr.Row():
            logs = gr.Textbox(label="Logs", lines=25, interactive=False)
        with gr.Row():
            result_url = gr.Textbox(label="Result URL", interactive=False)

        run_btn.click(
            fn=run_merge_and_upload,
            inputs=[private, include_vlm],
            outputs=[logs, result_url],
        )

        gr.Markdown("---")
        gr.Markdown("**Darwin Image v1.0** — VIDRAFT / 지니젠AI / FINAL-Bench · Apache 2.0")

    return demo


if __name__ == "__main__":
    demo = build_ui()
    demo.queue(max_size=2).launch(server_name="0.0.0.0", server_port=7860)
