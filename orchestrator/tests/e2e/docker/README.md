# Docker-based E2E Testing

This directory contains Docker-based end-to-end tests for the Agent Performance Testing Framework.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Test Host                                 │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                  pytest (E2E tests)                       │   │
│  │                                                           │   │
│  │  - Creates workflow state in DB                          │   │
│  │  - Calls container APIs to simulate orchestration        │   │
│  │  - Verifies results stored correctly                     │   │
│  └──────────────────────────────────────────────────────────┘   │
│                              │                                   │
└──────────────────────────────┼───────────────────────────────────┘
                               │ HTTP
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Docker Network (172.20.0.0/16)               │
│                                                                  │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐       │
│  │   PostgreSQL  │  │  Emulator 1   │  │  Emulator 2   │       │
│  │               │  │               │  │               │       │
│  │  Port: 5432   │  │ :8080 Emulator│  │ :8080 Emulator│       │
│  │  (ext: 5433)  │  │ :8085 Agent   │  │ :8086 Agent   │       │
│  │               │  │ (ext: 8081,   │  │ (ext: 8082,   │       │
│  │               │  │       8085)   │  │       8086)   │       │
│  │  172.20.0.5   │  │  172.20.0.10  │  │  172.20.0.11  │       │
│  └───────────────┘  └───────────────┘  └───────────────┘       │
│                                                                  │
│  ┌───────────────┐                                              │
│  │   LoadGen 1   │                                              │
│  │               │                                              │
│  │ :8090 LoadGen │                                              │
│  │ (ext: 8090)   │                                              │
│  │               │                                              │
│  │  172.20.0.20  │                                              │
│  └───────────────┘                                              │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Components

### 1. PostgreSQL (e2e-postgres)
- Database for storing test data and results
- Port: 5432 (internal), 5433 (external)
- Pre-seeded with test data via `E2ETestDataSeeder`

### 2. Emulator Containers (e2e-emulator-1, e2e-emulator-2)
Each emulator container runs two servers:

**Emulator Server (port 8080)**
- Simulates CPU load generation
- Endpoints: `/health`, `/status`, `/start`, `/stop`, `/calibration`, `/reset`

**Agent Simulator (port 8085/8086)**
- Simulates security agent package
- Endpoints: `/install`, `/uninstall`, `/verify`, `/start`, `/stop`, `/metrics`, `/reset`

### 3. Load Generator (e2e-loadgen-1)
- Simulates JMeter load testing
- Sends HTTP requests to emulator containers
- Endpoints: `/health`, `/start`, `/stop/{port}`, `/status/{port}`, `/result/{port}`

## Quick Start

```bash
# Start containers
cd tests/e2e/docker
docker-compose up -d

# Wait for containers to be healthy
docker-compose ps

# Run E2E tests
pytest tests/e2e/docker/ --e2e-docker -v

# Stop containers
docker-compose down
```

## Test Flow

The full E2E test simulates the complete orchestration flow:

```
1. Create Execution & Workflow State
   └── Store in PostgreSQL

2. Set Package List
   └── base_package_lst = [{agent package}]

3. Restore Baseline (Snapshot)
   └── POST /reset to emulator and agent

4. Install Packages
   └── POST /install to agent simulator

5. Verify Packages
   └── GET /verify from agent simulator
   └── Update base_package_lst_measured

6. Start Emulator + Agent Load
   └── POST /start to emulator
   └── POST /start to agent

7. Run Load Test
   └── POST /start to loadgen
   └── Wait for completion
   └── GET /result from loadgen

8. Collect Results
   └── GET /calibration from emulator
   └── GET /metrics from agent
   └── Compress and store in *_device_*_blob

9. Mark Phase Complete
   └── Update workflow state
```

## Snapshot Simulation

Docker container restart simulates snapshot restore:

```python
# In real orchestration:
await snapshot_manager.restore_snapshot(target_id, baseline_id)

# In Docker E2E:
await client.post(f"{emulator_url}/reset")
await client.post(f"{agent_url}/reset")
```

This clears all runtime state but preserves "installed" software.

## Agent Package Simulation

The agent simulator provides full package lifecycle:

```python
# Install agent
POST /install
{
    "version": "6.50.14358",
    "agent_id": 101,
    "agent_name": "TestSecurityAgent"
}

# Verify installation (simulates version_check_command)
GET /verify
→ {"is_installed": true, "version": "6.50.14358"}

# Start agent load (simulates agent CPU usage)
POST /start
{
    "thread_count": 4,
    "cpu_target_percent": 30.0,
    "duration_sec": 60
}

# Get metrics
GET /metrics
→ {"total_iterations": 1000, "avg_iteration_time_ms": 25.5, ...}
```

## Test Data Seeding

The `E2ETestDataSeeder` creates:

1. **Lab** - docker-e2e-lab
2. **Hardware Profile** - 4 CPU, 8GB RAM
3. **Servers** - 2 targets, 1 loadgen
4. **Baseline** - Container restart baseline
5. **Package Groups** - emulator, jmeter, agent
6. **Scenario** - Pre-calibrated for LOW/MEDIUM/HIGH
7. **Test Run** - With targets mapped to loadgen
8. **Calibration Results** - Pre-seeded thread counts

## Running Individual Tests

```bash
# Health checks only
pytest tests/e2e/docker/test_docker_e2e.py::TestDockerE2ESetup --e2e-docker -v

# Agent installation tests
pytest tests/e2e/docker/test_full_orchestration.py::TestAgentInstallation --e2e-docker -v

# Full phase execution
pytest tests/e2e/docker/test_full_orchestration.py::TestFullPhaseExecution --e2e-docker -v

# Multi-target tests
pytest tests/e2e/docker/test_full_orchestration.py::TestMultiTargetExecution --e2e-docker -v
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `E2E_DATABASE_URL` | postgresql+asyncpg://e2e_user:e2e_password@localhost:5433/agent_perf_e2e | Database URL |
| `EMULATOR_1_HOST` | localhost | Emulator 1 host |
| `EMULATOR_1_PORT` | 8081 | Emulator 1 port |
| `EMULATOR_2_HOST` | localhost | Emulator 2 host |
| `EMULATOR_2_PORT` | 8082 | Emulator 2 port |
| `AGENT_1_HOST` | localhost | Agent 1 host |
| `AGENT_1_PORT` | 8085 | Agent 1 port |
| `AGENT_2_HOST` | localhost | Agent 2 host |
| `AGENT_2_PORT` | 8086 | Agent 2 port |
| `LOADGEN_HOST` | localhost | Load generator host |
| `LOADGEN_PORT` | 8090 | Load generator port |

## Troubleshooting

### Containers not starting
```bash
docker-compose logs emulator-1
docker-compose logs loadgen-1
```

### Database connection issues
```bash
docker-compose exec postgres psql -U e2e_user -d agent_perf_e2e -c "SELECT 1"
```

### Reset all containers
```bash
docker-compose down -v
docker-compose up -d --build
```

## Adding New Tests

1. Create test file in `tests/e2e/docker/`
2. Mark with `@pytest.mark.e2e_docker`
3. Use provided fixtures: `emulator_1_url`, `agent_1_url`, `loadgen_url`, `seeded_data`, `db_session`
4. Run with `--e2e-docker` flag
