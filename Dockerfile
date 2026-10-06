# LISA images. Case data and built graphs are mounted at runtime (never baked in): /data (package data, read-only)
# and /app/out (graphs from scripts/build_graph.py + scripts/enrich_llm.py, caches, traces).
#
#   docker build --target server -t lisa-server .   # the four MCP servers (one image, module chosen per service)
#   docker build --target agent  -t lisa-agent  .   # research agent: Claude Agent SDK + claude CLI (node)

FROM python:3.12-slim AS server
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 LISA_HOST=0.0.0.0 LISA_DATA_DIR=/data LISA_OUT_DIR=/app/out
WORKDIR /app
# Editable install: lisa.common.config resolves config/ (and the agent its .claude/skills) relative to the source tree,
# so a site-packages copy would look for /usr/local/lib/config/settings.yaml and every server would fail at startup.
COPY pyproject.toml README.md ./
COPY src ./src
COPY config ./config
COPY scripts ./scripts
RUN pip install -e . && useradd --create-home --uid 10001 lisa && mkdir -p /app/out && chown lisa /app/out
USER lisa
# LISA_SERVER = lisa.servers.graph_server | citation_verifier | analytics_server | external_law_server
CMD ["sh", "-c", "python -m ${LISA_SERVER:?set LISA_SERVER}"]

FROM server AS agent
USER root
# pinned: the Agent SDK is tested against this CLI version
ARG CLAUDE_CODE_VERSION=2.1.289
RUN apt-get update && apt-get install -y --no-install-recommends nodejs npm \
    && npm install -g @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION} \
    && apt-get purge -y npm && apt-get autoremove -y && rm -rf /var/lib/apt/lists/* \
    && pip install -e ".[agent]"
USER lisa
ENTRYPOINT ["python", "scripts/ask.py"]
CMD ["--help"]
