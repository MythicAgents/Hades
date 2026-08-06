FROM python:3.11-slim

# Install Node.js (javascript-obfuscator), Go (Windows launcher cross-compilation),
# and C build tools needed to compile psutil from source on ARM.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates curl xz-utils gcc python3-dev && \
    \
    # ── Node.js ──────────────────────────────────────────────────────────────
    NODE_ARCH="$(dpkg --print-architecture)" && \
    case "${NODE_ARCH}" in \
      amd64) NODE_ARCH="x64" ;; \
      arm64) NODE_ARCH="arm64" ;; \
    esac && \
    curl -fsSL "https://nodejs.org/dist/v20.18.0/node-v20.18.0-linux-${NODE_ARCH}.tar.xz" \
      | tar -xJ -C /usr/local --strip-components=1 && \
    npm install -g javascript-obfuscator && \
    \
    # ── Go (for Windows launcher cross-compilation) ───────────────────────────
    GO_ARCH="$(dpkg --print-architecture)" && \
    case "${GO_ARCH}" in \
      amd64) GO_ARCH="amd64" ;; \
      arm64) GO_ARCH="arm64" ;; \
    esac && \
    curl -fsSL "https://go.dev/dl/go1.22.4.linux-${GO_ARCH}.tar.gz" \
      | tar -xz -C /usr/local && \
    \
    apt-get purge -y curl xz-utils && \
    apt-get autoremove -y && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

ENV PATH="/usr/local/go/bin:${PATH}"
ENV GOPATH="/root/go"
ENV GOCACHE="/root/.cache/go-build"

WORKDIR /Mythic/

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    apt-get purge -y gcc python3-dev && \
    apt-get autoremove -y && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

COPY . .

CMD ["python3", "mythic/mythic_service.py"]
