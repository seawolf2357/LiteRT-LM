import { createContext, useContext, useState, useRef, useCallback } from "react";
import {
  AutoProcessor,
  Gemma4ForConditionalGeneration,
  TextStreamer,
  InterruptableStoppingCriteria,
  RawImage,
} from "@huggingface/transformers";

const readImage = RawImage.read.bind(RawImage);
import {
  MODEL_ID,
  TOOLS,
  SEARCH_TOOL,
  SPECIAL_TOKEN_REGEX,
} from "../constants";
import { parseToolCalls, buildChatMessages, decodeImage, webSearch } from "../utils";

const ModelContext = createContext(null);

export function useModel() {
  const ctx = useContext(ModelContext);
  if (!ctx) throw new Error("useModel must be used within a ModelProvider.");
  return ctx;
}

/** Keywords that suggest user wants a web search */
const SEARCH_KEYWORDS = [
  "검색", "search", "찾아", "look up", "google", "최근", "latest", "뉴스",
  "news", "현재", "current", "today", "오늘", "실시간", "real-time", "how much",
  "가격", "price", "날씨", "weather", "환율", "exchange rate", "주가", "stock",
];

function looksLikeSearchQuery(text) {
  const lower = text.toLowerCase();
  return SEARCH_KEYWORDS.some((kw) => lower.includes(kw));
}

export function ModelProvider({ children }) {
  const [loadState, setLoadState] = useState("idle");
  const [loadProgress, setLoadProgress] = useState(0);
  const modelRef = useRef(null);
  const processorRef = useRef(null);
  const loadPromiseRef = useRef(null);
  const stoppingCriteria = useRef(new InterruptableStoppingCriteria());

  /** All tools always active — search uses DuckDuckGo (no key needed) */
  const getActiveTools = useCallback(() => [...TOOLS, SEARCH_TOOL], []);

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
              if (event.status === "progress_total") setLoadProgress(event.progress);
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
   * Core generation with streaming.
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
            if (cleaned) { fullText += cleaned; onToken(cleaned, "content"); }
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
            if (contentPart) { fullText += contentPart; onToken(contentPart, "content"); }
            buffer = "";
            phase = "content";
            return;
          }
          onToken(token, "thinking");
          buffer = "";
          return;
        }

        const cleaned = token.replace(SPECIAL_TOKEN_REGEX, "");
        if (cleaned) { fullText += cleaned; onToken(cleaned, "content"); }
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
      if (cleaned) { fullText += cleaned; onToken(cleaned, phase === "thinking" ? "thinking" : "content"); }
    }

    const rawOutput = processor.batch_decode(
      output.slice(null, [inputs.input_ids.dims.at(-1), null]),
      { skip_special_tokens: false },
    )[0];

    return { text: fullText, rawOutput };
  }, []);

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
      null, audioData, { add_special_tokens: false },
    );

    stoppingCriteria.current.reset();
    const output = await model.generate({
      ...inputs, max_new_tokens: 512, do_sample: false,
      stopping_criteria: [stoppingCriteria.current],
    });

    return processor
      .batch_decode(output.slice(null, [inputs.input_ids.dims.at(-1), null]), { skip_special_tokens: true })[0]
      .trim();
  }, []);

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
   * Analyze a single frame for detection mode.
   */
  const analyzeFrame = useCallback(async (imageDataUrl, condition) => {
    const processor = processorRef.current;
    const model = modelRef.current;
    if (!processor || !model) throw new Error("Model not loaded");

    const canvas = await decodeImage(imageDataUrl);
    if (!canvas) return { detected: false, description: "Failed to decode frame" };

    const prompt =
      `You are a strict visual detection system. Determine if this EXACT condition is present:\n` +
      `CONDITION: "${condition}"\n\n` +
      `CRITICAL RULES:\n` +
      `1. ONLY report detected:true if the condition matches EXACTLY — not something similar\n` +
      `2. Similar but DIFFERENT things must be detected:false. Examples:\n` +
      `   - If condition is "V sign": thumbs up = false, peace sign = true, pointing = false\n` +
      `   - If condition is "cat": dog = false, cat toy = false, real cat = true\n` +
      `   - If condition is "red car": blue car = false, red truck = false\n` +
      `3. When uncertain, ALWAYS choose detected:false\n` +
      `4. Describe what you ACTUALLY see, not what you think matches\n\n` +
      `JSON response ONLY: {"detected": true/false, "description": "what is actually visible"}`;

    const inputs = await processor(
      processor.apply_chat_template(
        [{ role: "user", content: [{ type: "image" }, { type: "text", text: prompt }] }],
        { add_generation_prompt: true },
      ),
      await readImage(canvas), null, { add_special_tokens: false },
    );

    const detectionCriteria = new InterruptableStoppingCriteria();
    const output = await model.generate({
      ...inputs, max_new_tokens: 200, do_sample: false,
      stopping_criteria: [detectionCriteria],
    });

    const rawText = processor
      .batch_decode(output.slice(null, [inputs.input_ids.dims.at(-1), null]), { skip_special_tokens: true })[0]
      .trim();

    // Strict JSON parsing only - no heuristic fallback
    try {
      const jsonMatch = rawText.match(/\{[^}]*"detected"\s*:\s*(true|false)[^}]*\}/);
      if (jsonMatch) {
        const parsed = JSON.parse(jsonMatch[0]);
        return {
          detected: parsed.detected === true,
          description: parsed.description || rawText,
        };
      }
    } catch {}

    // If JSON parsing fails entirely, default to NOT detected (conservative)
    return { detected: false, description: rawText };
  }, []);

  /**
   * High-level generate: text, image, audio, file, search, tool calling.
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

      // Direct image message (from camera capture or image upload)
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

      // Check if this is a file-context message (contains ``` code block from file upload)
      // For file messages: skip tool calling, send directly for analysis
      const hasFileContent = lastMessage?.content?.includes("[File:") && lastMessage?.content?.includes("```");
      if (hasFileContent) {
        const fileMessages = [
          { role: "system", content: "You are VIDRAFT AI. The user has uploaded a file. Analyze the file content provided and answer their question. Be thorough and helpful." },
          ...messages.map((m) => ({ role: m.role, content: m.content })),
        ];
        const { text } = await runGeneration(fileMessages, onToken, {
          enableThinking,
          maxNewTokens: 2048,
        });
        return text;
      }

      // Auto web search: if query looks like a search request
      if (looksLikeSearchQuery(lastMessage?.content || "")) {
        let searchResults = null;
        try {
          onToken("[Searching the web...]\n\n", "content");
          searchResults = await webSearch(lastMessage.content);
        } catch (err) {
          console.error("Web search failed:", err);
          onToken(`[Search failed: ${err.message}]\n\n`, "content");
        }

        if (searchResults) {
          const enrichedMessages = [
            { role: "system", content: "You are VIDRAFT AI. Answer the user's question using the web search results below. Be accurate and cite sources." },
            ...messages.slice(0, -1).map((m) => ({ role: m.role, content: m.content })),
            { role: "user", content: `${lastMessage.content}\n\n[Web Search Results]\n${searchResults}` },
          ];
          const { text } = await runGeneration(enrichedMessages, onToken, { enableThinking, maxNewTokens: 2048 });
          return text;
        }
      }

      // Normal text message with tool calling (for vision tool)
      const activeTools = getActiveTools();
      const chatMessages = buildChatMessages(messages);
      const { text, rawOutput } = await runGeneration(chatMessages, onToken, {
        enableThinking,
        tools: true,
        customTools: activeTools,
      });

      const toolCalls = parseToolCalls(rawOutput);
      if (toolCalls.length === 0) return text;

      // Handle vision tool call
      onToolCall?.();
      const toolResponseMap = {};

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

      // Handle search tool call (fallback if model explicitly calls it)
      const searchCall = toolCalls.find((c) => c.function.name === "web_search");
      if (searchCall) {
        const query = searchCall.function.arguments.query || lastMessage?.content || "";
        try {
          toolResponseMap.web_search = await webSearch(query);
        } catch (err) {
          toolResponseMap.web_search = `Search failed: ${err.message}`;
        }
      }

      const toolResponses = toolCalls.map((call) => ({
        name: call.function.name,
        response: { description: toolResponseMap[call.function.name] || "Tool not available." },
      }));

      const { text: finalText } = await runGeneration(
        [...chatMessages, { role: "assistant", tool_calls: toolCalls }, { role: "user", tool_responses: toolResponses }],
        onToken,
        { enableThinking, tools: true, customTools: activeTools },
      );

      return finalText;
    },
    [runGeneration, transcribeAudio, generateWithImage, getActiveTools],
  );

  const stopGeneration = useCallback(() => {
    stoppingCriteria.current.interrupt();
  }, []);

  return (
    <ModelContext.Provider
      value={{
        loadState, loadProgress, loadModel, generate, analyzeFrame, stopGeneration,
      }}
    >
      {children}
    </ModelContext.Provider>
  );
}
