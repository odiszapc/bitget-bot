#!/bin/bash
set -e

cd /home/odiszapc/bitget-bot

# Ensure GitHub is in known_hosts
ssh-keyscan -H github.com >> ~/.ssh/known_hosts 2>/dev/null

# Clone or pull
if [ -d .git ]; then
    git pull
else
    git init
    git remote add origin git@github.com:odiszapc/bitget-bot.git
    git fetch origin
    git checkout -f origin/main -B main
    git branch --set-upstream-to=origin/main main
fi

# Ensure data dirs exist
mkdir -p data/logs data/output
[ -f data/state.json ] || echo '{}' > data/state.json

# Build and restart
docker compose up -d --build
