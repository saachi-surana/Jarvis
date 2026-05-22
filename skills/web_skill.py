import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import OLLAMA_MODEL, OLLAMA_URL

import ollama
from ddgs import DDGS


def execute(params: dict) -> str:
    query = str(params.get("query", "")).strip()
    if not query:
        return "No search query provided."

    # Fetch top 3 results from DuckDuckGo
    try:
        with DDGS() as ddgs:
            raw_results = list(ddgs.text(query, max_results=3))
    except Exception as e:
        return f"Search failed: {e}"

    if not raw_results:
        return f"No results found for '{query}'."

    # Build a compact results block for the summarisation prompt
    results_text = "\n\n".join(
        f"Title: {r.get('title', 'N/A')}\nSnippet: {r.get('body', 'N/A')}"
        for r in raw_results
    )

    prompt = (
        f"Summarize these search results for the query '{query}' in 2-3 sentences:\n\n"
        f"{results_text}"
    )

    try:
        client = ollama.Client(host=OLLAMA_URL)
        response = client.chat(
            model=OLLAMA_MODEL,
            messages=[{"role": "user", "content": prompt}],
        )
        return response["message"]["content"].strip()
    except Exception as e:
        # Ollama unavailable — fall back to returning the raw snippets
        snippets = " | ".join(
            r.get("body", "")[:120] for r in raw_results if r.get("body")
        )
        return f"(Summary unavailable — {e}.) Top results: {snippets}"
