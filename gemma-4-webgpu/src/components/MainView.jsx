import { useState, useRef, useCallback } from "react";
import { Video, FolderOpen, MessageSquare, Shield, ScanSearch, Settings } from "lucide-react";
import { useMedia } from "../contexts/MediaContext";
import ScanningOverlay from "./ScanningOverlay";
import ChatOverlay from "./ChatOverlay";
import DetectionPanel from "./DetectionPanel";
import SettingsPanel from "./SettingsPanel";

export default function MainView() {
  const { videoRef, canvasRef, videoSource, startWebcam, loadVideoFile, setBlankMode } = useMedia();

  const [isScanning, setIsScanning] = useState(false);
  const [scanFrame, setScanFrame] = useState(null);
  const [scanCompleteFrame, setScanCompleteFrame] = useState(null);
  const [cameraError, setCameraError] = useState(null);
  const [showDetection, setShowDetection] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
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

  const isBlank = videoSource === "blank";
  const isWebcamOrVideo = videoSource === "webcam" || videoSource === "file";

  return (
    <div className="fixed inset-0 animate-fade-in-up">
      {/* Video element (hidden in blank mode) */}
      <video
        ref={videoRef}
        autoPlay
        muted
        playsInline
        className={`absolute inset-0 h-full w-full object-cover ${
          videoSource === "webcam" ? "-scale-x-100" : ""
        } ${isBlank ? "hidden" : ""}`}
      />
      <canvas ref={canvasRef} className="hidden" />

      {/* Blank background */}
      {isBlank && <div className="absolute inset-0 bg-dm-bg" />}

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

      {/* Top/bottom gradients (only for camera/video modes) */}
      {!isBlank && videoSource && (
        <>
          <div className="pointer-events-none absolute inset-x-0 top-0 h-32 bg-gradient-to-b from-dm-bg/50 to-transparent" />
          <div className="pointer-events-none absolute inset-x-0 bottom-0 h-64 bg-gradient-to-t from-dm-bg/70 to-transparent" />
        </>
      )}

      {/* Source selection (shown when no video source) */}
      {!videoSource && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-6 bg-dm-bg">
          {cameraError && (
            <p className="text-sm text-dm-text-secondary">{cameraError}</p>
          )}
          <div className="flex gap-4">
            <button
              type="button"
              onClick={() => setBlankMode()}
              className="frosted flex w-44 flex-col items-center gap-3 rounded-2xl py-6 text-dm-text transition-colors hover:bg-dm-surface-higher"
            >
              <MessageSquare className="size-8" />
              <span className="text-base font-medium">Chat Only</span>
            </button>
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
      {videoSource && (
        <header className="absolute inset-x-0 top-0 z-10 flex items-center justify-between px-5 pt-4 pb-10">
          <h1 className="text-2xl font-bold text-dm-text">VIDRAFT</h1>
          <div className="flex items-center gap-2">
            {/* Detection mode button (only when camera/video active) */}
            {isWebcamOrVideo && (
              <button
                type="button"
                onClick={() => setShowDetection(true)}
                title="Detection Mode"
                className="flex items-center gap-1.5 rounded-full bg-dm-surface-high px-3 py-1.5 text-dm-text-secondary transition-colors hover:text-dm-text"
              >
                <ScanSearch className="size-4" />
                <span className="text-xs font-medium">Detect</span>
              </button>
            )}
            {/* Settings button */}
            <button
              type="button"
              onClick={() => setShowSettings(true)}
              title="Settings"
              className="flex items-center justify-center rounded-full bg-dm-surface-high p-2 text-dm-text-secondary transition-colors hover:text-dm-text"
            >
              <Settings className="size-4" />
            </button>
            {/* Local badge */}
            <div className="flex items-center gap-1.5 rounded-full bg-dm-surface-high px-3 py-1.5">
              <Shield className="size-4 text-dm-green" />
              <span className="text-xs font-medium text-dm-text-secondary">Local</span>
            </div>
          </div>
        </header>
      )}

      {/* Overlays */}
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

      {/* Detection Panel */}
      {showDetection && (
        <DetectionPanel onClose={() => setShowDetection(false)} />
      )}

      {/* Settings Panel */}
      {showSettings && (
        <SettingsPanel onClose={() => setShowSettings(false)} />
      )}
    </div>
  );
}
