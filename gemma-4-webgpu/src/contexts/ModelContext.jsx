import { createContext, useContext, useState, useRef, useCallback } from "react";
import {
  AutoProcessor,
  Gemma3ForConditionalGeneration,
  TextStreamer,
  InterruptableStoppingCriteria,
  RawImage,
} from "@huggingface/transformers";

/** Read image from various sources (data URL, canvas, blob, etc.) */
const readImage = RawImage.read.bind(RawImage);
import {
  MODEL_ID,
  TOOLS,
  SPECIAL_TOKEN_REGEX,
} from "../constants";
import { parseToolCalls, buildChatMessages, decodeImage } from "../utils";

const ModelContext = createContext(null);

export function useModel() {
  const ctx = useContext(ModelContext);
  if (!ctx) throw new Error("useModel must be used within a ModelProvider.");
  return ctx;
}

export function ModelProvider({ children }) {
  const [loadState, setLoadState] = useState("idle");
  const [loadProgress, setLoadProgress] = useState(0);
  const modelRef = useRef(null);
  const processorRef = useRef(null);
  const loadPromiseRef = useRef(null);
  const stoppingCriteria = useRef(new InterruptableStoppingCriteria());

  const loadModel = useCallback(async () => {
    if (loadState === "ready") return;
    if (loadPromiseRef.current) return loadPromiseRef.current;

    const promise = (async () => {
      setLoadState("loading");
      setLoadProgress(0);
      try {
        const [processor, model] = await Promise.all([
          AutoProcessor.from_pretrained(MODEL_ID),
          Gemma3ForConditionalGeneration.from_pretrained(MODEL_ID, {
            dtype: {
              audio_encoder: "fp16",
              vision_encoder: "fp16",
              embed_tokens: "q4f16",
              decoder_model_merged: "q4f16",
            },
            device: "webgpu",
            progress_callback: (event) => {
              if (event.status === "progress_total") {
                setLoadProgress(event.progress);
              }
            },
          }),
        ]);
        processorRef.current = processor;
        modelRef.current = model;
        setLoadProgress(100);
        setLoadState("ready");
      } catch (err) {
        console.error("Model load failed:", err);
        setLoadState("error");
        alert(err instanceof Error ? err.message : "Failed to load model");
      } finally {
        loadPromiseRef.current = null;
      }
    })();

    loadPromiseRef.current = promise;
    return promise;
  }, [loadState]);

  /**
   * Run a single generation pass with streaming support.
   * Handles thinking mode (channel tokens) and content streaming.
   */
  const runGeneration = useCallback(async (messages, onToken, options) => {
    const processor = processorRef.current;
    const model = modelRef.current;
    if (!processor || !model) throw new Error("Model not loaded");

    const inputs = await processor(
      processor.apply_chat_template(messages, {
        add_generation_prompt: true,
        ...(options.tools && { tools: TOOLS }),
        ...(options.enableThinking && { enable_thinking: true }),
      }),
      options.image ? await readImage(options.image) : null,
      options.audio ?? null,
      { add_special_tokens: false },
    );

    let fullText = "";
    let buffer = "";
    let phase = "init"; // "init" | "thinking" | "content"

    const streamer = new TextStreamer(processor.tokenizer, {
      skip_prompt: true,
      skip_special_tokens: false,
      callback_function: (token) => {
        buffer += token;

        if (phase === "init") {
          if (buffer.includes("<|channel>thought")) {
            phase = "thinking";
            const remainder = (buffer.split("<|channel>thought").pop() ?? "").replace(/^\n/, "");
            if (remainder) onToken(remainder, "thinking");
            buffer = "";
            return;
          }
          if (buffer.length > 12 || !"<|channel>thought".startsWith(buffer)) {
            const cleaned = buffer.replace(SPECIAL_TOKEN_REGEX, "");
            if (cleaned) {
              fullText += cleaned;
              onToken(cleaned, "content");
            }
            buffer = "";
            phase = "content";
            return;
          }
          return;
        }

        if (phase === "thinking") {
          if (buffer.includes("<channel|>")) {
            const thinkPart = buffer.split("<channel|>")[0];
            if (thinkPart) onToken(thinkPart, "thinking");
            const contentPart = (buffer.split("<channel|>").pop() ?? "").replace(SPECIAL_TOKEN_REGEX, "");
            if (contentPart) {
              fullText += contentPart;
              onToken(contentPart, "content");
            }
            buffer = "";
            phase = "content";
            return;
          }
          onToken(token, "thinking");
          buffer = "";
          return;
        }

        // phase === "content"
        const cleaned = token.replace(SPECIAL_TOKEN_REGEX, "");
        if (cleaned) {
          fullText += cleaned;
          onToken(cleaned, "content");
        }
        buffer = "";
      },
    });

    stoppingCriteria.current.reset();

    const output = await model.generate({
      ...inputs,
      max_new_tokens: 2048,
      do_sample: false,
      streamer,
      stopping_criteria: [stoppingCriteria.current],
    });

    // Flush remaining buffer
    if (buffer) {
      const cleaned = buffer.replace(SPECIAL_TOKEN_REGEX, "");
      if (cleaned) {
        fullText += cleaned;
        onToken(cleaned, phase === "thinking" ? "thinking" : "content");
      }
    }

    const rawOutput = processor.batch_decode(
      output.slice(null, [inputs.input_ids.dims.at(-1), null]),
      { skip_special_tokens: false },
    )[0];

    return { text: fullText, rawOutput };
  }, []);

  /**
   * Transcribe audio using the model's speech recognition capability.
   */
  const transcribeAudio = useCallback(async (audioData) => {
    const processor = processorRef.current;
    const model = modelRef.current;
    if (!processor || !model) throw new Error("Model not loaded");

    const inputs = await processor(
      processor.apply_chat_template(
        [
          {
            role: "system",
            content: "Transcribe the following speech segment in English into English text.",
          },
          { role: "user", content: [{ type: "audio" }] },
        ],
        { add_generation_prompt: true },
      ),
      null,
      audioData,
      { add_special_tokens: false },
    );

    stoppingCriteria.current.reset();

    const output = await model.generate({
      ...inputs,
      max_new_tokens: 512,
      do_sample: false,
      stopping_criteria: [stoppingCriteria.current],
    });

    return processor
      .batch_decode(output.slice(null, [inputs.input_ids.dims.at(-1), null]), {
        skip_special_tokens: true,
      })[0]
      .trim();
  }, []);

  /**
   * Handle a direct image message (user sent a frame with text).
   */
  const generateWithImage = useCallback(
    async (messages, lastMessage, onToken, enableThinking) => {
      const canvas = await decodeImage(lastMessage.image);
      if (!canvas) throw new Error("Failed to decode captured frame");
      return runGeneration(
        [
          {
            role: "user",
            content: [
              { type: "image" },
              { type: "text", text: lastMessage.content },
            ],
          },
        ],
        onToken,
        { enableThinking, image: canvas },
      );
    },
    [runGeneration],
  );

  /**
   * High-level generate function that handles text, image, audio, and tool calling.
   */
  const generate = useCallback(
    async (messages, onToken, options) => {
      const {
        enableThinking = false,
        captureFrame,
        onToolCall,
        onTranscription,
      } = options ?? {};

      const lastMessage = messages[messages.length - 1];

      // Direct image message
      if (lastMessage?.image) {
        const { text } = await generateWithImage(messages, lastMessage, onToken, enableThinking);
        return text;
      }

      // Audio message: transcribe first, then generate
      if (lastMessage?.audio) {
        const transcription = await transcribeAudio(lastMessage.audio);
        onTranscription?.(transcription);
        return generate(
          [...messages.slice(0, -1), { ...lastMessage, content: transcription, audio: undefined }],
          onToken,
          { ...options, onTranscription: undefined },
        );
      }

      // Text message with tool calling
      const chatMessages = buildChatMessages(messages);
      const { text, rawOutput } = await runGeneration(chatMessages, onToken, {
        enableThinking,
        tools: true,
      });

      const toolCalls = parseToolCalls(rawOutput);
      if (toolCalls.length === 0) return text;

      // Handle tool calls
      onToolCall?.();
      const visionCall = toolCalls.find((c) => c.function.name === "vision");
      let toolResponse = "Could not capture frame.";

      if (visionCall && captureFrame) {
        const frameDataUrl = captureFrame();
        if (frameDataUrl) {
          const canvas = await decodeImage(frameDataUrl);
          if (canvas) {
            const { text: visionText } = await runGeneration(
              [
                {
                  role: "user",
                  content: [
                    { type: "image" },
                    {
                      type: "text",
                      text: visionCall.function.arguments.prompt || "Describe what you see",
                    },
                  ],
                },
              ],
              onToken,
              { enableThinking: false, image: canvas },
            );
            toolResponse = visionText;
          }
        }
      }

      const toolResponses = toolCalls.map((call) => ({
        name: call.function.name,
        response: { description: toolResponse },
      }));

      const { text: finalText } = await runGeneration(
        [
          ...chatMessages,
          { role: "assistant", tool_calls: toolCalls },
          { role: "user", tool_responses: toolResponses },
        ],
        onToken,
        { enableThinking, tools: true },
      );

      return finalText;
    },
    [runGeneration, transcribeAudio, generateWithImage],
  );

  const stopGeneration = useCallback(() => {
    stoppingCriteria.current.interrupt();
  }, []);

  return (
    <ModelContext.Provider
      value={{ loadState, loadProgress, loadModel, generate, stopGeneration }}
    >
      {children}
    </ModelContext.Provider>
  );
}
