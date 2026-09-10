# CostLens Dockerfile
FROM harbor.ymt.io/inf/python:3.11-slim

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

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
