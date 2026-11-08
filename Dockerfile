# --- frontend build ---
FROM node:22-alpine AS frontend
WORKDIR /app/frontend
RUN corepack enable
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build

# --- runtime ---
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock* README.md ./
COPY src/ src/
COPY --from=frontend /app/src/beetsplug/webui/static src/beetsplug/webui/static
# The plugin plus the extras that the plugins in examples/config.template.yaml need. Releases pass
# the beets version locked in uv.lock; local builds take the newest one the plugin allows.
ARG BEETS_VERSION=""
RUN uv pip install --system --no-cache . "beets[fetchart,embedart,lastgenre]${BEETS_VERSION:+==$BEETS_VERSION}"

COPY docker/ /docker/
ENV BEETSDIR=/config
VOLUME ["/config", "/music"]
EXPOSE 8338

ENTRYPOINT ["/docker/entrypoint.sh"]
CMD ["beet", "webui", "0.0.0.0"]
