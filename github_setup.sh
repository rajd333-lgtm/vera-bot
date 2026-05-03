#!/usr/bin/env bash
# github_setup.sh — push vera-bot to a new GitHub repo
# Usage: ./github_setup.sh YOUR_GITHUB_USERNAME
set -e

USERNAME="${1:-YOUR_USERNAME}"
REPO="vera-bot"

echo "========================================"
echo "  Vera Bot → GitHub Setup"
echo "========================================"
echo ""
echo "Step 1: Create repo on GitHub"
echo "  → Go to: https://github.com/new"
echo "  → Name: $REPO"
echo "  → Visibility: Public"
echo "  → Do NOT add README/gitignore (we have our own)"
echo "  → Click 'Create repository'"
echo ""
read -p "Press Enter once the repo is created..."

echo ""
echo "Step 2: Initializing local git..."
git init
git config user.email "you@example.com"
git config user.name "$USERNAME"
git add .
git commit -m "feat: initial Vera Bot submission

- FastAPI server with all 5 required endpoints
- Gemini 1.5 Flash (free tier) as LLM backend  
- 4-context composition (category/merchant/customer/trigger)
- Trigger-specific prompt routing (12 trigger kinds)
- Auto-reply detection + graceful exit
- Multi-turn conversation state management
- Suppression dedup"

echo ""
echo "Step 3: Push to GitHub..."
git remote add origin "https://github.com/$USERNAME/$REPO.git"
git branch -M main
git push -u origin main

echo ""
echo "✅ Done! Your repo: https://github.com/$USERNAME/$REPO"
echo ""
echo "Next: Deploy for a public URL:"
echo "  Railway → https://railway.app"
echo "  Render  → https://render.com"
