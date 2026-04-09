import {
  createContext,
  useContext,
  useState,
  useRef,
  useCallback,
  useEffect,
} from "react";

const MediaContext = createContext(null);

export function useMedia() {
  const ctx = useContext(MediaContext);
  if (!ctx) throw new Error("useMedia must be used within a MediaProvider.");
  return ctx;
}

export function MediaProvider({ children }) {
  const videoRef = useRef(null);
  const canvasRef = useRef(null);
  const recorderRef = useRef(null);
  const audioChunksRef = useRef([]);
  const streamRef = useRef(null);
  const objectUrlRef = useRef(null);

  const [videoSource, setVideoSource] = useState(null); // "webcam" | "file" | null
  const [isVideoReady, setIsVideoReady] = useState(false);
  const [isRecording, setIsRecording] = useState(false);

  // Cleanup on unmount
  useEffect(
    () => () => {
      streamRef.current?.getTracks().forEach((t) => t.stop());
      if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
    },
    [],
  );

  const startWebcam = useCallback(async () => {
    // Stop existing tracks
    streamRef.current?.getTracks().forEach((t) => t.stop());
    if (objectUrlRef.current) {
      URL.revokeObjectURL(objectUrlRef.current);
      objectUrlRef.current = null;
    }

    const stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: "user", width: { ideal: 1280 }, height: { ideal: 720 } },
      audio: false,
    });

    streamRef.current = stream;
    if (videoRef.current) {
      videoRef.current.srcObject = stream;
      videoRef.current.onloadedmetadata = () => {
        setIsVideoReady(true);
        videoRef.current?.play().catch(() => {});
      };
    }
    setVideoSource("webcam");
  }, []);

  const loadVideoFile = useCallback((file) => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);

    const url = URL.createObjectURL(file);
    objectUrlRef.current = url;

    if (videoRef.current) {
      videoRef.current.srcObject = null;
      videoRef.current.src = url;
      videoRef.current.loop = true;
      videoRef.current.onloadedmetadata = () => {
        setIsVideoReady(true);
        videoRef.current?.play().catch(() => {});
      };
    }
    setVideoSource("file");
  }, []);

  const captureFrame = useCallback(() => {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (
      !video ||
      !canvas ||
      video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA ||
      video.videoWidth === 0
    ) {
      return null;
    }

    const scale = Math.min(1, 960 / Math.max(video.videoWidth, video.videoHeight));
    const width = Math.round(video.videoWidth * scale);
    const height = Math.round(video.videoHeight * scale);
    canvas.width = width;
    canvas.height = height;

    const ctx = canvas.getContext("2d");
    if (!ctx) return null;
    ctx.drawImage(video, 0, 0, width, height);
    return canvas.toDataURL("image/jpeg", 0.8);
  }, []);

  const startRecording = useCallback(async () => {
    audioChunksRef.current = [];
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const recorder = new MediaRecorder(stream);
    recorderRef.current = recorder;
    recorder.ondataavailable = (e) => {
      if (e.data.size > 0) audioChunksRef.current.push(e.data);
    };
    recorder.start();
    setIsRecording(true);
  }, []);

  const stopRecording = useCallback(
    () =>
      new Promise((resolve) => {
        const recorder = recorderRef.current;
        if (!recorder || recorder.state === "inactive") {
          setIsRecording(false);
          resolve(null);
          return;
        }

        recorder.onstop = async () => {
          recorder.stream.getTracks().forEach((t) => t.stop());
          setIsRecording(false);
          const blob = new Blob(audioChunksRef.current, { type: "audio/webm" });
          try {
            const buffer = await blob.arrayBuffer();
            const audioCtx = new AudioContext({ sampleRate: 16000 });
            const decoded = await audioCtx.decodeAudioData(buffer);
            await audioCtx.close();
            resolve(decoded.getChannelData(0));
          } catch {
            resolve(null);
          }
        };
        recorder.stop();
      }),
    [],
  );

  return (
    <MediaContext.Provider
      value={{
        videoRef,
        canvasRef,
        videoSource,
        isVideoReady,
        isRecording,
        startWebcam,
        loadVideoFile,
        captureFrame,
        startRecording,
        stopRecording,
      }}
    >
      {children}
    </MediaContext.Provider>
  );
}
