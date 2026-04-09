import { useState, useRef, useCallback, useEffect } from "react";
import { Play, Square, X, ScanSearch, RotateCcw } from "lucide-react";
import { useModel } from "../contexts/ModelContext";
import { useMedia } from "../contexts/MediaContext";
import DetectionResult from "./DetectionResult";

/** Create a small thumbnail from a data URL */
function createThumbnail(dataUrl, maxSize = 200) {
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => {
      const scale = Math.min(1, maxSize / Math.max(img.width, img.height));
      const w = Math.round(img.width * scale);
      const h = Math.round(img.height * scale);
      const canvas = document.createElement("canvas");
      canvas.width = w;
      canvas.height = h;
      const ctx = canvas.getContext("2d");
      ctx?.drawImage(img, 0, 0, w, h);
      resolve(canvas.toDataURL("image/jpeg", 0.6));
    };
    img.onerror = () => resolve(dataUrl);
    img.src = dataUrl;
  });
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

export default function DetectionPanel({ onClose }) {
  const { analyzeFrame } = useModel();
  const { captureFrameAsync, videoSource } = useMedia();

  const [condition, setCondition] = useState("");
  const [duration, setDuration] = useState(60);
  const [interval, setInterval_] = useState(5);
  const [isRunning, setIsRunning] = useState(false);
  const [results, setResults] = useState([]);
  const [elapsed, setElapsed] = useState(0);
  const [detectedCount, setDetectedCount] = useState(0);
  const [currentStatus, setCurrentStatus] = useState("");

  const cancelledRef = useRef(false);
  const resultsRef = useRef([]);
  const scrollRef = useRef(null);

  // Auto-scroll results
  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [results]);

  const runDetection = useCallback(async () => {
    if (!condition.trim() || videoSource === "blank") return;

    setIsRunning(true);
    setResults([]);
    setDetectedCount(0);
    setElapsed(0);
    setCurrentStatus("Starting...");
    cancelledRef.current = false;
    resultsRef.current = [];

    const startTime = Date.now();
    const durationMs = duration * 1000;
    const intervalMs = Math.max(interval, 3) * 1000;
    let iterationCount = 0;

    while (!cancelledRef.current) {
      const loopStart = Date.now();
      const elapsedMs = loopStart - startTime;

      // Check if we exceeded duration
      if (elapsedMs >= durationMs) break;

      const elapsedSec = (elapsedMs / 1000).toFixed(1);
      setElapsed(parseFloat(elapsedSec));
      iterationCount++;

      // Step 1: Capture frame
      setCurrentStatus(`Capturing frame #${iterationCount}...`);
      let frame = null;
      for (let retry = 0; retry < 3 && !frame; retry++) {
        frame = await captureFrameAsync();
        if (!frame && retry < 2) await sleep(300);
      }

      if (!frame) {
        const result = {
          id: `det-${Date.now()}`,
          time: elapsedSec,
          detected: false,
          description: "Frame capture failed",
          thumbnail: null,
        };
        resultsRef.current = [...resultsRef.current, result];
        setResults([...resultsRef.current]);
        // Still continue the loop
        await sleep(intervalMs);
        continue;
      }

      if (cancelledRef.current) break;

      // Step 2: Create thumbnail
      const thumbnail = await createThumbnail(frame);

      // Step 3: Analyze with model
      setCurrentStatus(`Analyzing frame #${iterationCount}...`);
      try {
        const analysis = await analyzeFrame(frame, condition);

        if (cancelledRef.current) break;

        const result = {
          id: `det-${Date.now()}`,
          time: elapsedSec,
          detected: analysis.detected,
          description: analysis.description,
          thumbnail,
        };

        resultsRef.current = [...resultsRef.current, result];
        setResults([...resultsRef.current]);
        if (analysis.detected) setDetectedCount((c) => c + 1);
      } catch (err) {
        if (cancelledRef.current) break;

        const result = {
          id: `det-${Date.now()}`,
          time: elapsedSec,
          detected: false,
          description: `Error: ${err.message}`,
          thumbnail,
        };
        resultsRef.current = [...resultsRef.current, result];
        setResults([...resultsRef.current]);
      }

      if (cancelledRef.current) break;

      // Step 4: Wait for next interval
      const analysisTime = Date.now() - loopStart;
      const waitTime = Math.max(1000, intervalMs - analysisTime);

      setCurrentStatus(`Next scan in ${Math.ceil(waitTime / 1000)}s...`);

      // Wait in small chunks so we can check cancelled
      const waitEnd = Date.now() + waitTime;
      while (Date.now() < waitEnd && !cancelledRef.current) {
        await sleep(Math.min(500, waitEnd - Date.now()));
      }
    }

    setCurrentStatus(cancelledRef.current ? "Stopped" : "Completed");
    setIsRunning(false);
  }, [condition, duration, interval, videoSource, captureFrameAsync, analyzeFrame]);

  const stopDetection = useCallback(() => {
    cancelledRef.current = true;
    setCurrentStatus("Stopping...");
  }, []);

  const resetPanel = useCallback(() => {
    setResults([]);
    setElapsed(0);
    setDetectedCount(0);
    setCurrentStatus("");
  }, []);

  const isWebcamOrVideo = videoSource === "webcam" || videoSource === "file";

  return (
    <div className="fixed inset-x-0 top-0 bottom-0 z-30 flex items-start justify-center pt-16 px-4">
      <div className="frosted flex max-h-[80vh] w-full max-w-lg flex-col rounded-2xl shadow-xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-dm-outline px-4 py-3">
          <div className="flex items-center gap-2">
            <ScanSearch className="size-5 text-dm-blue" />
            <h2 className="text-sm font-semibold text-dm-text">Detection Mode</h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={isRunning}
            className="text-dm-text-secondary hover:text-dm-text disabled:opacity-40"
          >
            <X className="size-5" />
          </button>
        </div>

        {/* Settings (shown when not running and no results) */}
        {!isRunning && results.length === 0 && (
          <div className="flex flex-col gap-4 p-4">
            {!isWebcamOrVideo && (
              <p className="text-xs text-dm-red">Camera or video must be active for detection mode.</p>
            )}

            <div>
              <label className="mb-1.5 block text-xs font-medium text-dm-text-secondary">
                Detection Condition
              </label>
              <input
                type="text"
                value={condition}
                onChange={(e) => setCondition(e.target.value)}
                placeholder="e.g., A person appears in the frame"
                className="w-full rounded-xl border border-dm-outline bg-dm-surface-high px-3 py-2 text-sm text-dm-text placeholder-dm-text-secondary/50 outline-none focus:border-dm-blue"
              />
            </div>

            <div className="flex gap-4">
              <div className="flex-1">
                <label className="mb-1.5 block text-xs font-medium text-dm-text-secondary">
                  Duration (sec)
                </label>
                <input
                  type="number"
                  value={duration}
                  onChange={(e) => setDuration(Math.min(300, Math.max(10, Number(e.target.value))))}
                  min={10}
                  max={300}
                  className="w-full rounded-xl border border-dm-outline bg-dm-surface-high px-3 py-2 text-sm text-dm-text outline-none focus:border-dm-blue"
                />
              </div>
              <div className="flex-1">
                <label className="mb-1.5 block text-xs font-medium text-dm-text-secondary">
                  Interval (sec, min 3)
                </label>
                <input
                  type="number"
                  value={interval}
                  onChange={(e) => setInterval_(Math.min(60, Math.max(3, Number(e.target.value))))}
                  min={3}
                  max={60}
                  className="w-full rounded-xl border border-dm-outline bg-dm-surface-high px-3 py-2 text-sm text-dm-text outline-none focus:border-dm-blue"
                />
              </div>
            </div>

            <button
              type="button"
              onClick={runDetection}
              disabled={!condition.trim() || !isWebcamOrVideo}
              className="flex items-center justify-center gap-2 rounded-xl bg-dm-blue px-4 py-2.5 text-sm font-medium text-white transition-all hover:opacity-90 disabled:opacity-40"
            >
              <Play className="size-4" />
              Start Detection
            </button>
          </div>
        )}

        {/* Running / Results */}
        {(isRunning || results.length > 0) && (
          <div className="flex flex-col gap-3 p-4">
            {/* Status bar */}
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3 text-xs text-dm-text-secondary">
                {isRunning && (
                  <span className="flex items-center gap-1.5">
                    <span className="inline-block size-2 animate-pulse rounded-full bg-dm-red" />
                    Running
                  </span>
                )}
                <span className="font-mono">{elapsed}s / {duration}s</span>
                <span className="text-dm-green font-medium">{detectedCount} detected</span>
              </div>

              {isRunning ? (
                <button
                  type="button"
                  onClick={stopDetection}
                  className="flex items-center gap-1.5 rounded-lg bg-dm-red px-3 py-1 text-xs font-medium text-white hover:opacity-90"
                >
                  <Square className="size-3" />
                  Stop
                </button>
              ) : (
                <button
                  type="button"
                  onClick={resetPanel}
                  className="flex items-center gap-1.5 text-xs text-dm-text-secondary hover:text-dm-text"
                >
                  <RotateCcw className="size-3" />
                  New Detection
                </button>
              )}
            </div>

            {/* Progress bar */}
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-dm-surface-high">
              <div
                className="h-full rounded-full bg-dm-blue transition-all duration-300"
                style={{ width: `${Math.min(100, (elapsed / duration) * 100)}%` }}
              />
            </div>

            {/* Current status */}
            {currentStatus && (
              <div className="text-xs text-dm-text-secondary italic">{currentStatus}</div>
            )}

            {/* Condition reminder */}
            <div className="rounded-lg bg-dm-surface-high/60 px-3 py-1.5 text-xs text-dm-text-secondary">
              Condition: <span className="font-medium text-dm-text">{condition}</span>
            </div>

            {/* Results timeline */}
            <div
              ref={scrollRef}
              className="chat-scroll flex max-h-[40vh] flex-col gap-2 overflow-y-auto"
            >
              {results.map((r) => (
                <DetectionResult key={r.id} result={r} />
              ))}
              {isRunning && results.length === 0 && (
                <div className="py-4 text-center text-xs text-dm-text-secondary">
                  Waiting for first capture...
                </div>
              )}
            </div>

            {/* Completion message */}
            {!isRunning && results.length > 0 && (
              <div className="rounded-xl bg-dm-surface-high px-3 py-2 text-center text-xs text-dm-text-secondary">
                Detection {cancelledRef.current ? "stopped" : "completed"} — {results.length} captures, {detectedCount} matches
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
