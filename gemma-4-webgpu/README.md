# Gemma 4 WebGPU - Deobfuscated Source

Deobfuscated source code from the [Gemma 4 WebGPU](https://huggingface.co/spaces/FINAL-Bench/Gemma-4-WebGPU) Hugging Face Space (originally by [webml-community](https://huggingface.co/spaces/webml-community/Gemma-4-WebGPU)).

## What is this?

A multimodal AI chat application that runs **Gemma 4 (2B)** entirely in the browser using WebGPU. No server required - all inference happens locally on your device.

### Features

- **WebGPU inference** - Runs Gemma 4 2B model (ONNX, q4f16 quantized) directly in browser
- **Webcam / Video input** - Capture and analyze live video frames
- **Audio recording** - Record and transcribe speech
- **Tool calling** - Vision tool for automatic frame capture when user asks about visuals
- **Thinking mode** - Toggle chain-of-thought reasoning display
- **Math rendering** - KaTeX support for LaTeX math in responses
- **Streaming** - Real-time token streaming with animated markdown rendering

### Tech Stack

| Layer | Technology |
|-------|-----------|
| Framework | React 19.2 + Vite |
| Styling | Tailwind CSS v4.2 |
| ML Runtime | [Transformers.js](https://github.com/huggingface/transformers.js) + ONNX Runtime (WebGPU) |
| Model | [onnx-community/gemma-4-E2B-it-ONNX](https://huggingface.co/onnx-community/gemma-4-E2B-it-ONNX) |
| Markdown | [Streamdown](https://www.npmjs.com/package/streamdown) + KaTeX |
| Icons | [Lucide React](https://lucide.dev) |

## Project Structure

```
src/
├── main.jsx                  # Entry point
├── App.jsx                   # Root component (landing → loading → main)
├── index.css                 # Tailwind + custom theme/animations
├── constants.js              # Model ID, system prompt, tools, prompts
├── utils.js                  # Tool parsing, math preprocessing, helpers
├── contexts/
│   ├── ModelContext.jsx       # Model loading, generation, tool calling, transcription
│   └── MediaContext.jsx       # Webcam, video file, audio recording, frame capture
└── components/
    ├── LandingPage.jsx        # Hero page with "Load model" button
    ├── LoadingPage.jsx        # Progress bar during model download
    ├── MainView.jsx           # Video display + source selection
    ├── ChatOverlay.jsx        # Chat UI with input bar and controls
    ├── MessageBubble.jsx      # User/assistant message with markdown
    ├── ScanningOverlay.jsx    # Frame capture animation
    ├── ThinkingToggle.jsx     # Collapsible thinking content
    ├── AudioWaveform.jsx      # Audio amplitude visualization
    └── TypingIndicator.jsx    # Animated typing dots
```

## Development

```bash
npm install
npm run dev
```

Requires a WebGPU-capable browser (Chrome 113+, Edge 113+).

## How it was deobfuscated

The original Hugging Face Space only contains built/bundled files - a single 1.5MB minified JavaScript bundle produced by Vite/Rolldown. The deobfuscation process:

1. Downloaded and beautified the JS bundle (78,439 lines)
2. Identified library vs application code boundaries
3. Mapped all obfuscated variable names to meaningful names
4. Separated ~2,500 lines of application code from ~76,000 lines of library code
5. Reconstructed the original component structure and file organization
6. Replaced library code with proper npm package imports

### Key mappings discovered

| Bundle | Meaning |
|--------|---------|
| `_A` | `MODEL_ID` = `"onnx-community/gemma-4-E2B-it-ONNX"` |
| `kA` | `ModelProvider` - loads model, runs generation |
| `MA` | `MediaProvider` - webcam, video, audio |
| `SA` / `CA()` | `ModelContext` / `useModel()` hook |
| `AA` / `jA()` | `MediaContext` / `useMedia()` hook |
| `g5` → `h5` → `p5` | `App` → `MainView` → `ChatOverlay` |
| `Of` | `RawImage.read()` from Transformers.js |
| `s1` | `Markdown` from streamdown |
