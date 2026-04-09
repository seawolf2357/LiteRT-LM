import { useState } from "react";
import { Brain, ChevronDown, ChevronRight } from "lucide-react";

export default function ThinkingToggle({ thinking, isStreaming }) {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <div className="mb-2">
      <button
        type="button"
        onClick={() => setIsOpen((v) => !v)}
        className="flex items-center gap-1.5 text-xs text-dm-text-secondary hover:text-dm-text transition-colors"
      >
        <Brain className="size-3.5" />
        <span>{isStreaming ? "Thinking..." : "Thought process"}</span>
        {isOpen ? (
          <ChevronDown className="size-3.5" />
        ) : (
          <ChevronRight className="size-3.5" />
        )}
      </button>
      {isOpen && (
        <div className="mt-1.5 max-h-48 overflow-y-auto rounded-lg bg-dm-surface-high/60 px-3 py-2 text-xs leading-relaxed text-dm-text-secondary whitespace-pre-wrap">
          {thinking}
        </div>
      )}
    </div>
  );
}
