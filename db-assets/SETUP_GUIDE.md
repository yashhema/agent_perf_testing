# Agent Performance Measurement - Setup Guide

## Database Name
```
agent_performance_measurement
```

## Quick Start (SQL Server)

```powershell
# Step 1: Generate all files
.\setup_and_run.ps1 -Action generate -DbType mssql

# Step 2: Setup database (creates DB, tables, seed data)
.\setup_and_run.ps1 -Action setup-db -DbType mssql

# Step 3: Run JMeter tests
.\setup_and_run.ps1 -Action run-db-test -DbType mssql
```

---

## Prerequisites

### 1. Python Environment
```powershell
cd db-assets
pip install -r requirements.txt
```

### 2. SQL Server
- SQL Server running locally (or remote)
- Windows Authentication (trusted connection) or SQL authentication
- For named instance: `localhost\SQLEXPRESS`

### 3. JMeter
- Download: https://jmeter.apache.org/download_jmeter.cgi
- Extract to: `C:\apache-jmeter-5.x\`

### 4. SQL Server JDBC Driver
- Download: https://docs.microsoft.com/en-us/sql/connect/jdbc/download-microsoft-jdbc-driver-for-sql-server
- Copy `mssql-jdbc-*.jar` to `C:\apache-jmeter-5.x\lib\`

---

## Step-by-Step Instructions

### Step 1: Generate All Files

```powershell
cd C:\OfficeWork\Claude_understanding\FinalDocs\agent_perf_testing\db-assets

# Generate for SQL Server
python -m generator.main schema -d mssql
python -m generator.main seed -d mssql
python -m generator.main queries -d mssql
python -m generator.main jmx -d mssql

# Or generate everything at once
python -m generator.main all -d mssql
```

**Output Files:**
```
output/mssql/
├── schema/
│   ├── 00_create_database.sql    <- Creates agent_performance_measurement
│   ├── 01_create_tables.sql
│   ├── 02_create_indexes.sql
│   ├── 03_create_constraints.sql
│   └── 04_create_users.sql
├── seed/
│   └── seed_data.sql             <- INSERT statements
├── params/                        <- CSV files with ACTUAL seed values
│   ├── customer_ids.csv
│   ├── order_ids.csv
│   ├── patient_ids.csv
│   ├── account_ids.csv
│   ├── order_search_params.csv
│   ├── transaction_params.csv
│   ├── update_status_params.csv
│   ├── ddl_test_tables.csv       <- DDL only on test tables
│   ├── temp_users.csv            <- Temp users for load testing
│   └── ...
└── queries/
    ├── select/
    ├── insert/
    ├── update/
    ├── delete/
    └── ...

output/jmx/
├── server-normal.jmx
├── server-file-heavy.jmx
├── server-file-heavy_withconfidential.jmx
└── db-load-mssql.jmx
```

### Step 2: Setup SQL Server Database

**Option A: Using SQLCMD (Command Line)**
```powershell
# Connect to SQL Server (Windows Auth)
# Run scripts in order:

sqlcmd -S localhost -E -i "output\mssql\schema\00_create_database.sql"
sqlcmd -S localhost -d agent_performance_measurement -E -i "output\mssql\schema\01_create_tables.sql"
sqlcmd -S localhost -d agent_performance_measurement -E -i "output\mssql\schema\02_create_indexes.sql"
sqlcmd -S localhost -d agent_performance_measurement -E -i "output\mssql\schema\03_create_constraints.sql"
sqlcmd -S localhost -d agent_performance_measurement -E -i "output\mssql\schema\04_create_users.sql"
sqlcmd -S localhost -d agent_performance_measurement -E -i "output\mssql\seed\seed_data.sql"
```

**Option B: Using SSMS (SQL Server Management Studio)**
1. Open SSMS, connect to your SQL Server
2. Open and run `00_create_database.sql` (connected to master)
3. Switch to `agent_performance_measurement` database
4. Run scripts 01 through 04 in order
5. Run `seed_data.sql` to insert test data

### Step 3: Configure JMeter

1. **Copy JDBC Driver**
   - Copy `mssql-jdbc-12.x.jar` to `C:\apache-jmeter-5.x\lib\`

2. **Open JMX File**
   - Open `output/jmx/db-load-mssql.jmx` in JMeter

3. **Update JDBC Connection**
   - Find "JDBC Connection Configuration" element
   - Update connection settings:
     ```
     Database URL: jdbc:sqlserver://localhost;databaseName=agent_performance_measurement;integratedSecurity=true
     Driver Class: com.microsoft.sqlserver.jdbc.SQLServerDriver
     ```

4. **Update CSV Paths**
   - Find "CSV Data Set Config" elements
   - Ensure paths point to your `output/mssql/params/` folder

### Step 4: Run JMeter Tests

**For Database Load Test:**
```powershell
# GUI Mode (for testing/debugging)
C:\apache-jmeter-5.x\bin\jmeter.bat -t "output\jmx\db-load-mssql.jmx"

# Non-GUI Mode (for actual load testing)
C:\apache-jmeter-5.x\bin\jmeter.bat -n -t "output\jmx\db-load-mssql.jmx" -l results.jtl
```

**For Emulator Tests:**
```powershell
# First, start 2 emulator instances:
# Terminal 1:
python -m emulator.app --port 8080

# Terminal 2:
python -m emulator.app --port 8081

# Then run JMeter:
C:\apache-jmeter-5.x\bin\jmeter.bat -t "output\jmx\server-normal.jmx"
```

---

## Key Points

### Single-Pass Generation
- Seed data and params are generated **together**
- Params CSV files contain **actual values** from seed data
- This ensures JMeter queries reference data that **exists** in the database

### DDL Test Tables
- DDL operations (CREATE/ALTER/DROP) only on `ddl_test_NNN` tables
- **Never** on the 200 data tables (would break queries)
- See `params/ddl_test_tables.csv`

### Test Users
| User | Type | Purpose |
|------|------|---------|
| test_user_1 | Config (permanent) | Readonly tests |
| test_user_2 | Config (permanent) | Read/write tests |
| test_admin | Config (permanent) | Admin tests |
| load_user_NNN | Temp (created/dropped) | User management testing |

---

## Troubleshooting

### "Cannot connect to SQL Server"
- Check SQL Server is running: `Get-Service MSSQLSERVER`
- Check TCP/IP is enabled in SQL Server Configuration Manager
- Try: `sqlcmd -S localhost -E -Q "SELECT @@VERSION"`

### "JDBC Driver not found"
- Ensure `mssql-jdbc-*.jar` is in JMeter's `lib` folder
- Restart JMeter after adding the driver

### "Table does not exist"
- Run all schema scripts in order (00 through 04)
- Ensure you're connected to `agent_performance_measurement` database

### "Parameter value not found"
- Regenerate seed data: `python -m generator.main seed -d mssql`
- Params are now generated with seed data (single-pass)

---

## File Reference

| File | Purpose |
|------|---------|
| `setup_and_run.ps1` | PowerShell setup script |
| `config.yaml` | Generator configuration |
| `generator/` | Python generator package |
| `output/` | Generated files |

---

## Support

For issues, check:
1. Python errors: `python -m generator.main info`
2. SQL errors: Check SSMS for detailed error messages
3. JMeter errors: Check jmeter.log in JMeter's bin folder
