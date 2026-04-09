import { useEffect } from "react";
import { LoaderCircle } from "lucide-react";
import { SCAN_TIMEOUT } from "../constants";

export default function ScanningOverlay({ imageDataUrl, onComplete }) {
  useEffect(() => {
    const timer = setTimeout(onComplete, SCAN_TIMEOUT);
    return () => clearTimeout(timer);
  }, [onComplete]);

  return (
    <div className="fixed inset-0 z-30 flex flex-col items-center justify-center bg-dm-bg/60 backdrop-blur-sm animate-fade-in-up">
      <div className="relative overflow-hidden rounded-2xl border border-dm-outline shadow-2xl shadow-dm-blue/20">
        <img
          src={imageDataUrl}
          alt="Captured frame"
          className="block h-auto max-h-[300px] w-auto max-w-[400px] object-contain"
        />
        {/* Scan line */}
        <div className="absolute left-0 right-0 h-0.5 bg-gradient-to-r from-transparent via-dm-blue to-transparent animate-scan-line" />
        {/* Corner brackets */}
        <div className="absolute top-2 left-2 size-5 border-t-2 border-l-2 border-dm-blue animate-pulse" />
        <div className="absolute top-2 right-2 size-5 border-t-2 border-r-2 border-dm-blue animate-pulse" />
        <div className="absolute bottom-2 left-2 size-5 border-b-2 border-l-2 border-dm-blue animate-pulse" />
        <div className="absolute bottom-2 right-2 size-5 border-b-2 border-r-2 border-dm-blue animate-pulse" />
      </div>
      <div className="mt-5 flex items-center gap-2 text-sm text-dm-text/80">
        <LoaderCircle className="size-4 animate-spin" />
        Analyzing...
      </div>
    </div>
  );
}
