import { useState } from "react";
import { X, Search, ExternalLink, CheckCircle2, XCircle } from "lucide-react";
import { useModel } from "../contexts/ModelContext";
import { braveSearch } from "../utils";

export default function SettingsPanel({ onClose }) {
  const { braveApiKey, updateBraveApiKey } = useModel();
  const [keyInput, setKeyInput] = useState(braveApiKey);
  const [testStatus, setTestStatus] = useState(null); // null | "testing" | "ok" | "error"
  const [testError, setTestError] = useState("");

  const handleSave = () => {
    updateBraveApiKey(keyInput.trim());
    onClose();
  };

  const handleTest = async () => {
    if (!keyInput.trim()) return;
    setTestStatus("testing");
    setTestError("");
    try {
      const result = await braveSearch("test", keyInput.trim());
      setTestStatus(result ? "ok" : "error");
    } catch (err) {
      setTestStatus("error");
      setTestError(err.message);
    }
  };

  return (
    <div className="fixed inset-x-0 top-0 bottom-0 z-30 flex items-start justify-center pt-16 px-4">
      <div className="frosted w-full max-w-md rounded-2xl shadow-xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-dm-outline px-4 py-3">
          <h2 className="text-sm font-semibold text-dm-text">Settings</h2>
          <button type="button" onClick={onClose} className="text-dm-text-secondary hover:text-dm-text">
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
              type="text"
              value={keyInput}
              onChange={(e) => { setKeyInput(e.target.value); setTestStatus(null); }}
              placeholder="BSA-xxxxxxxxxxxxxxxx"
              className="mb-2 w-full rounded-xl border border-dm-outline bg-dm-surface-high px-3 py-2 text-sm text-dm-text placeholder-dm-text-secondary/50 outline-none focus:border-dm-blue font-mono"
            />
            <div className="flex items-center gap-3">
              <a
                href="https://brave.com/search/api/"
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-xs text-dm-blue hover:underline"
              >
                Get a free API key <ExternalLink className="size-3" />
              </a>
              {keyInput.trim() && (
                <button
                  type="button"
                  onClick={handleTest}
                  disabled={testStatus === "testing"}
                  className="text-xs text-dm-blue hover:underline disabled:opacity-50"
                >
                  {testStatus === "testing" ? "Testing..." : "Test Connection"}
                </button>
              )}
            </div>
          </div>

          {/* Test result */}
          {testStatus === "ok" && (
            <div className="flex items-center gap-2 rounded-lg bg-dm-green/10 px-3 py-2 text-xs text-dm-green">
              <CheckCircle2 className="size-4" />
              API key is valid. Web search is working.
            </div>
          )}
          {testStatus === "error" && (
            <div className="flex items-start gap-2 rounded-lg bg-dm-red/10 px-3 py-2 text-xs text-dm-red">
              <XCircle className="size-4 shrink-0 mt-0.5" />
              <span>{testError || "API key test failed."}</span>
            </div>
          )}

          {/* Status */}
          <div className="rounded-lg bg-dm-surface-high/60 px-3 py-2 text-xs text-dm-text-secondary">
            {keyInput.trim() ? (
              <span className="flex items-center gap-1.5">
                <span className="size-2 rounded-full bg-dm-green" />
                Web search will be enabled (auto-triggers on search keywords)
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
