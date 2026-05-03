# 🤖 Vera Bot — magicpin AI Challenge

AI-powered merchant WhatsApp assistant using **Google Gemini (free tier)** as the LLM backbone.

---

## ⚡ Quick Start (3 steps)

### 1. Clone & Install
```bash
git clone https://github.com/YOUR_USERNAME/vera-bot.git
cd vera-bot
pip install -r requirements.txt
```

### 2. Set your FREE Gemini API key
```bash
cp .env.example .env
# Edit .env — paste your key:  GEMINI_API_KEY=AIzaSy...
```
Get a free key → [aistudio.google.com](https://aistudio.google.com) → **Get API key**

### 3. Run
```bash
chmod +x start.sh
./start.sh YOUR_GEMINI_KEY     # starts bot + judge in one command
```

---

## 🌐 Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/v1/healthz` | Liveness probe |
| `GET` | `/v1/metadata` | Bot identity |
| `POST` | `/v1/context` | Push context (category/merchant/customer/trigger) |
| `POST` | `/v1/tick` | Compose proactive WhatsApp messages |
| `POST` | `/v1/reply` | Handle merchant reply; return next action |

---

## 🚀 Deploy (get public URL for submission)

### Railway (free)
```bash
npm i -g @railway/cli
railway login && railway init
railway variables set GEMINI_API_KEY=AIzaSy...
railway up
railway domain   # submit this URL to magicpin
```

### Render (free)
1. New Web Service → connect repo
2. Env var: `GEMINI_API_KEY=AIzaSy...`
3. Start: `uvicorn main:app --host 0.0.0.0 --port $PORT`

### Docker
```bash
docker build -t vera-bot .
docker run -e GEMINI_API_KEY=AIzaSy... -p 8080:8080 vera-bot
```

---

## 🔐 Security
- Never commit `.env` — it's in `.gitignore`
- Rotate exposed keys at [aistudio.google.com](https://aistudio.google.com)
