FROM python:3.11-slim

# System packages needed for lxml and a few yfinance deps
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential libxml2-dev libxslt1-dev \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN pip install --no-cache-dir uv

WORKDIR /app

# Install deps first for layer caching
COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen || uv sync

# Copy source
COPY . .

# Build knowledge graph into the image (so first request is fast)
RUN uv run python scripts/build_knowledge_graph.py || true

ENV ENV=prod
EXPOSE 8000

CMD ["uv", "run", "uvicorn", "src.api:app", "--host", "0.0.0.0", "--port", "8000"]
