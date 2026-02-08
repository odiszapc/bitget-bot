#!/bin/bash
set -e

cd /home/odiszapc/bitget-bot

# Clone or pull
if [ -d .git ]; then
    git pull
else
    git clone git@github.com:odiszapc/bitget-bot.git tmp
    mv tmp/.git .
    mv tmp/* . 2>/dev/null || true
    mv tmp/.* . 2>/dev/null || true
    rm -rf tmp
fi

# Ensure data dirs exist
mkdir -p data/logs data/output
[ -f data/state.json ] || echo '{}' > data/state.json

# Build and restart
docker compose up -d --build
