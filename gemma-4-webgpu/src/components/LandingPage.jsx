export default function LandingPage({ onStart }) {
  return (
    <div className="relative flex h-full flex-col items-center justify-center px-6">
      <div
        className="absolute inset-0 bg-cover bg-center bg-no-repeat"
        style={{ backgroundImage: "url(/background.jpg)" }}
      />
      <div className="absolute inset-0 bg-dm-bg/70" />
      <div className="relative z-10 flex flex-col items-center gap-6 text-center">
        <h1 className="text-6xl font-bold tracking-tight text-dm-text animate-title-appear sm:text-7xl animate-glow">
          Gemma 4 WebGPU
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
