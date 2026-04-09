export default function LandingPage({ onStart }) {
  return (
    <div className="relative flex h-full flex-col items-center justify-center px-6 bg-dm-bg">
      <div className="relative z-10 flex flex-col items-center gap-6 text-center">
        <h1 className="text-6xl font-bold tracking-tight text-dm-text animate-title-appear sm:text-7xl animate-glow">
          VIDRAFT
        </h1>
        <p className="max-w-lg text-lg text-dm-text-secondary animate-subtitle-appear">
          Multimodal AI, running locally in your browser with WebGPU
        </p>
        <button
          type="button"
          onClick={onStart}
          className="mt-4 rounded-full bg-dm-text px-8 py-3 text-base font-semibold text-dm-bg transition-all hover:opacity-90 active:scale-[0.98] animate-button-appear"
        >
          Load model
        </button>
      </div>
    </div>
  );
}
