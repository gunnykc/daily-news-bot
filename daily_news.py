import requests
from openai import OpenAI

import os

NEWS_API_KEY = os.getenv("NEWS_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

client = OpenAI(api_key=OPENAI_API_KEY)

# -------- FETCH NEWS --------
def get_news(query):
    url = f"https://newsdata.io/api/1/news?apikey={NEWS_API_KEY}&q={query}&language=en"
    res = requests.get(url).json()
    articles = res.get("results", [])[:10]

    return "\n".join([f"- {a['title']}" for a in articles])


# -------- CHATGPT PROCESSING --------
def summarize(k8s_news, stock_news):
    prompt = f"""
You are a smart daily news assistant.

1. Summarize Kubernetes/Tech news (top 10)
2. Summarize Indian stock market news
3. Suggest:
   - 2–3 stocks to watch or buy
   - Overall sentiment (Bullish/Bearish/Neutral)

Make it SHORT and Telegram friendly.

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
k8s_news = get_news("kubernetes OR cloud OR devops")
stock_news = get_news("Indian stock market OR NSE OR BSE")

final_msg = summarize(k8s_news, stock_news)
send_telegram(final_msg)

print("✅ Sent to Telegram!")
