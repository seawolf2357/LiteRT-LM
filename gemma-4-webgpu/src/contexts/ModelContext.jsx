import { createContext, useContext, useState, useRef, useCallback } from "react";
import {
  AutoProcessor,
  Gemma4ForConditionalGeneration,
  TextStreamer,
  InterruptableStoppingCriteria,
  RawImage,
} from "@huggingface/transformers";

/** Read image from various sources (data URL, canvas, blob, etc.) */
const readImage = RawImage.read.bind(RawImage);
import {
  MODEL_ID,
  TOOLS,
  SEARCH_TOOL,
  SPECIAL_TOKEN_REGEX,
} from "../constants";
import { parseToolCalls, buildChatMessages, decodeImage, braveSearch } from "../utils";

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

  // Brave Search API key (stored in localStorage)
  const [braveApiKey, setBraveApiKey] = useState(
    () => localStorage.getItem("vidraft_brave_api_key") || "",
  );

  const updateBraveApiKey = useCallback((key) => {
    setBraveApiKey(key);
    if (key) localStorage.setItem("vidraft_brave_api_key", key);
    else localStorage.removeItem("vidraft_brave_api_key");
  }, []);

  /** Get active tools based on available API keys */
  const getActiveTools = useCallback(() => {
    return braveApiKey ? [...TOOLS, SEARCH_TOOL] : TOOLS;
  }, [braveApiKey]);

  const loadModel = useCallback(async () => {
    if (loadState === "ready") return;
    if (loadPromiseRef.current) return loadPromiseRef.current;

    const promise = (async () => {
      setLoadState("loading");
      setLoadProgress(0);
      try {
        const [processor, model] = await Promise.all([
          AutoProcessor.from_pretrained(MODEL_ID),
          Gemma4ForConditionalGeneration.from_pretrained(MODEL_ID, {
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
   */
  const runGeneration = useCallback(async (messages, onToken, options) => {
    const processor = processorRef.current;
    const model = modelRef.current;
    if (!processor || !model) throw new Error("Model not loaded");

    const activeTools = options.tools ? (options.customTools || TOOLS) : undefined;

    const inputs = await processor(
      processor.apply_chat_template(messages, {
        add_generation_prompt: true,
        ...(activeTools && { tools: activeTools }),
        ...(options.enableThinking && { enable_thinking: true }),
      }),
      options.image ? await readImage(options.image) : null,
      options.audio ?? null,
      { add_special_tokens: false },
    );

    let fullText = "";
    let buffer = "";
    let phase = "init";

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
      max_new_tokens: options.maxNewTokens || 2048,
      do_sample: false,
      streamer,
      stopping_criteria: [stoppingCriteria.current],
    });

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
   * Transcribe audio.
   */
  const transcribeAudio = useCallback(async (audioData) => {
    const processor = processorRef.current;
    const model = modelRef.current;
    if (!processor || !model) throw new Error("Model not loaded");

    const inputs = await processor(
      processor.apply_chat_template(
        [
          { role: "system", content: "Transcribe the following speech segment in English into English text." },
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
      .batch_decode(output.slice(null, [inputs.input_ids.dims.at(-1), null]), { skip_special_tokens: true })[0]
      .trim();
  }, []);

  /**
   * Handle a direct image message.
   */
  const generateWithImage = useCallback(
    async (messages, lastMessage, onToken, enableThinking) => {
      const canvas = await decodeImage(lastMessage.image);
      if (!canvas) throw new Error("Failed to decode captured frame");
      return runGeneration(
        [{ role: "user", content: [{ type: "image" }, { type: "text", text: lastMessage.content }] }],
        onToken,
        { enableThinking, image: canvas },
      );
    },
    [runGeneration],
  );

  /**
   * Analyze a single frame for detection mode (non-streaming, short response).
   * Returns { detected: boolean, description: string }
   */
  const analyzeFrame = useCallback(async (imageDataUrl, condition) => {
    const processor = processorRef.current;
    const model = modelRef.current;
    if (!processor || !model) throw new Error("Model not loaded");

    const canvas = await decodeImage(imageDataUrl);
    if (!canvas) return { detected: false, description: "Failed to decode frame" };

    const prompt =
      `Analyze this image for the following condition: "${condition}"\n` +
      `Respond with ONLY a JSON object: {"detected": true or false, "description": "brief explanation"}\n` +
      `Do not include any other text.`;

    const inputs = await processor(
      processor.apply_chat_template(
        [{ role: "user", content: [{ type: "image" }, { type: "text", text: prompt }] }],
        { add_generation_prompt: true },
      ),
      await readImage(canvas),
      null,
      { add_special_tokens: false },
    );

    stoppingCriteria.current.reset();
    const output = await model.generate({
      ...inputs,
      max_new_tokens: 256,
      do_sample: false,
      stopping_criteria: [stoppingCriteria.current],
    });

    const rawText = processor
      .batch_decode(output.slice(null, [inputs.input_ids.dims.at(-1), null]), { skip_special_tokens: true })[0]
      .trim();

    try {
      const jsonMatch = rawText.match(/\{[\s\S]*\}/);
      if (jsonMatch) {
        const parsed = JSON.parse(jsonMatch[0]);
        return {
          detected: !!parsed.detected,
          description: parsed.description || rawText,
        };
      }
    } catch {}

    // Fallback: heuristic detection from text
    const lower = rawText.toLowerCase();
    const detected = lower.includes('"detected": true') || lower.includes('"detected":true');
    return { detected, description: rawText };
  }, []);

  /**
   * High-level generate function that handles text, image, audio, tool calling, and search.
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

      // Audio message
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
      const activeTools = getActiveTools();
      const chatMessages = buildChatMessages(messages);
      const { text, rawOutput } = await runGeneration(chatMessages, onToken, {
        enableThinking,
        tools: true,
        customTools: activeTools,
      });

      const toolCalls = parseToolCalls(rawOutput);
      if (toolCalls.length === 0) return text;

      // Handle tool calls
      onToolCall?.();
      const toolResponseMap = {};

      // Handle vision tool
      const visionCall = toolCalls.find((c) => c.function.name === "vision");
      if (visionCall) {
        let response = "Could not capture frame.";
        if (captureFrame) {
          const frameDataUrl = captureFrame();
          if (frameDataUrl) {
            const canvas = await decodeImage(frameDataUrl);
            if (canvas) {
              const { text: visionText } = await runGeneration(
                [{ role: "user", content: [{ type: "image" }, { type: "text", text: visionCall.function.arguments.prompt || "Describe what you see" }] }],
                onToken,
                { enableThinking: false, image: canvas },
              );
              response = visionText;
            }
          }
        }
        toolResponseMap.vision = response;
      }

      // Handle search tool
      const searchCall = toolCalls.find((c) => c.function.name === "web_search");
      if (searchCall && braveApiKey) {
        const query = searchCall.function.arguments.query || "";
        if (query) {
          try {
            const searchResults = await braveSearch(query, braveApiKey);
            toolResponseMap.web_search = searchResults;
          } catch (err) {
            toolResponseMap.web_search = `Search failed: ${err.message}`;
          }
        } else {
          toolResponseMap.web_search = "No search query provided.";
        }
      }

      const toolResponses = toolCalls.map((call) => ({
        name: call.function.name,
        response: { description: toolResponseMap[call.function.name] || "Tool not available." },
      }));

      const { text: finalText } = await runGeneration(
        [
          ...chatMessages,
          { role: "assistant", tool_calls: toolCalls },
          { role: "user", tool_responses: toolResponses },
        ],
        onToken,
        { enableThinking, tools: true, customTools: activeTools },
      );

      return finalText;
    },
    [runGeneration, transcribeAudio, generateWithImage, getActiveTools, braveApiKey],
  );

  const stopGeneration = useCallback(() => {
    stoppingCriteria.current.interrupt();
  }, []);

  return (
    <ModelContext.Provider
      value={{
        loadState,
        loadProgress,
        loadModel,
        generate,
        analyzeFrame,
        stopGeneration,
        braveApiKey,
        updateBraveApiKey,
      }}
    >
      {children}
    </ModelContext.Provider>
  );
}
