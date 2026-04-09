export default function TypingIndicator() {
  return (
    <div className="flex justify-start">
      <div className="frosted flex items-center gap-1 rounded-2xl px-4 py-3">
        {[0, 1, 2].map((i) => (
          <span
            key={i}
            className="inline-block size-1.5 rounded-full bg-dm-text-secondary animate-typing-dot"
            style={{ animationDelay: `${i * 0.15}s` }}
          />
        ))}
      </div>
    </div>
  );
}
