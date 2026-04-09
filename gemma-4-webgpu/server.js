import express from "express";
import { fileURLToPath } from "url";
import { dirname, join } from "path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const app = express();
const PORT = 7860;

// Serve static files from dist/
app.use(express.static(join(__dirname, "dist")));

// Search proxy API — fetches DuckDuckGo and parses results server-side
app.get("/api/search", async (req, res) => {
  const query = req.query.q;
  if (!query) return res.json({ error: "Missing query parameter ?q=" });

  try {
    const ddgUrl = `https://html.duckduckgo.com/html/?q=${encodeURIComponent(query)}`;
    const response = await fetch(ddgUrl, {
      headers: {
        "User-Agent": "Mozilla/5.0 (compatible; VIDRAFT/1.0)",
      },
    });

    if (!response.ok) throw new Error(`DDG returned ${response.status}`);

    const html = await response.text();

    // Parse results from DDG HTML
    const resultPattern = /class="result__a"[^>]*href="([^"]+)"[^>]*>([\s\S]*?)<\/a>[\s\S]*?class="result__snippet"[^>]*>([\s\S]*?)<\/span>/g;
    const results = [];
    let match;
    while ((match = resultPattern.exec(html)) !== null && results.length < 5) {
      const rawUrl = match[1];
      const title = match[2].replace(/<[^>]+>/g, "").trim();
      const snippet = match[3]
        .replace(/<[^>]+>/g, "")
        .replace(/&quot;/g, '"')
        .replace(/&amp;/g, "&")
        .replace(/&#x27;/g, "'")
        .replace(/&lt;/g, "<")
        .replace(/&gt;/g, ">")
        .trim();

      const urlMatch = rawUrl.match(/uddg=([^&]+)/);
      const url = urlMatch ? decodeURIComponent(urlMatch[1]) : rawUrl;

      if (title) results.push({ title, snippet, url });
    }

    res.json({ results, query });
  } catch (err) {
    console.error("Search proxy error:", err.message);
    res.status(500).json({ error: err.message });
  }
});

// SPA fallback (Express v5 requires named param for wildcard)
app.get("/{*path}", (req, res) => {
  res.sendFile(join(__dirname, "dist", "index.html"));
});

app.listen(PORT, "0.0.0.0", () => {
  console.log(`VIDRAFT server running on port ${PORT}`);
});
