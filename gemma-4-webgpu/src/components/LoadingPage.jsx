import { useEffect, useState } from "react";
import { useModel } from "../contexts/ModelContext";
import { LOADING_TIPS } from "../constants";

export default function LoadingPage({ onReady }) {
  const { loadState, loadProgress, loadModel } = useModel();
  const [tipIndex, setTipIndex] = useState(0);

  useEffect(() => {
    loadModel();
  }, [loadModel]);

  useEffect(() => {
    if (loadState !== "ready") return;
    const timer = setTimeout(onReady, 500);
    return () => clearTimeout(timer);
  }, [loadState, onReady]);

  useEffect(() => {
    if (loadState !== "loading") return;
    const interval = setInterval(() => {
      setTipIndex((i) => (i + 1) % LOADING_TIPS.length);
    }, 3000);
    return () => clearInterval(interval);
  }, [loadState]);

  return (
    <div className="flex h-full flex-col items-center justify-center gap-8 px-6 animate-fade-in-up bg-dm-bg">
      <h1 className="text-3xl font-bold tracking-tight text-dm-text">
        VIDRAFT
      </h1>

      <div className="flex w-full max-w-sm flex-col items-center gap-4">
        <div className="relative h-2 w-full overflow-hidden rounded-full bg-dm-surface-high">
          <div
            className="h-full rounded-full bg-gradient-to-r from-dm-blue to-dm-green transition-all duration-300 ease-out"
            style={{ width: `${Math.max(loadProgress, 3)}%` }}
          />
          {loadState === "loading" && (
            <div className="absolute inset-0 animate-shimmer bg-[length:200%_100%] bg-gradient-to-r from-transparent via-white/15 to-transparent" />
          )}
        </div>

        <p className="text-2xl font-semibold tabular-nums text-dm-text">
          {Math.round(loadProgress)}%
        </p>

        {loadState === "loading" && (
          <p
            key={tipIndex}
            className="animate-fade-in-up text-sm font-medium bg-[length:200%_auto] bg-clip-text text-transparent animate-glisten"
            style={{
              backgroundImage:
                "linear-gradient(90deg, #b2bbc5 0%, #b2bbc5 40%, #f8f9fc 50%, #b2bbc5 60%, #b2bbc5 100%)",
            }}
          >
            {LOADING_TIPS[tipIndex]}
          </p>
        )}
      </div>

      <p className="absolute bottom-8 text-xs text-dm-text-secondary">
        Powered by Transformers.js
      </p>
    </div>
  );
}
