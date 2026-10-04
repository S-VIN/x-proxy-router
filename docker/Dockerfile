# check=skip=InvalidDefaultArgInFrom
# Built from the root of the repository with the versions of build.json (docker/README.md):
#   docker build $(node scripts/build-config.mjs docker) -f docker/Dockerfile .
# Platforms: linux/amd64 and linux/arm64, the Linux builds of Mihomo in resources/mihomo.
# The versions have no defaults (the check above): they are only those of build.json.
ARG NODE_VERSION
ARG PYTHON_VERSION
ARG UV_VERSION

# The web client and the choice of Mihomo do not depend on the target platform,
# so they run natively on the build machine.
FROM --platform=$BUILDPLATFORM node:${NODE_VERSION}-alpine AS web
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

# COPY --from takes no build arguments: the image of uv is a stage of its own.
FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

# Python dependencies exactly as in uv.lock, without the development tools.
FROM python:${PYTHON_VERSION}-slim AS python
COPY --from=uv /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

FROM python:${PYTHON_VERSION}-slim
WORKDIR /app
# The same layout as in the repository: the server finds Mihomo and the web client by it.
COPY --from=python /app/.venv .venv/
COPY --from=mihomo /out/ resources/mihomo/
COPY --from=web /web/dist/ web/dist/
COPY server/ server/

ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1
# The server requires XPR_UI_PORT and XPR_DATA_DIR; compose.yaml passes them.
CMD ["python", "-m", "server.main"]
