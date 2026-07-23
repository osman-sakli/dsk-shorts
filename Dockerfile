FROM node:20-bookworm-slim

# System deps: Remotion's headless Chromium libs, Python for the Polly TTS step, ffmpeg for thumbnails
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates fonts-liberation \
    libasound2 libatk-bridge2.0-0 libatk1.0-0 libcups2 libdbus-1-3 libdrm2 \
    libgbm1 libgtk-3-0 libnspr4 libnss3 libu2f-udev libvulkan1 libx11-xcb1 \
    libxcomposite1 libxdamage1 libxfixes3 libxkbcommon0 libxrandr2 xdg-utils \
    python3 python3-pip python3-venv \
    ffmpeg curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY pipeline/requirements.txt pipeline/requirements.txt
RUN python3 -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir -r pipeline/requirements.txt
ENV PATH="/opt/venv/bin:$PATH"

COPY . .

# Pre-download Remotion's bundled headless browser at build time so the daily
# Fargate task doesn't pay that cost on every run.
RUN npx remotion browser ensure

ENV NODE_ENV=production
CMD ["python3", "pipeline/entrypoint.py"]
