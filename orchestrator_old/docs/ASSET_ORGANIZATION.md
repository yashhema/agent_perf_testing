# Asset Organization Plan

## Overview

This document organizes the folder structure and approach for creating test assets.

---

## Folder Structure

```
agent_perf_testing/
│
├── orchestrator/                    # Main application (existing)
│   └── app/
│       ├── jmeter/
│       │   └── templates/           # JMX template files
│       │       ├── server-normal.jmx
│       │       ├── server-file-heavy.jmx
│       │       └── db-load.jmx
│       │
│       └── db/
│           └── queries/             # Pre-defined SQL queries for JMeter
│               ├── crud.sql
│               ├── complex.sql
│               ├── bulk.sql
│               └── sensitive.sql
│
├── ConfidentialData/                # Source for realistic confidential data
│   └── (existing data files)
│
├── db-assets/                       # NEW: Database schema & seed data
│   ├── config.yaml                  # Configuration (table counts, record counts)
│   │
│   ├── schemas/                     # Schema definitions (DDL)
│   │   ├── common/                  # Database-agnostic definitions
│   │   │   ├── 01_ecommerce.yaml    # E-commerce table definitions
│   │   │   ├── 02_banking.yaml      # Banking table definitions
│   │   │   ├── 03_healthcare.yaml   # Healthcare table definitions
│   │   │   └── 04_shared.yaml       # Common/shared tables
│   │   │
│   │   └── generated/               # Generated SQL (per database type)
│   │       ├── postgresql/
│   │       │   └── schema.sql
│   │       ├── mysql/
│   │       │   └── schema.sql
│   │       └── mssql/
│   │           └── schema.sql
│   │
│   ├── seed-data/                   # Data generation (separate from schema)
│   │   ├── generators/              # Data generator scripts
│   │   │   ├── generate_data.py     # Main generator
│   │   │   └── faker_providers.py   # Custom Faker providers
│   │   │
│   │   └── generated/               # Generated INSERT statements
│   │       ├── postgresql/
│   │       │   └── seed.sql
│   │       ├── mysql/
│   │       │   └── seed.sql
│   │       └── mssql/
│   │           └── seed.sql
│   │
│   └── README.md                    # How to generate and use
│
└── packages/                        # NEW: Deployable packages
    ├── cpu-emulator/
    │   ├── src/                     # Emulator source code
    │   ├── build/                   # Build scripts
    │   └── dist/                    # Built packages
    │       ├── cpu-emulator-linux.tar.gz
    │       └── cpu-emulator-windows.zip
    │
    └── test-files/                  # Files for emulator to serve
        ├── small/                   # 1KB - 100KB files
        └── large/                   # 1MB - 100MB files
```

---

## Configuration (`db-assets/config.yaml`)

```yaml
# Database Asset Configuration
# All counts are configurable for different environments

schema:
  # Total tables = ecommerce + banking + healthcare + shared
  table_counts:
    ecommerce: 60      # Products, orders, inventory
    banking: 60        # Accounts, transactions, loans
    healthcare: 60     # Patients, records, prescriptions
    shared: 20         # Users, audit, config
    total: 200         # Calculated: 60+60+60+20

  # Tables containing confidential/sensitive data
  confidential_tables:
    - patient_records
    - patient_ssn
    - credit_cards
    - bank_accounts
    - user_credentials

seed_data:
  records_per_table: 10000    # 10K records per table

  # Batch size for inserts (adjust based on DB/Docker memory)
  batch_size: 1000

  # Source for realistic confidential data
  confidential_data_source: "../ConfidentialData"

# Database-specific settings
databases:
  postgresql:
    schema_file: "schemas/generated/postgresql/schema.sql"
    seed_file: "seed-data/generated/postgresql/seed.sql"

  mysql:
    schema_file: "schemas/generated/mysql/schema.sql"
    seed_file: "seed-data/generated/mysql/seed.sql"

  mssql:
    schema_file: "schemas/generated/mssql/schema.sql"
    seed_file: "seed-data/generated/mssql/seed.sql"
```

---

## Schema Definition Approach

### Why YAML definitions?

Instead of writing SQL directly, we define tables in YAML format:
- **Database-agnostic**: One definition, generate for any DB
- **Configurable**: Easy to add/remove tables
- **Type mapping**: Handle type differences between databases

### Example Table Definition (`schemas/common/01_ecommerce.yaml`)

```yaml
domain: ecommerce
tables:
  - name: products
    confidential: false
    columns:
      - name: product_id
        type: uuid
        primary_key: true
      - name: name
        type: varchar(255)
        nullable: false
      - name: description
        type: text
        nullable: true
      - name: price
        type: decimal(10,2)
        nullable: false
      - name: category_id
        type: uuid
        foreign_key: categories.category_id
      - name: created_at
        type: timestamp
        default: CURRENT_TIMESTAMP
    indexes:
      - columns: [category_id]
      - columns: [name]

  - name: credit_cards
    confidential: true    # Marked as confidential
    columns:
      - name: card_id
        type: uuid
        primary_key: true
      - name: card_number
        type: varchar(16)
        nullable: false
        sensitive: true   # Will use data from ConfidentialData
      - name: cvv
        type: varchar(4)
        sensitive: true
      - name: expiry_date
        type: date
      - name: cardholder_name
        type: varchar(255)
        sensitive: true
```

### Type Mapping

| YAML Type | PostgreSQL | MySQL | SQL Server |
|-----------|------------|-------|------------|
| `uuid` | `UUID` | `CHAR(36)` | `UNIQUEIDENTIFIER` |
| `varchar(n)` | `VARCHAR(n)` | `VARCHAR(n)` | `NVARCHAR(n)` |
| `text` | `TEXT` | `TEXT` | `NVARCHAR(MAX)` |
| `integer` | `INTEGER` | `INT` | `INT` |
| `bigint` | `BIGINT` | `BIGINT` | `BIGINT` |
| `decimal(p,s)` | `DECIMAL(p,s)` | `DECIMAL(p,s)` | `DECIMAL(p,s)` |
| `boolean` | `BOOLEAN` | `TINYINT(1)` | `BIT` |
| `timestamp` | `TIMESTAMP` | `DATETIME` | `DATETIME2` |
| `date` | `DATE` | `DATE` | `DATE` |
| `json` | `JSONB` | `JSON` | `NVARCHAR(MAX)` |

---

## Separation of Concerns

### 1. Schema Creation (DDL)
- Creates tables, indexes, constraints
- Run once per environment
- Lightweight, fast to execute
- **File**: `schema.sql`

### 2. Seed Data (DML)
- INSERTs 10K records per table
- Heavy operation, may need batching
- May timeout on resource-constrained Docker
- **File**: `seed.sql` (or multiple files)

### Why Separate?

```
Docker with limited resources:
├── Can handle: CREATE TABLE (200 tables) - seconds
└── May struggle: INSERT 2M records - minutes/timeout

Separation allows:
├── Always run schema.sql first
├── Run seed.sql in batches if needed
└── Or skip seeding entirely for quick tests
```

---

## Generation Workflow

```
┌─────────────────────────────────────────────────────────────┐
│                    GENERATION WORKFLOW                       │
└─────────────────────────────────────────────────────────────┘

1. CONFIGURE
   └── Edit config.yaml (table counts, record counts)

2. GENERATE SCHEMA
   └── python generate_schema.py
       ├── Reads: schemas/common/*.yaml
       ├── Writes: schemas/generated/{postgresql,mysql,mssql}/schema.sql
       └── Respects: config.yaml table counts

3. GENERATE SEED DATA
   └── python generate_seed.py
       ├── Reads: schemas/common/*.yaml + ConfidentialData/
       ├── Writes: seed-data/generated/{postgresql,mysql,mssql}/seed.sql
       └── Respects: config.yaml record counts, batch sizes

4. APPLY TO DATABASE
   └── Manual or via orchestrator
       ├── Step 1: Run schema.sql (creates structure)
       └── Step 2: Run seed.sql (populates data)
```

---

## Summary

| Aspect | Decision |
|--------|----------|
| Table count | 200 (configurable in config.yaml) |
| Records per table | 10K (configurable) |
| Schema vs Data | Separate files |
| Database support | PostgreSQL, MySQL, SQL Server |
| Definition format | YAML (database-agnostic) |
| Confidential data source | `ConfidentialData/` folder |
| Schema location | `db-assets/schemas/` |
| Seed data location | `db-assets/seed-data/` |

---

## Next Steps (In Order)

1. **Create folder structure** - Set up `db-assets/` directory
2. **Define config.yaml** - Lock in configuration
3. **Create YAML schema definitions** - 200 tables across 4 domains
4. **Create schema generator** - YAML → SQL for each DB type
5. **Create seed data generator** - Using Faker + ConfidentialData
6. **Create JMX templates** - 3 templates with proper load mixes
7. **Create CPU emulator package** - Web service + test files
8. **Create DB entries** - Wire everything together in orchestrator DB
