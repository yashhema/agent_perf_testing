# Load Generator Service Dockerfile

FROM python:3.11-slim

# Install Java for JMeter
RUN apt-get update && apt-get install -y \
    default-jre \
    wget \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install JMeter
ENV JMETER_VERSION=5.6.3
RUN wget -q https://archive.apache.org/dist/jmeter/binaries/apache-jmeter-${JMETER_VERSION}.tgz \
    && tar -xzf apache-jmeter-${JMETER_VERSION}.tgz -C /opt \
    && rm apache-jmeter-${JMETER_VERSION}.tgz \
    && ln -s /opt/apache-jmeter-${JMETER_VERSION} /opt/jmeter

ENV JMETER_HOME=/opt/jmeter
ENV PATH=$JMETER_HOME/bin:$PATH

WORKDIR /app

# Copy requirements first for caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create output directory
RUN mkdir -p /tmp/loadgen

# Set environment variables
ENV LOADGEN_PORT=8090
ENV LOADGEN_OUTPUT_DIR=/tmp/loadgen
ENV PYTHONUNBUFFERED=1

# Expose port
EXPOSE 8090

# Run the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8090"]
