import { computeAudioBars } from "../utils";

export default function AudioWaveform({ audio }) {
  return (
    <div className="mb-1.5 flex h-8 items-center gap-[2px]">
      {computeAudioBars(audio, 32).map((amplitude, i) => (
        <div
          key={i}
          className="w-1.5 rounded-full bg-dm-blue/70"
          style={{ height: `${Math.max(amplitude * 100, 10)}%` }}
        />
      ))}
    </div>
  );
}
