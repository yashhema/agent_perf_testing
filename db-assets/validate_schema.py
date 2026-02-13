"""Validate seed data columns against actual database schema."""
import re
import pyodbc

# Connect to database
conn = pyodbc.connect(
    'DRIVER={ODBC Driver 17 for SQL Server};'
    'SERVER=localhost;'
    'DATABASE=agent_performance_measurement;'
    'Trusted_Connection=yes;'
)
cursor = conn.cursor()

# Get all table schemas from database
def get_table_columns(table_name):
    cursor.execute("""
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_NAME = ?
        ORDER BY ORDINAL_POSITION
    """, table_name)
    return set(row[0] for row in cursor.fetchall())

# Parse seed file to extract INSERT statements
seed_file = r'output\mssql\seed\seed_data.sql'
table_columns_from_seed = {}

with open(seed_file, 'r', encoding='utf-8') as f:
    for line in f:
        if line.startswith('INSERT INTO '):
            # Extract table name and columns
            match = re.match(r'INSERT INTO (\w+) \(([^)]+)\)', line)
            if match:
                table = match.group(1)
                # Strip brackets from column names (SQL Server reserved keyword escaping)
                cols = [c.strip().strip('[]').strip('"') for c in match.group(2).split(',')]
                if table not in table_columns_from_seed:
                    table_columns_from_seed[table] = set(cols)

# Compare and report differences
print("=" * 80)
print("SCHEMA VALIDATION REPORT")
print("=" * 80)

mismatches = []
for table, seed_cols in sorted(table_columns_from_seed.items()):
    db_cols = get_table_columns(table)

    if not db_cols:
        print(f"\n[ERROR] Table '{table}' not found in database!")
        mismatches.append((table, 'TABLE_NOT_FOUND', None, None))
        continue

    extra_in_seed = seed_cols - db_cols
    missing_in_seed = db_cols - seed_cols

    if extra_in_seed or missing_in_seed:
        print(f"\n[MISMATCH] {table}")
        if extra_in_seed:
            print(f"  Invalid columns (in seed but not in DB): {extra_in_seed}")
            for col in extra_in_seed:
                mismatches.append((table, 'INVALID_COLUMN', col, None))
        if missing_in_seed:
            # Filter out auto-generated columns
            required_missing = {c for c in missing_in_seed if c not in ['updated_at']}
            if required_missing:
                print(f"  Missing columns (in DB but not in seed): {required_missing}")

print("\n" + "=" * 80)
print(f"Total tables checked: {len(table_columns_from_seed)}")
print(f"Total mismatches found: {len(mismatches)}")
print("=" * 80)

if mismatches:
    print("\nSUMMARY OF FIXES NEEDED:")
    for table, issue_type, col, _ in mismatches:
        if issue_type == 'INVALID_COLUMN':
            print(f"  - {table}: Remove or rename column '{col}'")
        elif issue_type == 'TABLE_NOT_FOUND':
            print(f"  - {table}: Table doesn't exist!")

conn.close()
