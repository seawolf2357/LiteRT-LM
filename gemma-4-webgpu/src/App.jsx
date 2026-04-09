import { useState } from "react";
import { ModelProvider } from "./contexts/ModelContext";
import { MediaProvider } from "./contexts/MediaContext";
import LandingPage from "./components/LandingPage";
import LoadingPage from "./components/LoadingPage";
import MainView from "./components/MainView";

function AppContent() {
  const [page, setPage] = useState("landing"); // "landing" | "loading" | "main"

  return (
    <>
      {page === "landing" && <LandingPage onStart={() => setPage("loading")} />}
      {page === "loading" && <LoadingPage onReady={() => setPage("main")} />}
      {page === "main" && <MainView />}
    </>
  );
}

export default function App() {
  return (
    <ModelProvider>
      <MediaProvider>
        <AppContent />
      </MediaProvider>
    </ModelProvider>
  );
}
