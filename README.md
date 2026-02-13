# Agent Performance Testing Framework

A comprehensive framework for testing security agent performance under various system loads. The framework generates realistic workloads (CPU, memory, disk, network, database) and measures the impact of security agents on system performance.

## Project Overview

This framework enables:
- **Baseline measurement**: Capture system performance without security agents
- **Agent impact testing**: Measure performance degradation with agents installed
- **Realistic workloads**: Database queries, file operations, network traffic with real PII data
- **Multi-database support**: PostgreSQL, SQL Server, Oracle, DB2

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Orchestrator  │────▶│    LoadGen      │────▶│    Emulator     │
│   (Control)     │     │   (JMeter)      │     │  (Workload)     │
└─────────────────┘     └─────────────────┘     └─────────────────┘
        │                                               │
        │                                               ▼
        │                                       ┌─────────────────┐
        └──────────────────────────────────────▶│   Database      │
                                                │   (Target)      │
                                                └─────────────────┘
```

## Components

### 1. Orchestrator (`orchestrator/`)
Central control service that manages test execution.

- **Status**: Partially implemented
- **Features**:
  - Lab management (test environments)
  - Baseline/calibration runs
  - Test run coordination
  - Remote execution (SSH/WinRM)
- **Tech**: FastAPI, SQLAlchemy, Alembic

### 2. Emulator (`emulator/`)
Generates system workloads on target machines.

- **Status**: Implemented with recent enhancements
- **Features**:
  - CPU/Memory/Disk/Network load operations
  - File operations with confidential data
  - **NEW**: Test lifecycle with stats collection
  - **NEW**: Background stats collection during tests
  - **NEW**: Stats persistence to JSON files
- **Tech**: FastAPI, psutil, asyncio

### 3. LoadGen (`loadgen/`)
JMeter wrapper service for load testing.

- **Status**: Implemented
- **Features**:
  - JMeter test execution
  - Result parsing and aggregation
  - HTTP API for test control
- **Tech**: FastAPI, JMeter (subprocess)

### 4. DB-Assets (`db-assets/`)
Database schema and query generator.

- **Status**: Implemented
- **Features**:
  - 201 tables across 4 domains (E-Commerce, Banking, Healthcare, Shared)
  - Seed data with real PII from ConfidentialData Excel files
  - Parameterized queries for JMeter
  - JMX template generation
  - Multi-database DDL (PostgreSQL, MSSQL, Oracle, DB2)
- **Tech**: SQLAlchemy, Faker, pandas

## Current State (January 2026)

### Completed

1. **Database Schema Generator**
   - All 201 tables defined with SQLAlchemy models
   - Schema generation for all 4 database types
   - Seed data generation (~113K records populated in MSSQL test)
   - FK/UNIQUE constraints removed for simpler data loading
   - Query generator with parameterized CSV files
   - JMX template generator for load tests

2. **Emulator Service**
   - All operation types (CPU, MEM, DISK, NET, FILE)
   - Test management with threading
   - **NEW**: Test lifecycle endpoints:
     - `POST /api/v1/tests/start` - Start test with stats collection
     - `POST /api/v1/tests/{id}/stop` - Stop test, save stats to file
     - `GET /api/v1/stats/recent?count=N` - Get last N samples
     - `GET /api/v1/stats/all?test_run_id=X` - Load stats from file
   - Background stats collection (CPU, memory, disk I/O, network I/O)
   - Stats persisted to `./stats/{test_run_id}_{scenario_id}_{mode}_stats.json`

3. **LoadGen Service**
   - JMeter execution and management
   - Result parsing

4. **Orchestrator Service**
   - Basic structure and repositories
   - Lab/baseline/test-run management

### Data Assets

- **ConfidentialData**: 14 Excel files with ~62,757 rows of PII (SSN, credit cards, names, addresses)
- **Database output**: `db-assets/output/{db_type}/` with schema, seed data, queries, params

## Directory Structure

```
agent_perf_testing/
├── orchestrator/           # Test orchestration service
│   ├── app/
│   │   ├── api/           # FastAPI routers
│   │   ├── repositories/  # Data access layer
│   │   ├── services/      # Business logic
│   │   └── remote/        # SSH/WinRM execution
│   └── alembic/           # Database migrations
│
├── emulator/              # Workload generation service
│   ├── app/
│   │   ├── operations/    # CPU, MEM, DISK, NET operations
│   │   ├── routers/       # FastAPI endpoints
│   │   ├── stats/         # Stats collection
│   │   └── services/      # Test management
│   └── tests/
│
├── loadgen/               # JMeter wrapper service
│   ├── app/
│   │   ├── jmeter/        # JMeter manager
│   │   └── routers/       # FastAPI endpoints
│   └── tests/
│
├── db-assets/             # Database schema generator
│   ├── generator/
│   │   ├── models/        # SQLAlchemy table definitions
│   │   ├── generators/    # Schema, seed, query generators
│   │   ├── loaders/       # ConfidentialData Excel loader
│   │   ├── jmx/           # JMX template generation
│   │   └── utils/         # Faker providers
│   ├── output/            # Generated SQL files
│   └── tests/
│
├── ConfidentialData/      # PII Excel files (14 files)
└── docker/                # Docker compose files
```

## Specifications

Detailed specifications are in `FinalProcess/`:
- `EMULATOR_SPECIFICATION.md` - Emulator service API and features
- `DATABASE_SCHEMA_GENERATOR_SPECIFICATION.md` - DB generator details
- `JMX_TEMPLATES_SPECIFICATION.md` - JMeter template formats

## Quick Start

### Running the Emulator

```bash
cd emulator
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

### Generating Database Assets

```bash
cd db-assets
pip install -r requirements.txt

# Generate everything for all databases
python -m generator.main --all

# Generate only for specific database
python -m generator.main --db mssql

# Generate only schema
python -m generator.main --schema

# Generate only seed data
python -m generator.main --seed
```

### Running Tests

```bash
# Emulator tests
cd emulator && pytest

# DB-Assets tests
cd db-assets && pytest

# Orchestrator tests
cd orchestrator && pytest
```

## Next Steps

### High Priority

1. **End-to-End Integration Testing**
   - Test the full flow: Orchestrator → LoadGen → Emulator → Database
   - Verify stats collection during actual load tests
   - Test stats file retrieval and analysis

2. **Orchestrator Completion**
   - Implement test execution workflow
   - Add emulator stats retrieval integration
   - Implement comparison reporting (baseline vs with-agent)

3. **Docker Deployment**
   - Complete docker-compose for all services
   - Add database containers for each supported DB type
   - Network configuration for multi-machine testing

### Medium Priority

4. **JMeter Integration**
   - Test generated JMX files with LoadGen service
   - Verify parameterized queries execute correctly
   - Add DB connection pool configuration

5. **Reporting**
   - Create performance comparison reports
   - Add visualization for stats data
   - Export to standard formats (CSV, PDF)

6. **Additional Database Support**
   - Test seed data loading on Oracle and DB2
   - Verify dialect-specific SQL generation
   - Add connection string configuration

### Lower Priority

7. **UI Dashboard**
   - Web interface for test management
   - Real-time stats visualization
   - Historical test comparison

8. **Agent Detection**
   - Auto-detect installed security agents
   - Collect agent-specific metrics
   - Agent configuration validation

## API Quick Reference

### Emulator Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/api/v1/config` | GET/POST | Configuration |
| `/api/v1/tests/start` | POST | Start test with stats |
| `/api/v1/tests/{id}` | GET | Get test status |
| `/api/v1/tests/{id}/stop` | POST | Stop test, save stats |
| `/api/v1/stats/system` | GET | Current system stats |
| `/api/v1/stats/recent` | GET | Recent N samples |
| `/api/v1/stats/all` | GET | All stats from file |
| `/api/v1/operations/cpu` | POST | Execute CPU load |
| `/api/v1/operations/mem` | POST | Execute memory load |
| `/api/v1/operations/disk` | POST | Execute disk I/O |
| `/api/v1/operations/net` | POST | Execute network load |
| `/api/v1/operations/file` | POST | Execute file operation |

### Example: Start a Test with Stats Collection

```bash
curl -X POST http://localhost:8080/api/v1/tests/start \
  -H "Content-Type: application/json" \
  -d '{
    "test_run_id": "run-001",
    "scenario_id": "cpu-heavy",
    "mode": "calibration",
    "collect_interval_sec": 0.5,
    "thread_count": 4,
    "duration_sec": 60,
    "operation": {
      "cpu": {"duration_ms": 1000, "intensity": 0.8}
    }
  }'
```

### Example: Retrieve Stats After Test

```bash
# Get all stats from saved file
curl "http://localhost:8080/api/v1/stats/all?test_run_id=run-001"
```

## Configuration

### Emulator Config

```json
{
  "input_folders": {
    "normal": "/path/to/normal/files",
    "confidential": "/path/to/confidential/files"
  },
  "output_folders": ["/path/to/output"],
  "partner": {
    "fqdn": "partner-host",
    "port": 8080
  },
  "stats": {
    "output_dir": "./stats",
    "max_memory_samples": 10000,
    "default_interval_sec": 1.0
  }
}
```

## Known Issues

1. **FK Constraints Disabled**: Foreign key constraints are not enforced in generated schemas to simplify seed data loading. Data integrity relies on generator logic.

2. **Large Seed Data**: Generating seed data for all 201 tables takes significant time. Use `--db` flag to generate for specific database only.

3. **Windows Path Handling**: Some scripts assume Windows paths. May need adjustment for Linux deployment.

## Contributing

- Specifications must be updated BEFORE code changes
- Run tests before committing
- Follow existing code patterns (dataclasses for models, FastAPI for APIs)
