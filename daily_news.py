import requests
from bs4 import BeautifulSoup
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

    # Log API-level errors (e.g. rate limit, bad key, invalid query param)
    if res.get("status") != "success":
        print(f"[WARN] API error for query '{query}': {res.get('results') or res}")
        return []

    articles = res.get("results", [])
    parsed = []
    for a in articles:
        # Guard: skip anything that isn't a dict (API sometimes returns strings on error)
        if not isinstance(a, dict):
            print(f"[WARN] Unexpected article format (skipping): {a!r}")
            continue
        title = a.get("title") or ""
        link  = a.get("link")  or ""
        if not title or not link:
            continue
        parsed.append({
            "title":       title.replace("(", "").replace(")", ""),
            "link":        link,
            "description": a.get("description") or "",
            "pubDate":     a.get("pubDate")      or "",
        })
    return parsed


def format_articles(articles: list[dict]) -> str:
    lines = []
    for a in articles:
        date_tag = f" [{a['pubDate'][:10]}]" if a["pubDate"] else ""
        lines.append(f"- [{a['title']}{date_tag}]({a['link']})")
        if a["description"]:
            snippet = a["description"][:120].strip()
            lines.append(f"  > {snippet}")
    return "\n".join(lines)


# -------- KUBERNETES NEWS --------

def get_k8s_news() -> str:
    """
    Two focused queries merged to improve recall:
      Query 1 — core Kubernetes / CNCF releases & security
      Query 2 — broader cloud-native ecosystem (Helm, Argo, Istio, etc.)
    """
    query1 = '"kubernetes" (release OR security OR vulnerability OR update OR CNCF)'
    query2 = '"cloud native" (Helm OR Argo OR Istio OR Cilium OR OpenTelemetry OR Flux)'

    articles1 = get_news(query1, size=10)
    articles2 = get_news(query2, size=8)

    seen, merged = set(), []
    for a in articles1 + articles2:
        if a["link"] not in seen:
            seen.add(a["link"])
            merged.append(a)

    return format_articles(merged[:18])


# -------- STOCK NEWS --------

def get_stock_news() -> str:
    """Fetch Indian stock market news headlines for GPT summarisation."""
    articles1 = get_news("Nifty Sensex Indian stock market", country="in", size=8)
    articles2 = get_news("NSE BSE India stocks earnings", country="in", size=6)

    seen, merged = set(), []
    for a in articles1 + articles2:
        if a["link"] not in seen:
            seen.add(a["link"])
            merged.append(a)

    return format_articles(merged[:12])


# -------- NSE GAINERS / LOSERS SCRAPER --------

GAINERS_URL = "https://www.moneycontrol.com/stocks/marketstats/nsegainer/index.php"
LOSERS_URL  = "https://www.moneycontrol.com/stocks/marketstats/nseloser/index.php"


def scrape_movers(url: str, label: str, top_n: int = 20) -> list[dict]:
    """
    Scrape top N gainers or losers from Moneycontrol NSE stats page.
    Returns list of dicts: {name, change_pct, link}
    """
    headers = {"User-Agent": "Mozilla/5.0 (compatible; DailyNewsBot/1.0)"}
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f"[ERROR] Could not fetch {label}: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")

    # Moneycontrol uses a table with class "tbldata14 bdrtpg"
    table = soup.find("table", {"class": lambda c: c and "tbldata14" in c})
    if not table:
        table = soup.find("table", {"id": "tbldata"}) or soup.find("table")

    if not table:
        print(f"[WARN] No table found on {label} page")
        return []

    rows = table.find_all("tr")[1:]  # skip header row
    results = []
    for row in rows[:top_n]:
        cols = row.find_all("td")
        if len(cols) < 3:
            continue

        anchor = cols[0].find("a")
        name   = anchor.get_text(strip=True) if anchor else cols[0].get_text(strip=True)
        link   = anchor["href"] if anchor and anchor.get("href") else ""
        if link and link.startswith("/"):
            link = "https://www.moneycontrol.com" + link

        # % change is usually at col index 4 (LTP | Prev Close | Change | %Change | ...)
        pct = ""
        for idx in [4, 3, 2]:
            if idx < len(cols):
                txt = cols[idx].get_text(strip=True)
                if "%" in txt or (txt.replace(".", "").replace("-", "").isdigit() and txt):
                    pct = txt
                    break

        if name:
            results.append({"name": name, "change_pct": pct, "link": link})

    return results


def format_movers(movers: list[dict]) -> str:
    if not movers:
        return "_No data available_"
    lines = []
    for i, m in enumerate(movers, 1):
        pct_tag = f"  `{m['change_pct']}`" if m["change_pct"] else ""
        if m["link"]:
            lines.append(f"{i}\\. [{m['name']}]({m['link']}){pct_tag}")
        else:
            lines.append(f"{i}\\. {m['name']}{pct_tag}")
    return "\n".join(lines)


def get_stock_movers() -> str:
    """Returns a pre-formatted Telegram message with top 20 gainers and losers."""
    print("  → Scraping gainers...")
    gainers = scrape_movers(GAINERS_URL, "gainers", top_n=20)
    print("  → Scraping losers...")
    losers  = scrape_movers(LOSERS_URL,  "losers",  top_n=20)

    gainers_text = format_movers(gainers)
    losers_text  = format_movers(losers)

    msg = (
        "📗 *Top 20 NSE Gainers*\n"
        f"{gainers_text}\n\n"
        "📕 *Top 20 NSE Losers*\n"
        f"{losers_text}\n\n"
        f"🔗 [View full gainers]({GAINERS_URL})  |  [View full losers]({LOSERS_URL})"
    )
    return msg


# -------- GPT SUMMARISATION --------

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
- EXCLUDE: generic tutorials, cloud provider marketing, opinion pieces, duplicates.
- Pick the TOP 4–5 highest-signal items only.

════════════════════════════════
SECTION 2 — Indian Stock Market News
════════════════════════════════
INPUT:
{stock_news}

RULES:
- 2-line market summary covering Nifty/Sensex movement, FII/DII flows, major sector trends.
- Sentiment: Bullish / Bearish / Neutral with a one-line rationale.
- Do NOT list individual stocks here — gainers/losers are sent in a separate message.

════════════════════════════════
OUTPUT FORMAT (Telegram Markdown):
════════════════════════════════

🚀 *Kubernetes & Cloud Native*
• [Title](url) — one-line takeaway
• ...

📈 *Indian Stock Market*
*Summary:* ...
*Sentiment:* Bullish/Bearish/Neutral — reason

IMPORTANT:
- Use Telegram MarkdownV1 (single asterisks for bold, links as [text](url)).
- Be concise; remove all noise.
- Never invent links or tickers.
"""
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )
    return response.choices[0].message.content


# -------- SEND TELEGRAM --------

def send_telegram(message: str) -> None:
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id":                  CHAT_ID,
        "text":                     message,
        "parse_mode":               "Markdown",
        "disable_web_page_preview": True,
    }
    try:
        resp = requests.post(url, data=payload, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        print(f"[ERROR] Telegram send failed: {e}")
        # Fallback: retry as plain text if Markdown caused the failure
        payload["parse_mode"] = ""
        try:
            requests.post(url, data=payload, timeout=10)
        except Exception as e2:
            print(f"[ERROR] Telegram fallback also failed: {e2}")


# -------- MAIN --------

if __name__ == "__main__":
    print("📰 Fetching Kubernetes news...")
    k8s_news = get_k8s_news()

    print("📊 Fetching stock market news...")
    stock_news = get_stock_news()

    print("📈 Scraping NSE gainers / losers...")
    movers_msg = get_stock_movers()

    print("🤖 Summarising with GPT...")
    summary_msg = summarize(k8s_news, stock_news)

    # Message 1: GPT summary (k8s + market sentiment)
    print("📬 Sending summary to Telegram...")
    send_telegram(summary_msg)

    # Message 2: Gainers / losers table + direct links
    print("📬 Sending movers to Telegram...")
    send_telegram(movers_msg)

    print("✅ All messages sent to Telegram!")
