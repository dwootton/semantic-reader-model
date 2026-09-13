#!/usr/bin/env bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
# BrowserGym pins Playwright 1.44, whose install-deps uses the pre-t64 ALSA name.
# Install Ubuntu 24.04 native shared libraries, then its pinned Chromium binary.
apt-get update
apt-get install -y libnss3 libatk-bridge2.0-0t64 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2t64 libcups2t64 libpango-1.0-0 libcairo2 libatk1.0-0t64 fonts-liberation libatspi2.0-0t64
export PLAYWRIGHT_BROWSERS_PATH=/opt/semantic-reader/browsers
/opt/semantic-reader/venv/bin/python -m playwright install chromium
mkdir -p /opt/semantic-reader/nltk
/opt/semantic-reader/venv/bin/python -m nltk.downloader -d /opt/semantic-reader/nltk punkt_tab
/opt/semantic-reader/venv/bin/pip freeze > /opt/semantic-reader/installed-requirements.txt
touch /opt/semantic-reader/runtime-ready
