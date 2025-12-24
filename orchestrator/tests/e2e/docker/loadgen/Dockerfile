# Load Generator container for E2E testing
# Simulates JMeter load generator

FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir \
    fastapi \
    uvicorn \
    httpx \
    pydantic

# Install curl for health checks
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# Copy loadgen application
COPY loadgen_server.py .

# Copy JMX test plans
RUN mkdir -p /opt/jmeter/plans
COPY plans/*.jmx /opt/jmeter/plans/

# Expose loadgen port
EXPOSE 8090

# Health check
HEALTHCHECK --interval=5s --timeout=3s --retries=5 \
    CMD curl -f http://localhost:8090/health || exit 1

# Run loadgen server
CMD ["python", "loadgen_server.py"]
