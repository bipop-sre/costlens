# CostLens Dockerfile
FROM harbor.ymt.io/inf/python:3.11-slim

# Set working directory
WORKDIR /app

# Disable pip progress bar globally (fixes threading crash in restricted CI environments)
ENV PIP_PROGRESS_BAR=off PIP_NO_INPUT=1 PIP_DISABLE_PIP_VERSION_CHECK=1

# Copy requirements first for better caching
COPY requirements.txt .

# Upgrade pip (old bundled rich has threading issues) then install deps
RUN python -m pip install --upgrade pip setuptools wheel && \
    python -m pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create data directory
RUN mkdir -p /app/data

# Set environment variables
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Expose port for web dashboard
EXPOSE 8080

# Health check - verifies web server is responsive
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8080/health').raise_for_status()" || exit 1

# Start web server (bot and scheduler start automatically via lifespan)
CMD ["python", "run_web.py"]
