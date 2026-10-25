# Lightweight Python base image
FROM python:3.14-slim

# Set environment variables for non-buffered logging and clean bytecode
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=5000 \
    TCP_HOST=0.0.0.0 \
    TCP_PORT=1337

WORKDIR /app

# Install system dependencies if required
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy and install python dependencies first for layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend source code
COPY . .

# Create volume mount directories and ensure permissions
RUN mkdir -p /app/data /app/log /app/client_log /app/config && \
    useradd -u 1000 -m appuser && \
    chown -R appuser:appuser /app

USER appuser

# Expose HTTP REST API and TCP Socket Ports
EXPOSE 5000 1337

# Healthcheck checking the root endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:5000/ || exit 1

# Start the unified backend application
CMD ["python", "main.py"]
