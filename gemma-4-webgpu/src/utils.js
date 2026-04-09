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
export function generateId() {
  return crypto.randomUUID?.() ?? `msg-${Date.now()}-${Math.random()}`;
}
