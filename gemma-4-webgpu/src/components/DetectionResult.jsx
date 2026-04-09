import { CheckCircle2, XCircle } from "lucide-react";

export default function DetectionResult({ result }) {
  const { time, detected, description, thumbnail } = result;

  return (
    <div className={`flex gap-3 rounded-xl p-2.5 text-sm ${detected ? "bg-dm-green/10" : "bg-dm-surface-high/60"}`}>
      {/* Thumbnail */}
      {thumbnail && (
        <img
          src={thumbnail}
          alt={`Frame at ${time}s`}
          className="size-14 shrink-0 rounded-lg object-cover"
        />
      )}

      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        {/* Header: time + status */}
        <div className="flex items-center gap-2">
          <span className="text-xs font-mono text-dm-text-secondary">{time}s</span>
          {detected ? (
            <span className="flex items-center gap-1 text-xs font-medium text-dm-green">
              <CheckCircle2 className="size-3.5" />
              DETECTED
            </span>
          ) : (
            <span className="flex items-center gap-1 text-xs text-dm-text-secondary">
              <XCircle className="size-3.5" />
              Not detected
            </span>
          )}
        </div>

        {/* Description */}
        {description && (
          <p className="text-xs leading-relaxed text-dm-text-secondary line-clamp-2">
            {description}
          </p>
        )}
      </div>
    </div>
  );
}
