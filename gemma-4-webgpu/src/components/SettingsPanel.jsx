import { useState } from "react";
import { X, Search, ExternalLink } from "lucide-react";
import { useModel } from "../contexts/ModelContext";

export default function SettingsPanel({ onClose }) {
  const { braveApiKey, updateBraveApiKey } = useModel();
  const [keyInput, setKeyInput] = useState(braveApiKey);

  const handleSave = () => {
    updateBraveApiKey(keyInput.trim());
    onClose();
  };

  return (
    <div className="fixed inset-x-0 top-0 bottom-0 z-30 flex items-start justify-center pt-16 px-4">
      <div className="frosted w-full max-w-md rounded-2xl shadow-xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-dm-outline px-4 py-3">
          <h2 className="text-sm font-semibold text-dm-text">Settings</h2>
          <button
            type="button"
            onClick={onClose}
            className="text-dm-text-secondary hover:text-dm-text"
          >
            <X className="size-5" />
          </button>
        </div>

        <div className="flex flex-col gap-5 p-4">
          {/* Brave Search API Key */}
          <div>
            <div className="mb-2 flex items-center gap-2">
              <Search className="size-4 text-dm-blue" />
              <span className="text-xs font-medium text-dm-text">Web Search (Brave API)</span>
            </div>
            <p className="mb-2 text-xs text-dm-text-secondary">
              Enable web search by entering your Brave Search API key. Free tier: 2,000 queries/month.
            </p>
            <input
              type="password"
              value={keyInput}
              onChange={(e) => setKeyInput(e.target.value)}
              placeholder="BSA-xxxxxxxxxxxxxxxx"
              className="mb-2 w-full rounded-xl border border-dm-outline bg-dm-surface-high px-3 py-2 text-sm text-dm-text placeholder-dm-text-secondary/50 outline-none focus:border-dm-blue"
            />
            <a
              href="https://brave.com/search/api/"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-xs text-dm-blue hover:underline"
            >
              Get a free API key
              <ExternalLink className="size-3" />
            </a>
          </div>

          {/* Status */}
          <div className="rounded-lg bg-dm-surface-high/60 px-3 py-2 text-xs text-dm-text-secondary">
            {keyInput.trim() ? (
              <span className="flex items-center gap-1.5">
                <span className="size-2 rounded-full bg-dm-green" />
                Web search will be enabled
              </span>
            ) : (
              <span className="flex items-center gap-1.5">
                <span className="size-2 rounded-full bg-dm-text-secondary/40" />
                Web search disabled (no API key)
              </span>
            )}
          </div>

          {/* Save */}
          <button
            type="button"
            onClick={handleSave}
            className="rounded-xl bg-dm-text px-4 py-2.5 text-sm font-medium text-dm-bg transition-all hover:opacity-90"
          >
            Save
          </button>
        </div>
      </div>
    </div>
  );
}
