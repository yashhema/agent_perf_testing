# Java Emulator — Implementation & Deployment Plan

## Goal
Replace the Python emulator with a Java (Spring Boot) emulator that is API-compatible. The Java version solves the GIL problem: real OS threads can burn CPU in parallel, enabling steady-state load for calibration.

---

## Target VMs

| Role | Hostname | IP | OS | VMID | Snapshot |
|------|----------|----|----|------|----------|
| Linux target | target-rky-01 | 10.0.0.92 | Rocky 9.7 | 410 | clean-rocky97 |
| Windows target | TARGET-WIN-01 | 10.0.0.91 | Windows 2022 | 321 | clean-win2022 |

Both VMs: 4 vCPU, 8 GB RAM, 40/60 GB SSD.

---

## Phase 1: Validate API Spec Against Python Code

**Goal**: Ensure JAVA_EMULATOR_API_SPEC.md matches the actual Python implementation. Reduce validation errors to <5%.

**Method**: Read every Python router, model, and operation file. Compare:
- Endpoint paths & HTTP methods
- Request field names, types, defaults, constraints
- Response field names, types, structure
- Error responses and status codes
- Edge cases (missing pool, unknown agent, etc.)

**Deliverable**: Updated JAVA_EMULATOR_API_SPEC.md with corrections, or a validation report showing <5% discrepancy.

---

## Phase 2: Implement Java Emulator

### 2.1 Project Setup
- Spring Boot 3.x with embedded Tomcat
- Java 17 (LTS)
- Build tool: Maven (pom.xml)
- Dependencies: spring-boot-starter-web, oshi-core (system stats), jackson, lombok
- Port: 8080 (application.yml)

### 2.2 Package Structure
```
emulator_java/
├── pom.xml
├── src/main/java/com/emulator/
│   ├── EmulatorApplication.java
│   ├── controller/
│   │   ├── HealthController.java          GET /health
│   │   ├── ConfigController.java          GET/POST /api/v1/config, POST/GET/DELETE /api/v1/config/pool
│   │   ├── OperationsController.java      POST /api/v1/operations/{cpu,mem,disk,net,file,work,suspicious}
│   │   ├── TestsController.java           POST /api/v1/tests/start, GET /api/v1/tests/, GET /api/v1/tests/{id}, POST /api/v1/tests/{id}/stop
│   │   ├── StatsController.java           GET /api/v1/stats/{system,recent,all,iterations}, POST /api/v1/stats/iterations/clear
│   │   └── AgentController.java           GET /api/v1/agent/{type}, POST /api/v1/agent/{install,uninstall,service}
│   ├── model/
│   │   ├── request/    (all request DTOs matching Python Pydantic models)
│   │   └── response/   (all response DTOs matching Python response models)
│   ├── service/
│   │   ├── ConfigService.java             Config + pool state management
│   │   ├── MemoryPoolService.java         byte[] allocation, touch, destroy
│   │   ├── CpuBurnService.java            Real CPU burn via Math.sin/sqrt loops
│   │   ├── WorkService.java               Combined cpu_burn + pool_touch
│   │   ├── MemoryOperationService.java    Per-request alloc/touch/dealloc
│   │   ├── DiskOperationService.java      Temp file read/write/mixed
│   │   ├── NetworkOperationService.java   TCP socket send/receive
│   │   ├── FileOperationService.java      Source file assembly + output
│   │   ├── SuspiciousOperationService.java OS-level suspicious activities
│   │   ├── StatsCollectorService.java     Background ScheduledExecutorService
│   │   ├── TestManagerService.java        Test lifecycle + worker threads
│   │   └── AgentService.java             ProcessBuilder for systemctl/sc
│   └── util/
│       └── PlatformUtil.java              OS detection, path resolution
├── src/main/resources/
│   └── application.yml                    server.port=8080
└── data/                                  (copied from Python emulator)
    ├── normal/
    └── confidential/
```

### 2.3 Critical Implementation Details

**CPU Burn** (`/operations/cpu` and `/operations/work`):
```java
// Tight loop that actually consumes CPU
long deadline = System.nanoTime() + (long)(cpuMs * 1_000_000L * intensity);
double x = 1.0;
while (System.nanoTime() < deadline) {
    x = Math.sin(x) + Math.sqrt(x + 1) + Math.cos(x);
}
// With intensity < 1.0: burn for (cpuMs * intensity), sleep for remainder
```

**Memory Pool** (shared `byte[]`):
```java
// Singleton, allocated once via POST /config/pool
private volatile byte[] pool;  // e.g., 1 GB
// Touch: sequential or random page access
// All Tomcat threads share the same array — no GIL, true parallelism
```

**Stats Collection** (oshi library):
```java
// ScheduledExecutorService runs at collect_interval_sec
// Reads: SystemInfo.getHardware().getProcessor().getSystemCpuLoad()
// Memory: GlobalMemory.getAvailable(), getTotal()
// Disk: HWDiskStore.getReadBytes/getWriteBytes (delta-based rates)
// Network: NetworkIF.getBytesSent/getBytesRecv (delta-based rates)
// Per-process: OSProcess.getProcessCpuLoadBetweenTicks(), getResidentSetSize()
```

---

## Phase 3: Build & Package

### 3.1 Build Fat JAR
```bash
cd emulator_java
mvn clean package -DskipTests
# Produces: target/emulator-java-1.0.0.jar
```

### 3.2 Create Deployment Packages

**Linux package** (`emulator-java-linux.tar.gz`):
```
emulator-java-linux/
├── emulator.jar                    # Fat JAR
├── start.sh                        # Launch script (replaces Python start.sh)
├── data/
│   ├── normal/                     # Same source files
│   └── confidential/               # Same source files
```
- Linux prerequisite script installs OpenJDK 17 via dnf/yum
- JRE NOT bundled (Linux package managers handle this well)

**Windows package** (`emulator-java-windows.tar.gz`):
```
emulator-java-windows/
├── emulator.jar                    # Fat JAR
├── start.ps1                       # Launch script (replaces Python start.ps1)
├── jre/                            # Bundled JRE 17 (like Python is bundled now)
│   └── (extracted Adoptium JRE 17) # ~180 MB
├── data/
│   ├── normal/
│   └── confidential/
```
- Windows package includes full JRE (no internet dependency, like Python installer is bundled now)
- start.ps1 uses `.\jre\bin\java.exe -jar emulator.jar`

### 3.3 Startup Scripts

**start.sh (Linux)**:
```bash
#!/bin/bash
EMULATOR_DIR="/opt/emulator"
cd "$EMULATOR_DIR"
mkdir -p /opt/emulator/output /opt/emulator/stats

# Firewall
which ufw >/dev/null 2>&1 && ufw allow 8080/tcp
which firewall-cmd >/dev/null 2>&1 && firewall-cmd --add-port=8080/tcp --permanent && firewall-cmd --reload

# Kill existing
fuser -k 8080/tcp 2>/dev/null || true
sleep 1

# Start Java emulator
nohup java -Xmx6g -jar "$EMULATOR_DIR/emulator.jar" \
    --server.port=8080 \
    > /opt/emulator/emulator.log 2>&1 &

# Health check (up to 30s — Spring Boot takes longer to start than uvicorn)
for i in $(seq 1 30); do
    if curl -sf http://localhost:8080/health > /dev/null 2>&1; then
        echo "Emulator started successfully"
        exit 0
    fi
    sleep 1
done
echo "WARNING: Health check failed after 30s"
exit 1
```

**start.ps1 (Windows)**:
```powershell
$emulatorDir = "C:\emulator"
Set-Location $emulatorDir
New-Item -ItemType Directory -Force -Path "$emulatorDir\output" | Out-Null
New-Item -ItemType Directory -Force -Path "$emulatorDir\stats" | Out-Null

# Firewall
$rule = Get-NetFirewallRule -DisplayName "Emulator API" -ErrorAction SilentlyContinue
if (-not $rule) {
    New-NetFirewallRule -DisplayName "Emulator API" -Direction Inbound -Protocol TCP -LocalPort 8080 -Action Allow
}

# Kill existing java on port 8080
Get-Process -Name java -ErrorAction SilentlyContinue | Stop-Process -Force

# Find JRE (bundled or system)
$javaExe = "$emulatorDir\jre\bin\java.exe"
if (-not (Test-Path $javaExe)) {
    $javaExe = (Get-Command java -ErrorAction SilentlyContinue).Source
}

# Start via WMI (detached from WinRM session)
$cmd = "cmd.exe /c `"$javaExe -Xmx6g -jar $emulatorDir\emulator.jar --server.port=8080 > $emulatorDir\emulator.log 2> $emulatorDir\emulator_err.log`""
$process = ([wmiclass]"Win32_Process").Create($cmd, $emulatorDir, $null)

# Health check (30s)
for ($i = 0; $i -lt 30; $i++) {
    try {
        $r = Invoke-WebRequest -Uri "http://localhost:8080/health" -UseBasicParsing -TimeoutSec 2
        if ($r.StatusCode -eq 200) { Write-Host "Emulator started"; exit 0 }
    } catch {}
    Start-Sleep -Seconds 1
}
Write-Host "WARNING: Health check failed after 30s"
exit 1
```

---

## Phase 4: Prerequisite Scripts

**Linux** (`prerequisites/rhel/java_emulator.sh`):
```bash
#!/bin/bash
# Install OpenJDK 17 JRE
if ! java -version 2>&1 | grep -q "17"; then
    dnf install -y java-17-openjdk-headless
fi
java -version
```

**Windows**: No prerequisite script needed — JRE is bundled in the package (like Python installer is bundled).

---

## Phase 5: Database & Package Registration

Register new package group members in the DB (like the Python emulator entries):

```sql
-- New package group for Java emulator
INSERT INTO package_groups (name, description) VALUES ('java-emulator', 'Java emulator for server targets');

-- Linux member
INSERT INTO package_group_members (
    package_group_id, os_match_string, package_path,
    root_install_path, extraction_command, install_command,
    run_command, status_command, prereq_script
) VALUES (
    @java_emu_grp_id, 'rhel/9/.*',
    'artifacts/packages/emulator-java-linux.tar.gz',
    '/opt/emulator-pkg/emulator-java-linux.tar.gz',
    'mkdir -p /opt/emulator && tar -xzf /opt/emulator-pkg/emulator-java-linux.tar.gz -C /opt/emulator --strip-components=1',
    NULL,
    'bash /opt/emulator/start.sh',
    'curl -sf http://localhost:8080/health',
    'rhel/java_emulator.sh'
);

-- Windows member
INSERT INTO package_group_members (
    package_group_id, os_match_string, package_path,
    root_install_path, extraction_command, install_command,
    run_command, status_command, prereq_script
) VALUES (
    @java_emu_grp_id, 'windows/2022',
    'artifacts/packages/emulator-java-windows.tar.gz',
    'C:\emulator-pkg\emulator-java-windows.tar.gz',
    'mkdir C:\emulator 2>nul & tar -xzf C:\emulator-pkg\emulator-java-windows.tar.gz -C C:\emulator',
    NULL,
    'powershell -ExecutionPolicy Bypass -File C:\emulator\start.ps1',
    'powershell -Command "(Invoke-WebRequest -Uri http://localhost:8080/health -UseBasicParsing).StatusCode"',
    NULL
);
```

Then update the lab's `emulator_package_grp_id` to point to the new Java emulator group.

---

## Phase 6: Deployment Procedure

### 6.1 Manual Deployment (for initial testing)

**Linux (10.0.0.92)**:
```bash
# From orchestrator machine (10.0.0.82):
# 1. Build package
cd /path/to/emulator_java && mvn clean package -DskipTests
# 2. Create tar.gz
mkdir -p /tmp/emulator-java-linux/data
cp target/emulator-java-1.0.0.jar /tmp/emulator-java-linux/emulator.jar
cp start.sh /tmp/emulator-java-linux/
cp -r data/normal data/confidential /tmp/emulator-java-linux/data/
cd /tmp && tar -czf emulator-java-linux.tar.gz emulator-java-linux/
# 3. Upload & deploy
scp emulator-java-linux.tar.gz root@10.0.0.92:/opt/emulator-pkg/
ssh root@10.0.0.92 "mkdir -p /opt/emulator && tar -xzf /opt/emulator-pkg/emulator-java-linux.tar.gz -C /opt/emulator --strip-components=1"
ssh root@10.0.0.92 "dnf install -y java-17-openjdk-headless"
ssh root@10.0.0.92 "bash /opt/emulator/start.sh"
# 4. Verify
curl http://10.0.0.92:8080/health
```

**Windows (10.0.0.91)**:
```powershell
# 1. Create package with bundled JRE
# Download Adoptium JRE 17: https://adoptium.net/temurin/releases/?version=17
# Extract to emulator-java-windows/jre/
# 2. Create tar.gz (from WSL or Git Bash)
tar -czf emulator-java-windows.tar.gz emulator-java-windows/
# 3. Upload via WinRM/HTTP and extract
# 4. Run start.ps1
```

### 6.2 Automated Deployment (via test_deploy_all.py)

Once packages are in `orchestrator/artifacts/packages/` and DB is configured:
```bash
python test_deploy_all.py emulator-linux   # Deploys Java emulator to Linux
python test_deploy_all.py emulator-windows # Deploys Java emulator to Windows
```

This reuses the existing PackageDeployer pipeline — the orchestrator doesn't care that it's Java.

---

## Phase 7: Testing

### 7.1 Endpoint Validation
```bash
python test_emulator_endpoints.py linux    # All 15 endpoint tests
python test_emulator_endpoints.py windows
```

### 7.2 Steady-State Load Test
```bash
python test_steady_load.py 10.0.0.92 5 60 50   # 5 threads, 60s, 50ms burns
# Expected: CPU 15-50% with <5% spread (vs Python's 0% CPU)
```

### 7.3 Full Orchestrator Test
```bash
# Create new baseline with server-steady template
# Verify calibration converges (unlike Python where it timed out)
```

---

## Execution Order

| Step | Task | Depends On |
|------|------|-----------|
| 1 | Validate API spec vs Python code | — |
| 2 | Implement Java emulator (all 23 endpoints) | Step 1 |
| 3 | Build fat JAR | Step 2 |
| 4 | Download/prepare JRE 17 for Windows bundling | — |
| 5 | Create Linux prerequisite script | — |
| 6 | Create startup scripts (start.sh, start.ps1) | Step 2 |
| 7 | Create deployment packages (tar.gz) | Steps 3, 4, 6 |
| 8 | Deploy to Linux VM (10.0.0.92) | Step 7 |
| 9 | Deploy to Windows VM (10.0.0.91) | Step 7 |
| 10 | Run test_emulator_endpoints.py on both VMs | Steps 8, 9 |
| 11 | Run test_steady_load.py — verify CPU utilization | Step 10 |
| 12 | Register packages in DB | Step 7 |
| 13 | Run test_deploy_all.py (automated pipeline) | Step 12 |

---

## Risk & Mitigations

| Risk | Mitigation |
|------|-----------|
| Spring Boot startup slower than uvicorn | Health check timeout increased to 30s (vs 10s) |
| Fat JAR size large (~50MB + deps) | Still smaller than Python emulator package (86 MB) |
| Windows JRE bundle adds ~180 MB | Similar to bundled Python (110 MB currently) |
| oshi library cross-platform issues | Well-tested library; fallback to JMX MBeans if needed |
| Port 8080 conflict | Same port as Python emulator — only one runs at a time |
| Memory: -Xmx6g + 1GB pool | 8 GB VMs, leaves ~1 GB for OS — sufficient |

---

## Non-Changes (Orchestrator Side)

The orchestrator does NOT need any code changes for the Java emulator because:
1. Same HTTP API on same port (8080)
2. Same JSON request/response structures
3. Same startup mechanism (run_command → start.sh/start.ps1)
4. Same health check endpoint (/health)
5. Same stats collection/retrieval flow
6. JMeter templates unchanged — they call the same REST endpoints

Only the package artifacts and DB package_group entries change.
