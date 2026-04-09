import { useState, useRef, useEffect, useCallback } from "react";
import {
  Mic,
  Square,
  Camera,
  Brain,
  ArrowUp,
  RotateCcw,
  Paperclip,
  Download,
} from "lucide-react";
import { useModel } from "../contexts/ModelContext";
import { useMedia } from "../contexts/MediaContext";
import { SUGGESTED_PROMPTS } from "../constants";
import { generateId, processUploadedFile, exportAsMarkdown, exportAsJson } from "../utils";
import MessageBubble from "./MessageBubble";
import TypingIndicator from "./TypingIndicator";

export default function ChatOverlay({
  onScanStart,
  isScanning,
  scanCompleteFrame,
  onScanConsumed,
}) {
  const { generate, stopGeneration } = useModel();
  const { captureFrame, captureFrameAsync, isRecording, startRecording, stopRecording, videoSource } = useMedia();

  const [messages, setMessages] = useState([]);
  const [inputText, setInputText] = useState("");
  const [isGenerating, setIsGenerating] = useState(false);
  const [thinkingEnabled, setThinkingEnabled] = useState(false);
  const [pendingFile, setPendingFile] = useState(null); // { text?, image?, fileName }
  const [captureError, setCaptureError] = useState(null);
  const [showExport, setShowExport] = useState(false);

  const scrollRef = useRef(null);
  const inputTextRef = useRef("");
  const messagesRef = useRef([]);
  const fileInputRef = useRef(null);
  const textInputRef = useRef(null);

  // Keep refs in sync
  useEffect(() => { inputTextRef.current = inputText; }, [inputText]);
  useEffect(() => { messagesRef.current = messages; }, [messages]);
  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [messages]);

  // Clear capture error after 3s
  useEffect(() => {
    if (!captureError) return;
    const t = setTimeout(() => setCaptureError(null), 3000);
    return () => clearTimeout(t);
  }, [captureError]);

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
      if ((!text.trim() && !image && !pendingFile) || isGenerating) return;

      // Build message content with file context
      let finalText = text.trim();
      let finalImage = image;

      if (pendingFile) {
        if (pendingFile.image) {
          finalImage = pendingFile.image;
          if (!finalText) finalText = `Analyze this image: ${pendingFile.fileName}`;
        } else if (pendingFile.text) {
          const prefix = `[File: ${pendingFile.fileName}]\n\`\`\`\n${pendingFile.text}\n\`\`\`\n\n`;
          finalText = prefix + (finalText || `Analyze and summarize this file.`);
        }
        setPendingFile(null);
      }

      if (!finalText && !finalImage) return;

      const userMsg = {
        id: generateId(),
        role: "user",
        content: finalText,
        ...(finalImage && { image: finalImage }),
        ...(audio && { audio }),
        ...(hideText && { hideText }),
      };
      const assistantId = generateId();
      const assistantMsg = { id: assistantId, role: "assistant", content: "", isStreaming: true };

      const history = [...messagesRef.current, userMsg];
      setMessages((prev) => [...prev, userMsg, assistantMsg]);
      setInputText("");
      setIsGenerating(true);

      try {
        await generate(history, (token, type) => appendToken(assistantId, token, type), {
          enableThinking: thinkingEnabled,
          captureFrame,
          onToolCall: () => resetAssistantMessage(assistantId),
          onTranscription: (transcribedText) => {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === userMsg.id ? { ...m, content: transcribedText, hideText: false } : m,
              ),
            );
          },
        });
      } finally {
        markDone(assistantId);
        setIsGenerating(false);
      }
    },
    [isGenerating, thinkingEnabled, generate, captureFrame, appendToken, markDone, resetAssistantMessage, pendingFile],
  );

  // Capture frame button with async retry and error feedback
  const handleCapture = useCallback(async () => {
    if (isGenerating || isScanning) return;
    if (videoSource === "blank") {
      setCaptureError("No camera active in Chat Only mode");
      return;
    }
    const frame = await captureFrameAsync();
    if (frame) {
      onScanStart(frame);
    } else {
      setCaptureError("Could not capture frame. Camera may still be loading.");
    }
  }, [isGenerating, isScanning, videoSource, captureFrameAsync, onScanStart]);

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
      try { await startRecording(); } catch {}
    }
  }, [isGenerating, isRecording, startRecording, stopRecording, sendMessage]);

  // File upload handler
  const handleFileUpload = useCallback(async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = "";
    const result = await processUploadedFile(file);
    if (result) {
      setPendingFile(result);
      textInputRef.current?.focus();
    }
  }, []);

  // Clipboard paste handler (Ctrl+V for images)
  const handlePaste = useCallback(async (e) => {
    const items = e.clipboardData?.items;
    if (!items) return;
    for (const item of items) {
      if (item.type.startsWith("image/")) {
        e.preventDefault();
        const blob = item.getAsFile();
        if (!blob) continue;
        const reader = new FileReader();
        reader.onload = () => {
          setPendingFile({ image: reader.result, fileName: "clipboard-image.png", fileType: "image" });
          textInputRef.current?.focus();
        };
        reader.readAsDataURL(blob);
        return;
      }
    }
  }, []);

  // Export conversation
  const handleExport = useCallback((format) => {
    const data = format === "md" ? exportAsMarkdown(messages) : exportAsJson(messages);
    const ext = format === "md" ? "md" : "json";
    const type = format === "md" ? "text/markdown" : "application/json";
    const blob = new Blob([data], { type });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `vidraft-conversation.${ext}`;
    a.click();
    URL.revokeObjectURL(url);
    setShowExport(false);
  }, [messages]);

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
              className="frosted rounded-full px-4 py-2 text-sm font-medium text-dm-text transition-all hover:bg-dm-surface-higher"
            >
              {prompt}
            </button>
          ))}
        </div>
      )}

      {/* Capture error toast */}
      {captureError && (
        <div className="mb-2 rounded-lg bg-dm-red/10 px-3 py-1.5 text-xs text-dm-red">
          {captureError}
        </div>
      )}

      {/* Recording indicator */}
      {isRecording && (
        <div className="mb-2 flex items-center gap-2 text-sm text-dm-red">
          <span className="inline-block size-2 animate-pulse rounded-full bg-dm-red" />
          Recording...
        </div>
      )}

      {/* Pending file indicator */}
      {pendingFile && (
        <div className="mb-2 flex items-center gap-2 rounded-lg bg-dm-surface-high px-3 py-1.5 text-xs text-dm-text">
          <Paperclip className="size-3.5" />
          <span className="truncate max-w-[200px]">{pendingFile.fileName}</span>
          <button
            type="button"
            onClick={() => setPendingFile(null)}
            className="ml-1 text-dm-text-secondary hover:text-dm-text"
          >
            &times;
          </button>
        </div>
      )}

      {/* Input bar */}
      <div className="frosted flex w-full max-w-2xl items-center gap-2 rounded-2xl p-2">
        {/* File upload button */}
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          disabled={isGenerating}
          title="Upload file (TXT, CSV, PDF, Image...)"
          className="flex size-10 shrink-0 items-center justify-center rounded-xl text-dm-text-secondary transition-colors hover:text-dm-text disabled:opacity-40"
        >
          <Paperclip className="size-5" />
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept=".txt,.csv,.json,.md,.xml,.html,.css,.js,.py,.pdf,.png,.jpg,.jpeg,.gif,.webp,.yaml,.yml,.toml,.log,.sql"
          onChange={handleFileUpload}
          className="hidden"
        />

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
          ref={textInputRef}
          type="text"
          value={inputText}
          onChange={(e) => setInputText(e.target.value)}
          onKeyDown={handleKeyDown}
          onPaste={handlePaste}
          placeholder={pendingFile ? `Ask about ${pendingFile.fileName}...` : "Ask VIDRAFT anything..."}
          disabled={isGenerating}
          className="min-w-0 flex-1 bg-transparent px-2 text-sm text-dm-text placeholder-dm-text-secondary/60 outline-none disabled:opacity-50"
        />

        {/* Capture button */}
        <button
          type="button"
          onClick={handleCapture}
          disabled={isGenerating || isScanning}
          title="Capture camera frame"
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

        {/* Export button (when messages exist) */}
        {messages.length > 0 && !isGenerating && (
          <div className="relative">
            <button
              type="button"
              onClick={() => setShowExport((v) => !v)}
              title="Export conversation"
              className="flex size-10 shrink-0 items-center justify-center rounded-xl text-dm-text-secondary transition-colors hover:text-dm-text"
            >
              <Download className="size-5" />
            </button>
            {showExport && (
              <div className="absolute bottom-12 right-0 frosted rounded-xl p-1 flex flex-col gap-0.5 min-w-[120px]">
                <button
                  type="button"
                  onClick={() => handleExport("md")}
                  className="rounded-lg px-3 py-1.5 text-xs text-dm-text hover:bg-dm-surface-higher text-left"
                >
                  Markdown (.md)
                </button>
                <button
                  type="button"
                  onClick={() => handleExport("json")}
                  className="rounded-lg px-3 py-1.5 text-xs text-dm-text hover:bg-dm-surface-higher text-left"
                >
                  JSON (.json)
                </button>
              </div>
            )}
          </div>
        )}

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
        ) : !inputText.trim() && !pendingFile && messages.length > 0 ? (
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
            disabled={!inputText.trim() && !pendingFile}
            className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-dm-text text-dm-bg transition-all hover:opacity-90 disabled:opacity-40"
          >
            <ArrowUp className="size-5" />
          </button>
        )}
      </div>
    </div>
  );
}
