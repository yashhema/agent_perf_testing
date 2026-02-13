# Prerequisites to Create Before Testing

## Overview

These are the **assets** that must be created before the orchestrator can execute tests. The orchestrator consumes these assets but does not create them.

---

## 1. CPU Emulator Package

The CPU Emulator is a web service that runs on **target servers** and provides endpoints that simulate various workloads.

### What to Create

```
packages/cpu-emulator/
├── cpu-emulator.tar.gz (or .zip for Windows)
│   ├── emulator                    # Main executable
│   ├── config.yaml                 # Configuration
│   └── startup.sh / startup.ps1    # Startup script
│
└── test-files/                     # Files the emulator downloads
    ├── small-files/                # Small file downloads (1KB - 100KB)
    │   ├── doc-001.pdf
    │   ├── image-001.jpg
    │   └── ...
    └── large-files/                # Large file downloads (1MB - 100MB)
        ├── archive-001.zip
        ├── video-001.mp4
        └── ...
```

### Emulator Endpoints Required

| Endpoint | Purpose | CPU Impact |
|----------|---------|------------|
| `GET /health` | Health check | Minimal |
| `GET /api/v1/stats/system` | CPU/memory metrics | Minimal |
| `POST /api/v1/tests/compute` | CPU-intensive calculation | High |
| `POST /api/v1/tests/memory` | Memory allocation test | Medium |
| `GET /api/v1/tests/file/small` | Download small file | Low |
| `GET /api/v1/tests/file/large` | Download large file | I/O bound |
| `POST /api/v1/tests/anomaly` | Anomalous behavior (slow, error) | Variable |

### Two Types of File Downloads

1. **Small Files (1KB - 100KB)**
   - Simulates typical API responses, thumbnails, config files
   - High frequency, low bandwidth
   - Mix: PDFs, images, JSON files

2. **Large Files (1MB - 100MB)**
   - Simulates file downloads, exports, attachments
   - Lower frequency, high bandwidth
   - Mix: Archives, videos, large documents

---

## 2. JMX Templates

Pre-created JMeter test plans that define the load mix. Thread count is variable; load mix is fixed.

### What to Create

```
app/jmeter/templates/
├── server-normal.jmx          # 99% normal + 1% anomaly
├── server-file-heavy.jmx      # 69% normal + 30% file + 1% anomaly
└── db-load.jmx                # Database load test
```

### Template A: Server Normal Load (`server-normal.jmx`)

Load distribution:
- **99% Normal Requests**: `/api/v1/tests/compute`, `/api/v1/tests/memory`
- **1% Anomalous Requests**: `/api/v1/tests/anomaly`

```
Thread Group: ${THREAD_COUNT} threads, ${DURATION} seconds
├── Random Controller (99%)
│   ├── HTTP Request: POST /api/v1/tests/compute
│   │   └── Body: {"iterations": 1000, "complexity": "medium"}
│   └── HTTP Request: POST /api/v1/tests/memory
│       └── Body: {"allocate_mb": 10, "duration_ms": 100}
│
└── Random Controller (1%)
    └── HTTP Request: POST /api/v1/tests/anomaly
        └── Body: {"type": "slow_response", "delay_ms": 5000}
```

Variables to substitute:
- `${THREAD_COUNT}` - From calibration
- `${TARGET_HOST}` - Target server IP/hostname
- `${TARGET_PORT}` - Emulator port (default: 8080)
- `${DURATION}` - Test duration in seconds
- `${RAMP_UP}` - Ramp-up period in seconds

### Template B: Server File-Heavy Load (`server-file-heavy.jmx`)

Load distribution:
- **69% Normal Requests**: Compute and memory operations
- **30% File Requests**: Small and large file downloads
- **1% Anomalous Requests**: Error/slow responses

```
Thread Group: ${THREAD_COUNT} threads, ${DURATION} seconds
├── Random Controller (69%)
│   ├── HTTP Request: POST /api/v1/tests/compute
│   └── HTTP Request: POST /api/v1/tests/memory
│
├── Random Controller (30%)
│   ├── HTTP Request: GET /api/v1/tests/file/small (70%)
│   └── HTTP Request: GET /api/v1/tests/file/large (30%)
│
└── Random Controller (1%)
    └── HTTP Request: POST /api/v1/tests/anomaly
```

### Template C: Database Load (`db-load.jmx`)

Load distribution:
- **40% Simple CRUD**: INSERT, SELECT by ID, UPDATE, DELETE
- **30% Complex Queries**: JOINs, aggregations, subqueries
- **20% Bulk Operations**: Batch inserts, large result sets
- **10% Sensitive Data Access**: Queries on confidential tables

```
Thread Group: ${THREAD_COUNT} threads, ${DURATION} seconds
├── JDBC Connection Configuration
│   ├── Database URL: ${DB_URL}
│   ├── Driver: ${DB_DRIVER}
│   ├── Username: ${DB_USER}
│   └── Password: ${DB_PASSWORD}
│
├── Random Controller (40% - Simple CRUD)
│   ├── JDBC Request: INSERT INTO orders (...)
│   ├── JDBC Request: SELECT * FROM products WHERE id = ?
│   ├── JDBC Request: UPDATE inventory SET quantity = ...
│   └── JDBC Request: DELETE FROM cart_items WHERE ...
│
├── Random Controller (30% - Complex Queries)
│   ├── JDBC Request: SELECT with 3-table JOIN
│   ├── JDBC Request: Aggregation with GROUP BY
│   └── JDBC Request: Subquery with IN clause
│
├── Random Controller (20% - Bulk Operations)
│   ├── JDBC Request: Batch INSERT (100 rows)
│   └── JDBC Request: SELECT with LIMIT 1000
│
└── Random Controller (10% - Sensitive Data)
    ├── JDBC Request: SELECT * FROM patient_records WHERE ...
    ├── JDBC Request: SELECT * FROM credit_cards WHERE ...
    └── JDBC Request: SELECT * FROM user_ssn WHERE ...
```

Variables to substitute:
- `${THREAD_COUNT}` - From calibration
- `${DB_URL}` - JDBC connection URL
- `${DB_DRIVER}` - JDBC driver class
- `${DB_USER}` - Database username
- `${DB_PASSWORD}` - Database password
- `${DURATION}` - Test duration in seconds

---

## 3. Database Schema (500 Tables)

A comprehensive schema mixing e-commerce, banking, and healthcare domains.

### What to Create

```
app/db/schemas/
├── schema.sql              # Full schema (500 tables)
├── seed-data.sql           # Initial data (10K-50K records/table)
├── indexes.sql             # Performance indexes
└── README.md               # Schema documentation
```

### Domain Distribution (200 Tables Total)

| Domain | Tables | Purpose |
|--------|--------|---------|
| **E-Commerce** | 60 | Products, orders, inventory, reviews |
| **Banking** | 60 | Accounts, transactions, loans, cards |
| **Healthcare** | 60 | Patients, records, prescriptions, billing |
| **Common/Shared** | 20 | Users, addresses, audit logs, configs |

**Confidential Data Source**: `C:\OfficeWork\Claude_understanding\FinalDocs\agent_perf_testing\ConfidentialData`

### E-Commerce Tables (60)

```sql
-- Core entities (15 tables)
products, categories, brands, suppliers, warehouses,
inventory, price_history, product_images, product_reviews, ...

-- Orders & Cart (15 tables)
customers, customer_addresses, shopping_carts, cart_items,
orders, order_items, order_status_history, shipments, ...

-- Payments (15 tables)
payment_methods, payment_transactions, refunds,
invoices, invoice_items, discounts, coupons, ...

-- Marketing & Analytics (15 tables)
campaigns, email_subscribers, wishlists,
page_views, sales_by_day, customer_segments, ...
```

### Banking Tables (60)

```sql
-- Accounts (15 tables)
bank_accounts, account_types, account_holders,
account_status_history, interest_rates, account_limits, ...

-- Transactions (15 tables)
transactions, transaction_types, transfers,
fraud_alerts, transaction_limits, ...

-- Cards (15 tables) [CONFIDENTIAL]
credit_cards, debit_cards, card_transactions,
card_rewards, card_statements, ...

-- Loans & Compliance (15 tables) [CONFIDENTIAL]
loans, loan_applications, loan_payments,
kyc_documents, aml_checks, ...
```

### Healthcare Tables (60)

```sql
-- Patients (15 tables) [CONFIDENTIAL]
patients, patient_demographics, patient_contacts,
patient_insurance, patient_ssn, ...

-- Medical Records (20 tables) [CONFIDENTIAL]
medical_records, diagnoses, procedures,
lab_results, medications, prescriptions, ...

-- Appointments (10 tables)
appointments, providers, provider_schedules,
rooms, waiting_lists, ...

-- Billing (15 tables)
claims, claim_items, payments,
billing_codes, payment_plans, ...
```

### Common/Shared Tables (20)

```sql
-- Users & Auth (8 tables) [CONFIDENTIAL]
users, user_roles, roles, permissions,
user_sessions, user_credentials, api_keys, ...

-- Addresses (5 tables)
addresses, countries, states, cities, ...

-- Audit & Config (7 tables)
audit_logs, access_logs, error_logs,
system_config, feature_flags, ...
```

### Confidential Data Tables

Tables marked as confidential for testing sensitive data access:

| Table | Domain | Sensitive Data |
|-------|--------|---------------|
| `patient_records` | Healthcare | Full medical history |
| `patient_ssn` | Healthcare | Social Security Numbers |
| `credit_cards` | Banking | Card numbers, CVV |
| `bank_accounts` | Banking | Account numbers, balances |
| `kyc_documents` | Banking | Identity documents |
| `user_passwords` | Common | Password hashes |
| `api_keys` | Common | API credentials |

### Data Volume (Configurable)

| Setting | Value | Notes |
|---------|-------|-------|
| Total Tables | 200 | Configurable in config.yaml |
| Records/Table | 10,000 | Configurable in config.yaml |
| **Total Records** | **~2M** | 200 tables × 10K |

**Note**: Schema creation and data seeding are SEPARATE operations to handle Docker resource constraints.

---

## 4. Database Load Queries

Pre-defined SQL queries for the db-load.jmx template.

### What to Create

```
app/db/queries/
├── crud/
│   ├── inserts.sql          # INSERT statements
│   ├── selects.sql          # SELECT by ID
│   ├── updates.sql          # UPDATE statements
│   └── deletes.sql          # DELETE statements
│
├── complex/
│   ├── joins.sql            # Multi-table JOINs
│   ├── aggregations.sql     # GROUP BY, HAVING
│   └── subqueries.sql       # Nested queries
│
├── bulk/
│   ├── batch_inserts.sql    # Batch operations
│   └── large_selects.sql    # Large result sets
│
└── sensitive/
    ├── patient_queries.sql  # Healthcare data access
    ├── financial_queries.sql # Banking data access
    └── pii_queries.sql      # PII data access
```

### Query Examples

**Simple CRUD:**
```sql
-- Insert
INSERT INTO orders (customer_id, order_date, total_amount, status)
VALUES (?, CURRENT_TIMESTAMP, ?, 'pending');

-- Select by ID
SELECT * FROM products WHERE product_id = ?;

-- Update
UPDATE inventory SET quantity = quantity - ? WHERE product_id = ?;

-- Delete
DELETE FROM cart_items WHERE cart_id = ? AND created_at < ?;
```

**Complex Queries:**
```sql
-- 3-table JOIN
SELECT o.order_id, c.name, p.product_name, oi.quantity, oi.price
FROM orders o
JOIN customers c ON o.customer_id = c.customer_id
JOIN order_items oi ON o.order_id = oi.order_id
JOIN products p ON oi.product_id = p.product_id
WHERE o.order_date BETWEEN ? AND ?;

-- Aggregation
SELECT category_id,
       COUNT(*) as product_count,
       AVG(price) as avg_price,
       SUM(stock_quantity) as total_stock
FROM products
GROUP BY category_id
HAVING COUNT(*) > 10;

-- Subquery
SELECT * FROM customers
WHERE customer_id IN (
    SELECT DISTINCT customer_id
    FROM orders
    WHERE total_amount > (SELECT AVG(total_amount) FROM orders)
);
```

**Sensitive Data Queries:**
```sql
-- Patient records
SELECT p.patient_id, p.ssn, m.diagnosis, m.treatment
FROM patients p
JOIN medical_records m ON p.patient_id = m.patient_id
WHERE m.record_date > ?;

-- Credit card data
SELECT card_number, expiry_date, cvv, cardholder_name
FROM credit_cards
WHERE account_id = ?;

-- Bank account balances
SELECT account_number, routing_number, balance, account_holder_ssn
FROM bank_accounts
WHERE balance > ?;
```

---

## 5. Docker Images

Pre-built Docker images for targets and databases.

### What to Create

```
Docker Registry (local or remote):
├── Target Server Images
│   ├── ubuntu:22.04           # Linux target (standard)
│   ├── ubuntu:20.04           # Linux target (older)
│   └── windows-servercore     # Windows target (if needed)
│
├── Database Images
│   ├── postgres:15            # PostgreSQL
│   ├── mysql:8                # MySQL
│   └── mssql:2019             # SQL Server (if needed)
│
└── Load Generator Images
    └── jmeter:5.6             # JMeter with required plugins
```

### Custom JMeter Image

```dockerfile
FROM eclipse-temurin:17-jre
RUN wget https://archive.apache.org/dist/jmeter/binaries/apache-jmeter-5.6.tgz && \
    tar -xzf apache-jmeter-5.6.tgz && \
    mv apache-jmeter-5.6 /opt/jmeter

# Add JDBC drivers
COPY drivers/postgresql-42.6.0.jar /opt/jmeter/lib/
COPY drivers/mysql-connector-j-8.0.33.jar /opt/jmeter/lib/

# Add plugins
COPY plugins/jmeter-plugins-manager-1.9.jar /opt/jmeter/lib/ext/

ENV PATH="/opt/jmeter/bin:${PATH}"
WORKDIR /opt/jmeter
```

---

## 6. Summary Checklist

| Asset | Location | Status |
|-------|----------|--------|
| CPU Emulator Package | `packages/cpu-emulator/` | TO CREATE |
| Emulator Test Files (Small) | `packages/cpu-emulator/test-files/small-files/` | TO CREATE |
| Emulator Test Files (Large) | `packages/cpu-emulator/test-files/large-files/` | TO CREATE |
| JMX: Server Normal | `app/jmeter/templates/server-normal.jmx` | TO CREATE |
| JMX: Server File-Heavy | `app/jmeter/templates/server-file-heavy.jmx` | TO CREATE |
| JMX: DB Load | `app/jmeter/templates/db-load.jmx` | TO CREATE |
| DB Schema | `app/db/schemas/schema.sql` | TO CREATE |
| DB Seed Data | `app/db/schemas/seed-data.sql` | TO CREATE |
| DB Load Queries | `app/db/queries/` | TO CREATE |
| Docker: JMeter Image | Registry | TO CREATE |
| Docker: Target Images | Registry | EXISTS (standard images) |
| Docker: DB Images | Registry | EXISTS (standard images) |

---

## Next Steps

1. Create the CPU Emulator package
2. Create JMX templates
3. Design and create the 500-table schema
4. Generate seed data (10K-50K records)
5. Create database load queries
6. Build custom JMeter Docker image
7. Create database entries to tie everything together
