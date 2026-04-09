import { SYSTEM_PROMPT } from "./constants";

/**
 * Parse tool calls from Gemma's raw output format.
 * Format: <|tool_call>call:functionName{key:<|"|>value<|"|>}<tool_call|>
 */
export function parseToolCalls(text) {
  const calls = [];
  const pattern = /<\|tool_call>call:(\w+)\{(.*?)\}<tool_call\|>/gs;
  let match;
  while ((match = pattern.exec(text)) !== null) {
    const name = match[1];
    const argsStr = match[2];
    const args = {};
    const argPattern = /(\w+):<\|"\|>(.*?)<\|"\|>/gs;
    let argMatch;
    while ((argMatch = argPattern.exec(argsStr)) !== null) {
      args[argMatch[1]] = argMatch[2];
    }
    calls.push({ function: { name, arguments: args } });
  }
  return calls;
}

/**
 * Build chat messages array with system prompt prepended.
 */
export function buildChatMessages(messages) {
  const result = [{ role: "system", content: SYSTEM_PROMPT }];
  for (const msg of messages) {
    if (msg.role === "user") {
      result.push({ role: "user", content: msg.content });
    } else {
      result.push({ role: "assistant", content: msg.content });
    }
  }
  return result;
}

/**
 * Decode a data URL to an HTMLCanvasElement for vision input.
 */
export async function decodeImage(dataUrl) {
  const img = new Image();
  img.src = dataUrl;
  await img.decode();
  if (img.naturalWidth === 0) return null;
  const canvas = document.createElement("canvas");
  canvas.width = img.naturalWidth;
  canvas.height = img.naturalHeight;
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;
  ctx.drawImage(img, 0, 0);
  return canvas;
}

/**
 * Find the matching closing brace for a LaTeX command argument.
 */
function findClosingBrace(text, start) {
  let depth = 1;
  let pos = start;
  while (pos < text.length && depth > 0) {
    if (text[pos] === "{") depth++;
    else if (text[pos] === "}") depth--;
    pos++;
  }
  return pos;
}

const LATEX_COMMANDS = [
  { prefix: "\\boxed{", args: 1 },
  { prefix: "\\text{", args: 1 },
  { prefix: "\\textbf{", args: 1 },
  { prefix: "\\mathbf{", args: 1 },
  { prefix: "\\mathrm{", args: 1 },
  { prefix: "\\frac{", args: 2 },
];

/**
 * Wrap bare LaTeX commands (not inside $ delimiters) in inline math markers.
 */
function wrapBareLatex(text) {
  let result = "";
  let i = 0;
  let delimiter = null;
  while (i < text.length) {
    const cmd = delimiter
      ? undefined
      : LATEX_COMMANDS.find((c) => text.startsWith(c.prefix, i));
    if (cmd) {
      let end = findClosingBrace(text, i + cmd.prefix.length);
      for (let a = 1; a < cmd.args; a++) {
        if (text[end] === "{") end = findClosingBrace(text, end + 1);
      }
      const slice = text.slice(i, end);
      result += "$" + slice + "$";
      i = end;
    } else if (text[i] === "$") {
      const marker = text[i + 1] === "$" ? "$$" : "$";
      if (delimiter === marker) delimiter = null;
      else delimiter ||= marker;
      result += marker;
      i += marker.length;
    } else {
      result += text[i];
      i++;
    }
  }
  return result;
}

/**
 * Preprocess math notation in text for remark-math compatibility.
 * Converts \[...\] and \(...\) to $$ and $ delimiters, then wraps bare LaTeX.
 */
export function preprocessMath(text) {
  return wrapBareLatex(
    text
      .replace(/(?<!\\)\\\[/g, "$$")
      .replace(/\\\]/g, "$$")
      .replace(/(?<!\\)\\\(/g, "$")
      .replace(/\\\)/g, "$"),
  );
}

/** Max characters to extract from uploaded files (model context limit) */
const MAX_FILE_CHARS = 8000;

/** Supported text file extensions */
const TEXT_EXTENSIONS = new Set([
  "txt", "csv", "json", "md", "xml", "html", "css", "js", "jsx", "ts", "tsx",
  "py", "java", "c", "cpp", "h", "rs", "go", "yaml", "yml", "toml", "ini",
  "log", "sql", "sh", "bat", "env", "conf", "cfg",
]);

/** Check if a file is a text-readable type */
function isTextFile(file) {
  const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
  return TEXT_EXTENSIONS.has(ext) || file.type.startsWith("text/");
}

/** Check if a file is an image */
function isImageFile(file) {
  return file.type.startsWith("image/");
}

/** Check if a file is a PDF */
function isPdfFile(file) {
  return file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
}

/**
 * Read a text file and return its content (truncated to MAX_FILE_CHARS).
 */
function readTextFile(file) {
  return new Promise((resolve) => {
    const reader = new FileReader();
    reader.onload = () => {
      let text = reader.result ?? "";
      if (text.length > MAX_FILE_CHARS) {
        text = text.slice(0, MAX_FILE_CHARS) + "\n\n... (truncated)";
      }
      resolve(text);
    };
    reader.onerror = () => resolve(null);
    reader.readAsText(file);
  });
}

/**
 * Read an image file and return a data URL.
 */
function readImageFile(file) {
  return new Promise((resolve) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => resolve(null);
    reader.readAsDataURL(file);
  });
}

/** Load pdf.js library from CDN */
async function loadPdfJs() {
  if (window.pdfjsLib) return window.pdfjsLib;

  // Use worker-disabled mode to avoid CORS issues with worker file
  await new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js";
    script.onload = resolve;
    script.onerror = () => reject(new Error("Failed to load pdf.js from CDN"));
    document.head.appendChild(script);
  });

  if (!window.pdfjsLib) throw new Error("pdf.js not available after loading");

  // Disable worker to avoid CORS issues in iframe/HF Spaces
  window.pdfjsLib.GlobalWorkerOptions.workerSrc = "";

  return window.pdfjsLib;
}

/**
 * Extract text from a single PDF page, preserving line structure.
 */
function extractPageText(content) {
  if (!content.items || content.items.length === 0) return "";

  const lines = [];
  let currentLine = "";
  let lastY = null;

  for (const item of content.items) {
    const text = item.str;
    if (!text) continue;

    // Detect line breaks by Y-position change
    const y = item.transform ? item.transform[5] : null;
    if (lastY !== null && y !== null && Math.abs(y - lastY) > 2) {
      if (currentLine.trim()) lines.push(currentLine.trim());
      currentLine = text;
    } else {
      // Same line — check if we need a space
      if (currentLine && !currentLine.endsWith(" ") && !text.startsWith(" ")) {
        currentLine += item.hasEOL ? "\n" : " ";
      }
      currentLine += text;
    }
    lastY = y;
  }
  if (currentLine.trim()) lines.push(currentLine.trim());

  return lines.join("\n");
}

/**
 * Render a PDF page to an image data URL (for image-based PDFs).
 */
async function renderPageToImage(page, scale = 1.5) {
  const viewport = page.getViewport({ scale });
  const canvas = document.createElement("canvas");
  canvas.width = viewport.width;
  canvas.height = viewport.height;
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;
  await page.render({ canvasContext: ctx, viewport }).promise;
  return canvas.toDataURL("image/jpeg", 0.7);
}

/**
 * Extract text from a PDF. If text extraction yields little content,
 * renders the first page as an image for vision analysis.
 */
async function readPdfFile(file) {
  try {
    const pdfjsLib = await loadPdfJs();

    const arrayBuffer = await file.arrayBuffer();
    const loadingTask = pdfjsLib.getDocument({
      data: new Uint8Array(arrayBuffer),
      useWorkerFetch: false,
      isEvalSupported: false,
      useSystemFonts: true,
    });
    const pdf = await loadingTask.promise;

    const pages = [];
    const maxPages = Math.min(pdf.numPages, 20);
    let totalChars = 0;

    for (let i = 1; i <= maxPages; i++) {
      const page = await pdf.getPage(i);
      const content = await page.getTextContent();
      const text = extractPageText(content);
      totalChars += text.length;
      pages.push({ num: i, text, page });
    }

    // If very little text extracted, this is likely an image-based PDF
    // Render first page as image for vision pipeline
    if (totalChars < 50) {
      const firstPage = await pdf.getPage(1);
      const imageDataUrl = await renderPageToImage(firstPage);
      if (imageDataUrl) {
        return {
          text: null,
          image: imageDataUrl,
          isImagePdf: true,
        };
      }
      return { text: "[This PDF appears to be image-based. Text extraction found no content.]" };
    }

    let result = pages
      .map((p) => `[Page ${p.num}]\n${p.text}`)
      .join("\n\n");

    if (result.length > MAX_FILE_CHARS) {
      result = result.slice(0, MAX_FILE_CHARS) + "\n\n... (truncated)";
    }
    if (pdf.numPages > maxPages) {
      result += `\n\n(Showing ${maxPages} of ${pdf.numPages} pages)`;
    }
    return { text: result };
  } catch (err) {
    console.error("PDF extraction failed:", err);
    // Fallback: try raw text extraction
    try {
      const rawText = await file.text();
      const cleaned = rawText.replace(/[^\x20-\x7E\n\r\t\u00A0-\uFFFF]/g, " ").replace(/\s{3,}/g, " ").trim();
      if (cleaned.length > 100) {
        return { text: cleaned.slice(0, MAX_FILE_CHARS) + "\n\n(Raw extraction - PDF parser failed: " + err.message + ")" };
      }
    } catch {}
    return { text: `[PDF text extraction failed: ${err.message}. The PDF may require a different viewer.]` };
  }
}

/**
 * Process an uploaded file and return { text, image, fileName, fileType }.
 * - Text files → extracted text content
 * - Images → data URL for vision pipeline
 * - PDFs → extracted text via pdf.js
 */
export async function processUploadedFile(file) {
  const fileName = file.name;

  if (isImageFile(file)) {
    const dataUrl = await readImageFile(file);
    return dataUrl ? { image: dataUrl, fileName, fileType: "image" } : null;
  }

  if (isPdfFile(file)) {
    const result = await readPdfFile(file);
    if (result.image) {
      // Image-based PDF: send first page as image to vision pipeline
      return { image: result.image, fileName, fileType: "pdf-image" };
    }
    return { text: result.text || "[Failed to extract PDF content]", fileName, fileType: "pdf" };
  }

  if (isTextFile(file)) {
    const text = await readTextFile(file);
    return text ? { text, fileName, fileType: "text" } : null;
  }

  // Try reading as text anyway
  const text = await readTextFile(file);
  return text ? { text, fileName, fileType: "unknown" } : null;
}

/**
 * Export conversation as Markdown text.
 */
export function exportAsMarkdown(messages) {
  return messages
    .map((m) => {
      const role = m.role === "user" ? "**You**" : "**VIDRAFT**";
      let content = m.content || "";
      if (m.thinking) content = `> *Thinking:* ${m.thinking}\n\n${content}`;
      if (m.image) content = `[Image attached]\n\n${content}`;
      if (m.audio) content = `[Audio attached]\n\n${content}`;
      return `${role}:\n${content}`;
    })
    .join("\n\n---\n\n");
}

/**
 * Export conversation as JSON.
 */
export function exportAsJson(messages) {
  return JSON.stringify(
    messages.map(({ id, role, content, thinking }) => ({ id, role, content, thinking })),
    null,
    2,
  );
}

/**
 * Compute amplitude bars from audio data for visualization.
 */
export function computeAudioBars(data, numBars) {
  const chunkSize = Math.floor(data.length / numBars);
  const bars = [];
  for (let i = 0; i < numBars; i++) {
    let sum = 0;
    for (let j = 0; j < chunkSize; j++) {
      sum += Math.abs(data[i * chunkSize + j]);
    }
    bars.push(sum / chunkSize);
  }
  const max = Math.max(...bars, 0.001);
  return bars.map((b) => b / max);
}

/**
 * Generate a unique message ID.
 */
/**
 * Perform a web search using Brave Search API.
 * Tries direct request first, falls back to CORS proxy if blocked.
 * Returns formatted text with top results.
 */
export async function braveSearch(query, apiKey) {
  const baseUrl = `https://api.search.brave.com/res/v1/web/search?q=${encodeURIComponent(query)}&count=5`;
  const headers = {
    "X-Subscription-Token": apiKey,
    "Accept": "application/json",
  };

  let res;
  try {
    // Try direct request first
    res = await fetch(baseUrl, { headers });
  } catch (directErr) {
    // CORS blocked — try via proxy
    console.warn("Brave Search direct failed, trying CORS proxy:", directErr.message);
    try {
      const proxyUrl = `https://api.allorigins.win/raw?url=${encodeURIComponent(baseUrl)}`;
      res = await fetch(proxyUrl, {
        headers: { "X-Subscription-Token": apiKey },
      });
    } catch (proxyErr) {
      throw new Error(`Search failed (CORS blocked). Try a different browser or disable extensions. ${directErr.message}`);
    }
  }

  if (!res.ok) {
    const errText = await res.text().catch(() => "");
    if (res.status === 401 || res.status === 422) {
      throw new Error("Invalid Brave API key. Check Settings.");
    }
    throw new Error(`Brave API error ${res.status}: ${errText.slice(0, 100)}`);
  }

  const data = await res.json();
  const results = data.web?.results || [];

  if (results.length === 0) return "No search results found for: " + query;

  return results
    .slice(0, 5)
    .map((r, i) => `${i + 1}. ${r.title}\n   ${r.description || ""}\n   ${r.url}`)
    .join("\n\n");
}

export function generateId() {
  return crypto.randomUUID?.() ?? `msg-${Date.now()}-${Math.random()}`;
}
