# syntax=docker/dockerfile:1
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /opt/app

# System deps if needed
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Copy project
COPY . /opt/app/shpak-k8s/

# Install Python deps (fallback to minimal if file missing)
COPY ./tests/requirements.txt /opt/app/requirements.txt
RUN if [ -f /opt/app/requirements.txt ]; then \
      pip install -r /opt/app/requirements.txt; \
    else \
      pip install fastapi uvicorn pydantic[dotenv] orjson httpx PyYAML; \
    fi

# Default command; override per service
CMD ["python", "-c", "import os; print('shpak-k8s image ready; mount service code or set CMD')"]


