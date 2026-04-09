export const MODEL_ID = "onnx-community/gemma-4-E2B-it-ONNX";

export const SCAN_TIMEOUT = 2000;

export const SUGGESTED_PROMPTS = [
  "What do you see?",
  "Describe the scene",
  "Tell me about yourself",
  "What can you do?",
];

export const SYSTEM_PROMPT =
  "You are Gemma 4, a helpful multimodal AI assistant running entirely in the user's browser via WebGPU. " +
  "The user has a live camera or video feed. You can use the vision tool to capture and analyze the current " +
  "frame whenever the user asks about what they see, what is on screen, their surroundings, or anything visual. " +
  "You can also use the audio tool to listen to the user's microphone input when they ask you to listen or " +
  "transcribe. Always be concise and helpful.";

export const TOOLS = [
  {
    type: "function",
    function: {
      name: "vision",
      description:
        "Captures and analyzes the current camera/video frame. Use this when the user asks anything about " +
        "what they see, what is being shown, what is on screen, their appearance, surroundings, etc.",
      parameters: {
        type: "object",
        properties: {
          prompt: {
            type: "string",
            description:
              "The prompt describing what to analyze in the current frame.",
          },
        },
        required: ["prompt"],
      },
    },
  },
];

export const LOADING_TIPS = [
  "Loading model...",
  "Cached after first load",
  "Runs 100% offline",
  "No data leaves your device",
  "Powered by WebGPU",
  "No server required",
  "Private by design",
  "Works without WiFi after loading",
  "All inference runs locally",
  "Your data stays on your machine",
];

/** Regex to strip channel/turn/special tokens from raw output */
export const SPECIAL_TOKEN_REGEX =
  /<\|channel\|>|<channel\|>|<turn\|>|<eos>|<bos>|<\|channel>|<\|tool_response\|>|<\|tool_response>|<tool_response\|>/g;
