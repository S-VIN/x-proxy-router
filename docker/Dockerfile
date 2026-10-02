# Built from the root of the repository: docker build -f docker/Dockerfile .
# Platforms: linux/amd64 and linux/arm64, the Linux builds of Mihomo in resources/mihomo.

# The web client and the choice of Mihomo do not depend on the target platform,
# so they run natively on the build machine.
FROM --platform=$BUILDPLATFORM node:22-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM --platform=$BUILDPLATFORM alpine:3 AS mihomo
ARG TARGETARCH
COPY resources/mihomo/ /mihomo/
# Only the binary of the target platform: amd64 -> x64, arm64 -> arm64 (server/utils/platform.py).
RUN case "$TARGETARCH" in \
        amd64) arch=x64 ;; \
        arm64) arch=arm64 ;; \
        *) echo "Mihomo has no build for $TARGETARCH" >&2; exit 1 ;; \
    esac \
    && mkdir -p /out/linux \
    && mv /mihomo/LICENSE /out/ \
    && mv "/mihomo/linux/$arch" /out/linux/ \
    && chmod 755 "/out/linux/$arch/mihomo"

# Python dependencies exactly as in uv.lock, without the development tools.
FROM python:3.11-slim AS python
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

FROM python:3.11-slim
WORKDIR /app
# The same layout as in the repository: the server finds Mihomo and the web client by it.
COPY --from=python /app/.venv .venv/
COPY --from=mihomo /out/ resources/mihomo/
COPY --from=web /web/dist/ web/dist/
COPY server/ server/
COPY --chmod=755 docker/entrypoint.sh /app/entrypoint.sh

# settings.sqlite3 is created in the working directory; a folder of the host is mounted there.
WORKDIR /data
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    XPR_UI_HOST=0.0.0.0

ENTRYPOINT ["/app/entrypoint.sh"]
