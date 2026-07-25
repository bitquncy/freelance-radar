# Pinned to bookworm (Debian 12): Playwright 1.41's dependency registry
# supports debian11/debian12/ubuntu20.04/ubuntu22.04 only. The floating
# python:3.11-slim tag moved to Debian 13 (trixie), where
# `playwright install-deps` falls back to the ubuntu20.04 package list and
# dies on renamed font packages (ttf-unifont → fonts-unifont).
FROM python:3.11-slim-bookworm

# Install system dependencies for Playwright
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    libglib2.0-0 \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxcb1 \
    libxkbcommon0 \
    libx11-6 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    libatspi2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first for caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers
RUN playwright install chromium
RUN playwright install-deps chromium

# Copy application code
COPY . .

# Create data directory
RUN mkdir -p /app/data /app/logs

# Health check script
COPY scripts/healthcheck.py /app/healthcheck.py
COPY scripts/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python /app/healthcheck.py || exit 1

# Run via entrypoint
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python", "main.py"]
