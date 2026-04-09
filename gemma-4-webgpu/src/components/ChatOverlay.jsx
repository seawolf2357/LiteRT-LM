import { useState, useRef, useEffect, useCallback } from "react";
import {
  Mic,
  Square,
  Camera,
  Brain,
  ArrowUp,
  RotateCcw,
} from "lucide-react";
import { useModel } from "../contexts/ModelContext";
import { useMedia } from "../contexts/MediaContext";
import { SUGGESTED_PROMPTS } from "../constants";
import { generateId } from "../utils";
import MessageBubble from "./MessageBubble";
import TypingIndicator from "./TypingIndicator";

export default function ChatOverlay({
  onScanStart,
  isScanning,
  scanCompleteFrame,
  onScanConsumed,
}) {
  const { generate, stopGeneration } = useModel();
  const { captureFrame, isRecording, startRecording, stopRecording } = useMedia();

  const [messages, setMessages] = useState([]);
  const [inputText, setInputText] = useState("");
  const [isGenerating, setIsGenerating] = useState(false);
  const [thinkingEnabled, setThinkingEnabled] = useState(false);

  const scrollRef = useRef(null);
  const inputTextRef = useRef("");
  const messagesRef = useRef([]);

  // Keep refs in sync
  useEffect(() => {
    inputTextRef.current = inputText;
  }, [inputText]);
  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  const appendToken = useCallback((msgId, token, type) => {
    setMessages((prev) =>
      prev.map((m) =>
        m.id === msgId
          ? type === "thinking"
            ? { ...m, thinking: (m.thinking ?? "") + token }
            : { ...m, content: m.content + token }
          : m,
      ),
    );
  }, []);

  const markDone = useCallback((msgId) => {
    setMessages((prev) =>
      prev.map((m) => (m.id === msgId ? { ...m, isStreaming: false } : m)),
    );
  }, []);

  const resetAssistantMessage = useCallback((msgId) => {
    setMessages((prev) =>
      prev.map((m) =>
        m.id === msgId ? { ...m, content: "", thinking: undefined } : m,
      ),
    );
  }, []);

  const sendMessage = useCallback(
    async ({ text, image, audio, hideText }) => {
      if (!text.trim() || isGenerating) return;

      const userMsg = {
        id: generateId(),
        role: "user",
        content: text.trim(),
        ...(image && { image }),
        ...(audio && { audio }),
        ...(hideText && { hideText }),
      };
      const assistantId = generateId();
      const assistantMsg = {
        id: assistantId,
        role: "assistant",
        content: "",
        isStreaming: true,
      };

      const history = [...messagesRef.current, userMsg];
      setMessages((prev) => [...prev, userMsg, assistantMsg]);
      setInputText("");
      setIsGenerating(true);

      try {
        await generate(history, (token, type) => appendToken(assistantId, token, type), {
          enableThinking: thinkingEnabled,
          captureFrame,
          onToolCall: () => resetAssistantMessage(assistantId),
          onTranscription: (text) => {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === userMsg.id ? { ...m, content: text, hideText: false } : m,
              ),
            );
          },
        });
      } finally {
        markDone(assistantId);
        setIsGenerating(false);
      }
    },
    [isGenerating, thinkingEnabled, generate, captureFrame, appendToken, markDone, resetAssistantMessage],
  );

  // Capture frame button handler
  const handleCapture = useCallback(() => {
    if (isGenerating || isScanning) return;
    const frame = captureFrame();
    if (frame) onScanStart(frame);
  }, [isGenerating, isScanning, captureFrame, onScanStart]);

  // When scan completes, send the frame as a message
  useEffect(() => {
    if (!scanCompleteFrame) return;
    onScanConsumed();
    sendMessage({
      text: inputTextRef.current.trim() || "Describe what you see",
      image: scanCompleteFrame,
    });
  }, [scanCompleteFrame]);

  // Mic button handler
  const handleMic = useCallback(async () => {
    if (isGenerating) return;
    if (isRecording) {
      const audioData = await stopRecording();
      if (!audioData) return;
      sendMessage({
        text: inputTextRef.current.trim() || "Transcribe this audio and respond to what I said.",
        audio: audioData,
        hideText: !inputTextRef.current.trim(),
      });
    } else {
      try {
        await startRecording();
      } catch {}
    }
  }, [isGenerating, isRecording, startRecording, stopRecording, sendMessage]);

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage({ text: inputText });
    }
  };

  const isEmpty = messages.length === 0 && !isGenerating;

  return (
    <div className="fixed inset-x-0 bottom-0 z-20 flex flex-col items-center px-4 pb-4">
      {/* Message list */}
      {messages.length > 0 && (
        <div
          ref={scrollRef}
          className="chat-scroll mb-3 flex max-h-[50vh] w-full max-w-2xl flex-col gap-2.5 overflow-y-auto px-1"
        >
          {messages.map((msg) =>
            msg.role === "assistant" && msg.isStreaming && !msg.content && !msg.thinking
              ? null
              : <MessageBubble key={msg.id} message={msg} />,
          )}
          {isGenerating &&
            messages.at(-1)?.role === "assistant" &&
            !messages.at(-1)?.content &&
            !messages.at(-1)?.thinking && <TypingIndicator />}
        </div>
      )}

      {/* Suggested prompts */}
      {isEmpty && (
        <div className="mb-3 flex flex-wrap justify-center gap-2">
          {SUGGESTED_PROMPTS.map((prompt) => (
            <button
              key={prompt}
              type="button"
              onClick={() => sendMessage({ text: prompt })}
              className="frosted rounded-full px-4 py-2 text-sm font-medium text-dm-text transition-all hover:bg-dm-surface-higher hover:text-white"
            >
              {prompt}
            </button>
          ))}
        </div>
      )}

      {/* Recording indicator */}
      {isRecording && (
        <div className="mb-2 flex items-center gap-2 text-sm text-dm-red">
          <span className="inline-block size-2 animate-pulse rounded-full bg-dm-red" />
          Recording...
        </div>
      )}

      {/* Input bar */}
      <div className="frosted flex w-full max-w-2xl items-center gap-2 rounded-2xl p-2">
        {/* Mic button */}
        <button
          type="button"
          onClick={handleMic}
          disabled={isGenerating && !isRecording}
          className={`relative flex size-10 shrink-0 items-center justify-center rounded-xl transition-all ${
            isRecording
              ? "bg-dm-red text-white"
              : "text-dm-text-secondary hover:text-dm-text"
          } disabled:opacity-40`}
        >
          {isRecording && (
            <span className="absolute inset-0 rounded-xl bg-dm-red animate-pulse-ring" />
          )}
          {isRecording ? (
            <Square className="relative z-10 size-4" />
          ) : (
            <Mic className="size-5" />
          )}
        </button>

        {/* Text input */}
        <input
          type="text"
          value={inputText}
          onChange={(e) => setInputText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask VIDRAFT anything..."
          disabled={isGenerating}
          className="min-w-0 flex-1 bg-transparent px-2 text-sm text-dm-text placeholder-dm-text-secondary/60 outline-none disabled:opacity-50"
        />

        {/* Capture button */}
        <button
          type="button"
          onClick={handleCapture}
          disabled={isGenerating || isScanning}
          className="flex size-10 shrink-0 items-center justify-center rounded-xl text-dm-text-secondary transition-colors hover:text-dm-text disabled:opacity-40"
        >
          <Camera className="size-5" />
        </button>

        {/* Thinking toggle */}
        <button
          type="button"
          onClick={() => setThinkingEnabled((v) => !v)}
          disabled={isGenerating}
          title={thinkingEnabled ? "Thinking enabled" : "Thinking disabled"}
          className={`flex size-10 shrink-0 items-center justify-center rounded-xl transition-all disabled:opacity-40 ${
            thinkingEnabled
              ? "bg-dm-surface-higher text-dm-text"
              : "text-dm-text-secondary hover:text-dm-text"
          }`}
        >
          <Brain className="size-5" />
        </button>

        {/* Send / Stop / Reset button */}
        {isGenerating ? (
          <button
            type="button"
            onClick={stopGeneration}
            title="Stop generating"
            className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-dm-red text-white transition-all hover:opacity-90"
          >
            <Square className="size-4" />
          </button>
        ) : !inputText.trim() && messages.length > 0 ? (
          <button
            type="button"
            onClick={() => setMessages([])}
            title="Reset conversation"
            className="flex size-10 shrink-0 items-center justify-center rounded-xl text-dm-text-secondary transition-all hover:text-dm-text"
          >
            <RotateCcw className="size-5" />
          </button>
        ) : (
          <button
            type="button"
            onClick={() => sendMessage({ text: inputText })}
            disabled={!inputText.trim()}
            className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-dm-text text-dm-bg transition-all hover:opacity-90 disabled:opacity-40"
          >
            <ArrowUp className="size-5" />
          </button>
        )}
      </div>
    </div>
  );
}
