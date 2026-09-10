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

# Default command - run web dashboard
CMD ["python", "run_web.py"]
