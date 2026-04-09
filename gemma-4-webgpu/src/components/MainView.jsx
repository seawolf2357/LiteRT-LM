import { useState, useRef, useCallback } from "react";
import { Video, FolderOpen, WifiOff } from "lucide-react";
import { useMedia } from "../contexts/MediaContext";
import ScanningOverlay from "./ScanningOverlay";
import ChatOverlay from "./ChatOverlay";

export default function MainView() {
  const { videoRef, canvasRef, videoSource, startWebcam, loadVideoFile } = useMedia();

  const [isScanning, setIsScanning] = useState(false);
  const [scanFrame, setScanFrame] = useState(null);
  const [scanCompleteFrame, setScanCompleteFrame] = useState(null);
  const [cameraError, setCameraError] = useState(null);
  const fileInputRef = useRef(null);

  const handleScanStart = useCallback((dataUrl) => {
    setScanFrame(dataUrl);
    setIsScanning(true);
  }, []);

  const handleScanComplete = useCallback(() => {
    setIsScanning(false);
    setScanCompleteFrame(scanFrame);
  }, [scanFrame]);

  const handleScanConsumed = useCallback(() => {
    setScanCompleteFrame(null);
    setScanFrame(null);
  }, []);

  return (
    <div className="fixed inset-0 animate-fade-in-up">
      {/* Video element */}
      <video
        ref={videoRef}
        autoPlay
        muted
        playsInline
        className={`absolute inset-0 h-full w-full object-cover ${
          videoSource === "webcam" ? "-scale-x-100" : ""
        }`}
      />
      <canvas ref={canvasRef} className="hidden" />

      {/* Hidden file input */}
      <input
        ref={fileInputRef}
        type="file"
        accept="video/*"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) {
            loadVideoFile(file);
            setCameraError(null);
          }
          e.target.value = "";
        }}
        className="hidden"
      />

      {/* Top gradient */}
      <div className="pointer-events-none absolute inset-x-0 top-0 h-32 bg-gradient-to-b from-black/50 to-transparent" />
      {/* Bottom gradient */}
      <div className="pointer-events-none absolute inset-x-0 bottom-0 h-64 bg-gradient-to-t from-black/70 to-transparent" />

      {/* Source selection (shown when no video source) */}
      {!videoSource && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-6 bg-dm-bg">
          {cameraError && (
            <p className="text-sm text-dm-text-secondary">{cameraError}</p>
          )}
          <div className="flex gap-4">
            <button
              type="button"
              onClick={() => {
                startWebcam().catch(() => setCameraError("Camera access denied."));
              }}
              className="frosted flex w-44 flex-col items-center gap-3 rounded-2xl py-6 text-dm-text transition-colors hover:bg-dm-surface-higher"
            >
              <Video className="size-8" />
              <span className="text-base font-medium">Start Webcam</span>
            </button>
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              className="frosted flex w-44 flex-col items-center gap-3 rounded-2xl py-6 text-dm-text transition-colors hover:bg-dm-surface-higher"
            >
              <FolderOpen className="size-8" />
              <span className="text-base font-medium">Select Video</span>
            </button>
          </div>
          <p className="text-xs text-dm-text-secondary">
            Everything runs locally — no data leaves your device
          </p>
        </div>
      )}

      {/* Header */}
      <header className="absolute inset-x-0 top-0 z-10 flex items-center justify-between bg-gradient-to-b from-black/60 via-black/30 to-transparent px-5 pt-4 pb-10">
        <h1 className="text-2xl font-bold text-dm-text drop-shadow-lg">
          Gemma 4
        </h1>
        <WifiOff className="size-12 text-white drop-shadow-lg" />
      </header>

      {/* Overlays (only when video source is active) */}
      {videoSource && (
        <>
          {isScanning && scanFrame && (
            <ScanningOverlay
              imageDataUrl={scanFrame}
              onComplete={handleScanComplete}
            />
          )}
          <ChatOverlay
            onScanStart={handleScanStart}
            isScanning={isScanning}
            scanCompleteFrame={scanCompleteFrame}
            onScanConsumed={handleScanConsumed}
          />
        </>
      )}
    </div>
  );
}
