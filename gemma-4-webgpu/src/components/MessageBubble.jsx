import Markdown from "react-markdown";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";
import { preprocessMath } from "../utils";
import ThinkingToggle from "./ThinkingToggle";
import AudioWaveform from "./AudioWaveform";

export default function MessageBubble({ message }) {
  const isUser = message.role === "user";
  const hasThinking = !!message.thinking;
  const isThinkingOnly = hasThinking && !message.content;

  return (
    <div className={`flex animate-fade-in-up ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[80%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed ${
          isUser
            ? "bg-dm-surface-higher text-dm-text"
            : "frosted text-dm-text"
        }`}
      >
        {message.image && (
          <img
            src={message.image}
            alt="Captured frame"
            className="mb-2 h-20 w-auto rounded-lg"
          />
        )}

        {message.audio && <AudioWaveform audio={message.audio} />}

        {hasThinking && (
          <ThinkingToggle
            thinking={message.thinking}
            isStreaming={message.isStreaming && isThinkingOnly}
          />
        )}

        {!(message.hideText && message.audio) &&
          (message.content ? (
            isUser ? (
              <span className="whitespace-pre-wrap">{message.content}</span>
            ) : (
              <Markdown
                remarkPlugins={[[remarkMath, { singleDollarTextMath: true }]]}
                rehypePlugins={[rehypeKatex]}
              >
                {preprocessMath(message.content)}
              </Markdown>
            )
          ) : message.isStreaming ? (
            <span className="inline-block animate-pulse text-dm-blue">|</span>
          ) : null)}
      </div>
    </div>
  );
}
