import requests
from openai import OpenAI
import os

NEWS_API_KEY    = os.getenv("NEWS_API_KEY")
OPENAI_API_KEY  = os.getenv("OPENAI_API_KEY")
TELEGRAM_TOKEN  = os.getenv("TELEGRAM_TOKEN")
CHAT_ID         = os.getenv("CHAT_ID")

client = OpenAI(api_key=OPENAI_API_KEY)

# -------- FETCH NEWS --------

def get_news(query: str, country: str = None, size: int = 15) -> list[dict]:
    """
    Fetch raw articles from newsdata.io.
    Returns a list of dicts with title + link so the caller can format/filter.
    """
    url = (
        f"https://newsdata.io/api/1/news"
        f"?apikey={NEWS_API_KEY}"
        f"&q={requests.utils.quote(query)}"
        f"&language=en"
        f"&size={size}"
    )
    if country:
        url += f"&country={country}"

    try:
        res = requests.get(url, timeout=10).json()
    except Exception as e:
        print(f"[ERROR] News fetch failed for query '{query}': {e}")
        return []

    articles = res.get("results", [])
    return [
        {
            "title": a.get("title", "No title").replace("(", "").replace(")", ""),
            "link":  a.get("link", ""),
            "description": a.get("description") or "",
            "pubDate": a.get("pubDate") or "",
        }
        for a in articles
        if a.get("title") and a.get("link")
    ]


def format_articles(articles: list[dict]) -> str:
    lines = []
    for a in articles:
        date_tag = f" [{a['pubDate'][:10]}]" if a["pubDate"] else ""
        lines.append(f"- [{a['title']}{date_tag}]({a['link']})")
        if a["description"]:
            # Short blurb helps GPT filter signal vs noise
            snippet = a["description"][:120].strip()
            lines.append(f"  > {snippet}")
    return "\n".join(lines)


def get_k8s_news() -> str:
    """
    Use two focused queries and merge results to improve recall.
    Query 1 — core Kubernetes / CNCF releases & security
    Query 2 — broader cloud-native ecosystem (Helm, Argo, Istio, etc.)
    """
    query1 = '"kubernetes" (release OR security OR vulnerability OR update OR CNCF)'
    query2 = '"cloud native" (Helm OR Argo OR Istio OR Cilium OR OpenTelemetry OR Flux)'

    articles1 = get_news(query1, size=10)
    articles2 = get_news(query2, size=8)

    # Deduplicate by link
    seen = set()
    merged = []
    for a in articles1 + articles2:
        if a["link"] not in seen:
            seen.add(a["link"])
            merged.append(a)

    return format_articles(merged[:18])  # Send up to 18 for GPT to filter


def get_stock_news() -> str:
    query = '"Nifty" OR "Sensex" OR "NSE" OR "BSE" (stocks OR market OR rally OR crash OR earnings)'
    articles = get_news(query, country="in", size=12)
    return format_articles(articles)


# -------- GPT PROCESSING --------

def summarize(k8s_news: str, stock_news: str) -> str:
    prompt = f"""
You are a highly selective expert news analyst creating a daily briefing for a DevOps engineer.

════════════════════════════════
SECTION 1 — Kubernetes & Cloud Native
════════════════════════════════
INPUT:
{k8s_news}

RULES:
- INCLUDE: official Kubernetes releases, CVEs/security patches, CNCF project milestones,
  ecosystem tools (Helm, Argo, Istio, Cilium, Flux, OpenTelemetry, Karpenter).
- EXCLUDE: generic "how to use Kubernetes" tutorials, cloud provider marketing,
  opinion pieces without substance, duplicates.
- Pick the TOP 4–5 highest-signal items only.

════════════════════════════════
SECTION 2 — Indian Stock Market
════════════════════════════════
INPUT:
{stock_news}

RULES:
- Focus on Nifty/Sensex movement, sector rotation, FII/DII flows, major earnings.
- 2-line market summary max.
- Sentiment: Bullish / Bearish / Neutral with one-line rationale.
- 2–3 stocks to watch with a one-line reason each.

════════════════════════════════
OUTPUT FORMAT (Telegram Markdown):
════════════════════════════════

🚀 *Kubernetes & Cloud Native*
• [Title](url) — one-line takeaway
• ...

📈 *Indian Stock Market*
*Summary:* ...
*Sentiment:* Bullish/Bearish/Neutral — reason
*Stocks to Watch:*
• TICKER — reason
• ...

IMPORTANT:
- Use Telegram MarkdownV1 (single asterisks for bold, links as [text](url)).
- Be concise; remove all noise.
- Never invent links or tickers.
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",   # ← fixed: was "gpt-5-mini" (invalid)
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,       # Low temperature = more factual, less hallucination
    )
    return response.choices[0].message.content


# -------- SEND TELEGRAM --------

def send_telegram(message: str) -> None:
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id":    CHAT_ID,
        "text":       message,
        "parse_mode": "Markdown",          # ← fixed: links now clickable
        "disable_web_page_preview": True,  # cleaner Telegram rendering
    }
    try:
        resp = requests.post(url, data=payload, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        print(f"[ERROR] Telegram send failed: {e}")
        # Fallback: send as plain text without Markdown if formatting broke it
        payload["parse_mode"] = ""
        requests.post(url, data=payload, timeout=10)


# -------- MAIN --------

if __name__ == "__main__":
    print("📰 Fetching Kubernetes news...")
    k8s_news = get_k8s_news()

    print("📊 Fetching stock news...")
    stock_news = get_stock_news()

    print("🤖 Summarising with GPT...")
    final_msg = summarize(k8s_news, stock_news)

    print("📬 Sending to Telegram...")
    send_telegram(final_msg)

    print("✅ Sent to Telegram!")
