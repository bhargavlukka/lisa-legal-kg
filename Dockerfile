# LISA images. Case data and built graphs are mounted at runtime (never baked in): /data (package data, read-only)
# and /app/out (graphs from scripts/build_graph.py + scripts/enrich_llm.py, caches, traces).
#
#   docker build --target server -t lisa-server .   # the four MCP servers (one image, module chosen per service)
#   docker build --target agent  -t lisa-agent  .   # research agent: Claude Agent SDK + claude CLI (node)

FROM python:3.12-slim AS server
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 LISA_HOST=0.0.0.0 LISA_DATA_DIR=/data LISA_OUT_DIR=/app/out
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY config ./config
COPY scripts ./scripts
RUN pip install . && useradd --create-home --uid 10001 lisa && mkdir -p /app/out && chown lisa /app/out
USER lisa
# LISA_SERVER = lisa.servers.graph_server | citation_verifier | analytics_server | external_law_server
CMD ["sh", "-c", "python -m ${LISA_SERVER:?set LISA_SERVER}"]

FROM server AS agent
USER root
ARG CLAUDE_CODE_VERSION=latest
RUN apt-get update && apt-get install -y --no-install-recommends nodejs npm \
    && npm install -g @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION} \
    && apt-get purge -y npm && apt-get autoremove -y && rm -rf /var/lib/apt/lists/* \
    && pip install ".[agent]"
USER lisa
ENTRYPOINT ["python", "scripts/ask.py"]
CMD ["--help"]
