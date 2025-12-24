# Emulator container for E2E testing
# Simulates:
# - CPU load emulator on target servers
# - Agent installation/verification
# - Agent load simulation

FROM python:3.11-slim

WORKDIR /app

# Install curl for healthcheck
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# Install dependencies
RUN pip install --no-cache-dir \
    fastapi \
    uvicorn \
    pydantic

# Copy applications
COPY emulator_server.py .
COPY agent_simulator.py .
COPY combined_server.py .

# Create agent install directory
RUN mkdir -p /opt/test-agent

# Expose ports
# 8080 - Emulator API
# 8085 - Agent API
EXPOSE 8080 8085

# Health check
HEALTHCHECK --interval=5s --timeout=3s --retries=5 \
    CMD curl -f http://localhost:8080/health || exit 1

# Run combined server (includes both emulator and agent)
CMD ["python", "combined_server.py"]
