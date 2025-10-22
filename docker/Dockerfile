# syntax=docker/dockerfile:1
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH="/opt/app/.local/bin:$PATH"

WORKDIR /opt/app

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    libssl-dev \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy minimal requirements first for better layer caching
COPY config/requirements.txt /opt/app/requirements.txt
RUN pip install --upgrade pip && \
    pip install -r /opt/app/requirements.txt

# Copy application code
COPY app/ /opt/app/app/

# Create non-root user for security
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /opt/app
USER appuser

# Health check (override per service)
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import sys; sys.exit(0)"

# Default command
CMD ["python", "-c", "print('shpak-k8s ready. Override CMD per service.')"]

