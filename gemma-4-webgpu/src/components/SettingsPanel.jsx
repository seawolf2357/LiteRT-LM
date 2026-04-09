import { useState } from "react";
import { X, Search, CheckCircle2, XCircle, Sparkles } from "lucide-react";
import { webSearch } from "../utils";
import { useModel } from "../contexts/ModelContext";

export default function SettingsPanel({ onClose }) {
  const { smartDecoding, updateSmartDecoding } = useModel();
  const [testStatus, setTestStatus] = useState(null);
  const [testResult, setTestResult] = useState("");

  const handleTest = async () => {
    setTestStatus("testing");
    setTestResult("");
    try {
      const result = await webSearch("test search query");
      setTestStatus("ok");
      setTestResult(result.split("\n")[0]); // show first result title
    } catch (err) {
      setTestStatus("error");
      setTestResult(err.message);
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
          {/* Web Search */}
          <div>
            <div className="mb-2 flex items-center gap-2">
              <Search className="size-4 text-dm-blue" />
              <span className="text-xs font-medium text-dm-text">Web Search</span>
            </div>
            <p className="mb-3 text-xs text-dm-text-secondary">
              Web search is enabled by default using DuckDuckGo (no API key required).
              Search triggers automatically when your message contains keywords like:
              검색, search, 최근, latest, news, 날씨, weather, 가격, price, etc.
            </p>

            <div className="mb-3 flex items-center gap-1.5 rounded-lg bg-dm-surface-high/60 px-3 py-2 text-xs text-dm-text-secondary">
              <span className="size-2 rounded-full bg-dm-green" />
              Web search active (DuckDuckGo via proxy — no key needed)
            </div>

            <button
              type="button"
              onClick={handleTest}
              disabled={testStatus === "testing"}
              className="text-xs text-dm-blue hover:underline disabled:opacity-50"
            >
              {testStatus === "testing" ? "Testing..." : "Test Search Connection"}
            </button>
          </div>

          {/* Smart Decoding */}
          <div className="border-t border-dm-outline pt-4">
            <div className="mb-2 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Sparkles className="size-4 text-dm-blue" />
                <span className="text-xs font-medium text-dm-text">Smart Decoding</span>
              </div>
              <button
                type="button"
                role="switch"
                aria-checked={smartDecoding}
                onClick={() => updateSmartDecoding(!smartDecoding)}
                className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
                  smartDecoding ? "bg-dm-blue" : "bg-dm-surface-higher"
                }`}
              >
                <span
                  className={`inline-block size-4 transform rounded-full bg-white transition-transform ${
                    smartDecoding ? "translate-x-4" : "translate-x-0.5"
                  }`}
                />
              </button>
            </div>
            <p className="text-xs text-dm-text-secondary leading-relaxed">
              Entropy-gated top-K sampling that tightens token selection on uncertain
              steps. May improve answer quality on hard reasoning questions
              (~1-3% gain). Switches from greedy to low-temperature (0.4) sampling,
              so answers may vary slightly between runs. ~5% latency overhead.
              <span className="block mt-1 text-dm-text-secondary/80">
                Independent of Thinking mode — works with thinking off.
              </span>
            </p>
          </div>

          {/* Test result */}
          {testStatus === "ok" && (
            <div className="flex items-start gap-2 rounded-lg bg-dm-green/10 px-3 py-2 text-xs text-dm-green">
              <CheckCircle2 className="size-4 shrink-0 mt-0.5" />
              <div>
                <div className="font-medium">Search is working!</div>
                <div className="text-dm-text-secondary mt-0.5">{testResult}</div>
              </div>
            </div>
          )}
          {testStatus === "error" && (
            <div className="flex items-start gap-2 rounded-lg bg-dm-red/10 px-3 py-2 text-xs text-dm-red">
              <XCircle className="size-4 shrink-0 mt-0.5" />
              <span>{testResult || "Search test failed."}</span>
            </div>
          )}

          {/* Close */}
          <button
            type="button"
            onClick={onClose}
            className="rounded-xl bg-dm-text px-4 py-2.5 text-sm font-medium text-dm-bg transition-all hover:opacity-90"
          >
            Done
          </button>
        </div>
      </div>
    </div>
  );
}
