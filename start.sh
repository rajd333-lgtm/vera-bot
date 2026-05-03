#!/usr/bin/env bash
# start.sh — run both the bot + judge simulator
# Usage: ./start.sh YOUR_GEMINI_API_KEY
set -e

KEY="${1:-$GEMINI_API_KEY}"

if [ -z "$KEY" ]; then
  echo "❌  Usage: ./start.sh YOUR_GEMINI_API_KEY"
  echo "   Get a free key at: https://aistudio.google.com → API Keys"
  exit 1
fi

# Write .env
echo "GEMINI_API_KEY=$KEY" > .env
echo "GEMINI_MODEL=gemini-1.5-flash" >> .env

echo "✅  .env written"
echo ""
echo "▶  Starting Vera Bot on http://localhost:8080 ..."
GEMINI_API_KEY=$KEY uvicorn main:app --host 0.0.0.0 --port 8080 &
BOT_PID=$!
sleep 2
echo "✅  Bot running (PID $BOT_PID)"
echo ""
echo "▶  Running judge simulator..."
python judge_simulator.py
echo ""
echo "▶  Stopping bot..."
kill $BOT_PID 2>/dev/null || true
