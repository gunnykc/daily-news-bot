import requests
from openai import OpenAI

import os

NEWS_API_KEY = os.getenv("NEWS_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

client = OpenAI(api_key=OPENAI_API_KEY)


def get_k8s_news():
    return get_news(
        "kubernetes CNCF kubernetes release kubernetes security"
    )


def get_stock_news():
    return get_news(
        "Indian stock market NSE BSE Nifty Sensex stocks",
        country="in"
    )


# -------- FETCH NEWS --------
def get_news(query, country=None):
    url = f"https://newsdata.io/api/1/news?apikey={NEWS_API_KEY}&q={query}&language=en"

    if country:
        url += f"&country={country}"

    res = requests.get(url).json()
    articles = res.get("results", [])[:10]

    news_list = []
    for a in articles:
        title = a.get("title", "No title").replace("(", "").replace(")", "")
        link = a.get("link", "")
        news_list.append(f"- [{title}]({link})")

    return "\n".join(news_list)


# -------- CHATGPT PROCESSING --------
def summarize(k8s_news, stock_news):
    prompt = f"""
You are a highly selective expert news analyst.

STRICT FILTERING RULES:

1. Kubernetes Section:
- ONLY include:
  - Kubernetes official releases
  - CNCF ecosystem updates
  - Security updates
- EXCLUDE:
  - Cloud provider news (AWS, Azure, GCP unless directly Kubernetes core)

2. Indian Stock Market:
- ONLY India-related news
- Focus on:
  - Nifty / Sensex movement
  - Major sector trends
  - High-impact company updates

OUTPUT FORMAT (Telegram friendly, concise):

🚀 Kubernetes (Top 3-5)
- Keep only HIGH SIGNAL news with links

📈 Indian Stock Market
- Market Summary (2 lines max)
- Sentiment: Bullish / Bearish / Neutral
- Stocks to Watch (2-3 with 1-line reasoning)

IMPORTANT:
- Keep links clickable
- Remove noise
- Be concise

DATA:

Kubernetes News:
{k8s_news}

Stock News:
{stock_news}
"""

    response = client.chat.completions.create(
        model="gpt-5-mini",
        messages=[{"role": "user", "content": prompt}]
    )

    return response.choices[0].message.content


# -------- SEND TELEGRAM --------
def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, data={
        "chat_id": CHAT_ID,
        "text": message
    })


# -------- MAIN --------
k8s_news = get_k8s_news()
stock_news = get_stock_news()

final_msg = summarize(k8s_news, stock_news)
send_telegram(final_msg)

print("✅ Sent to Telegram!")
