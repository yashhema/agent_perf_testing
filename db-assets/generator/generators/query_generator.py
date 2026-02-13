"""Query generator for creating parameterized SQL queries."""

from pathlib import Path
from typing import List, Dict, Any, Optional

from ..config import GeneratorConfig


class QueryGenerator:
    """Generate parameterized SQL queries for JMeter testing."""

    def __init__(self, config: GeneratorConfig):
        """Initialize the query generator.

        Args:
            config: Generator configuration
        """
        self.config = config

    def _get_placeholder(self, db_type: str, index: int = 1) -> str:
        """Get parameter placeholder for database type.

        Args:
            db_type: Database type
            index: Parameter index (1-based)

        Returns:
            Placeholder string
        """
        if db_type == 'postgresql':
            return '$' + str(index)
        elif db_type == 'oracle':
            return ':' + str(index)
        else:  # mssql, db2
            return '?'

    def generate_select_queries(self, db_type: str) -> Dict[str, str]:
        """Generate SELECT queries.

        Args:
            db_type: Database type

        Returns:
            Dictionary of query name to SQL
        """
        p = lambda i: self._get_placeholder(db_type, i)
        queries = {}

        # Simple selects
        queries['select_customer_by_id'] = f"""-- Select customer by ID
SELECT customer_id, email, first_name, last_name, phone, created_at
FROM customers
WHERE customer_id = {p(1)}"""

        queries['select_order_by_id'] = f"""-- Select order by ID
SELECT order_id, order_number, customer_id, order_date, status, grand_total
FROM orders
WHERE order_id = {p(1)}"""

        queries['select_patient_by_id'] = f"""-- Select patient by ID
SELECT patient_id, mrn, first_name, last_name, date_of_birth, ssn, medicare_id
FROM patients
WHERE patient_id = {p(1)}"""

        queries['select_account_by_number'] = f"""-- Select account by account number
SELECT account_id, account_number, routing_number, current_balance, status
FROM accounts
WHERE account_number = {p(1)}"""

        # Range queries
        queries['select_orders_by_date_range'] = f"""-- Select orders by date range
SELECT order_id, order_number, customer_id, order_date, status, grand_total
FROM orders
WHERE order_date BETWEEN {p(1)} AND {p(2)}
ORDER BY order_date DESC"""

        queries['select_transactions_by_date'] = f"""-- Select transactions by date range
SELECT transaction_id, account_id, amount, transaction_date, description, status
FROM bank_transactions
WHERE transaction_date BETWEEN {p(1)} AND {p(2)}
AND account_id = {p(3)}"""

        # Join queries
        queries['select_order_with_customer'] = f"""-- Select order with customer details
SELECT o.order_id, o.order_number, o.order_date, o.status, o.grand_total,
       c.first_name, c.last_name, c.email
FROM orders o
JOIN customers c ON o.customer_id = c.customer_id
WHERE o.order_id = {p(1)}"""

        queries['select_patient_medical_records'] = f"""-- Select patient with medical records
SELECT p.patient_id, p.first_name, p.last_name, p.date_of_birth,
       m.record_id, m.encounter_type, m.admission_date, m.status
FROM patients p
JOIN medical_records m ON p.patient_id = m.patient_id
WHERE p.patient_id = {p(1)}
ORDER BY m.admission_date DESC"""

        queries['select_account_with_transactions'] = f"""-- Select account with recent transactions
SELECT a.account_id, a.account_number, a.current_balance,
       t.transaction_id, t.amount, t.transaction_date, t.description
FROM accounts a
JOIN bank_transactions t ON a.account_id = t.account_id
WHERE a.account_id = {p(1)}
ORDER BY t.transaction_date DESC"""

        return queries

    def generate_insert_queries(self, db_type: str) -> Dict[str, str]:
        """Generate INSERT queries.

        Args:
            db_type: Database type

        Returns:
            Dictionary of query name to SQL
        """
        p = lambda i: self._get_placeholder(db_type, i)
        queries = {}

        queries['insert_order'] = f"""-- Insert new order
INSERT INTO orders (customer_id, order_number, order_date, status, subtotal, tax_total, grand_total)
VALUES ({p(1)}, {p(2)}, {p(3)}, {p(4)}, {p(5)}, {p(6)}, {p(7)})"""

        queries['insert_transaction'] = f"""-- Insert bank transaction
INSERT INTO bank_transactions (account_id, transaction_type_id, reference_number, transaction_date, amount, description, status)
VALUES ({p(1)}, {p(2)}, {p(3)}, {p(4)}, {p(5)}, {p(6)}, {p(7)})"""

        queries['insert_medical_record'] = f"""-- Insert medical record
INSERT INTO medical_records (patient_id, encounter_number, encounter_type, admission_date, provider_id, chief_complaint, status)
VALUES ({p(1)}, {p(2)}, {p(3)}, {p(4)}, {p(5)}, {p(6)}, {p(7)})"""

        queries['insert_diagnosis'] = f"""-- Insert diagnosis
INSERT INTO diagnoses (record_id, patient_id, diagnosis_code, diagnosis_description, diagnosis_type, status)
VALUES ({p(1)}, {p(2)}, {p(3)}, {p(4)}, {p(5)}, {p(6)})"""

        return queries

    def generate_update_queries(self, db_type: str) -> Dict[str, str]:
        """Generate UPDATE queries.

        Args:
            db_type: Database type

        Returns:
            Dictionary of query name to SQL
        """
        p = lambda i: self._get_placeholder(db_type, i)
        queries = {}

        queries['update_order_status'] = f"""-- Update order status
UPDATE orders
SET status = {p(1)}, updated_at = CURRENT_TIMESTAMP
WHERE order_id = {p(2)}"""

        queries['update_account_balance'] = f"""-- Update account balance
UPDATE accounts
SET current_balance = {p(1)}, available_balance = {p(2)}, updated_at = CURRENT_TIMESTAMP
WHERE account_id = {p(3)}"""

        queries['update_patient_contact'] = f"""-- Update patient contact info
UPDATE patients
SET phone_home = {p(1)}, email = {p(2)}, updated_at = CURRENT_TIMESTAMP
WHERE patient_id = {p(3)}"""

        queries['update_customer_loyalty'] = f"""-- Update customer loyalty points
UPDATE customers
SET loyalty_points = {p(1)}, loyalty_tier = {p(2)}, updated_at = CURRENT_TIMESTAMP
WHERE customer_id = {p(3)}"""

        return queries

    def generate_delete_queries(self, db_type: str) -> Dict[str, str]:
        """Generate DELETE queries.

        Args:
            db_type: Database type

        Returns:
            Dictionary of query name to SQL
        """
        p = lambda i: self._get_placeholder(db_type, i)
        queries = {}

        queries['delete_cart_item'] = f"""-- Delete cart item
DELETE FROM cart_items
WHERE cart_id = {p(1)} AND product_id = {p(2)}"""

        queries['delete_expired_sessions'] = f"""-- Delete expired sessions
DELETE FROM sessions
WHERE expires_at < {p(1)}"""

        queries['delete_old_notifications'] = f"""-- Delete old notifications
DELETE FROM notifications
WHERE created_at < {p(1)} AND is_read = TRUE"""

        return queries

    def generate_complex_queries(self, db_type: str) -> Dict[str, str]:
        """Generate complex queries with aggregations and subqueries.

        Args:
            db_type: Database type

        Returns:
            Dictionary of query name to SQL
        """
        p = lambda i: self._get_placeholder(db_type, i)
        queries = {}

        queries['aggregate_sales_by_category'] = f"""-- Aggregate sales by category
SELECT c.category_name,
       COUNT(DISTINCT o.order_id) as order_count,
       SUM(oi.quantity) as total_units,
       SUM(oi.line_total) as total_revenue
FROM order_items oi
JOIN orders o ON oi.order_id = o.order_id
JOIN products p ON oi.product_id = p.product_id
JOIN categories c ON p.category_id = c.category_id
WHERE o.order_date BETWEEN {p(1)} AND {p(2)}
GROUP BY c.category_name
HAVING SUM(oi.line_total) > {p(3)}
ORDER BY total_revenue DESC"""

        queries['top_customers_by_spending'] = f"""-- Top customers by spending
SELECT c.customer_id, c.first_name, c.last_name, c.email,
       COUNT(o.order_id) as order_count,
       SUM(o.grand_total) as total_spent
FROM customers c
JOIN orders o ON c.customer_id = o.customer_id
WHERE o.order_date >= {p(1)}
GROUP BY c.customer_id, c.first_name, c.last_name, c.email
ORDER BY total_spent DESC"""

        queries['account_balance_summary'] = f"""-- Account balance summary by type
SELECT at.type_name,
       COUNT(a.account_id) as account_count,
       SUM(a.current_balance) as total_balance,
       AVG(a.current_balance) as avg_balance
FROM accounts a
JOIN account_types at ON a.account_type_id = at.type_id
WHERE a.status = {p(1)}
GROUP BY at.type_name
ORDER BY total_balance DESC"""

        queries['patient_visit_history'] = f"""-- Patient visit history with diagnoses
SELECT p.patient_id, p.first_name, p.last_name,
       m.encounter_type, m.admission_date,
       d.diagnosis_code, d.diagnosis_description
FROM patients p
JOIN medical_records m ON p.patient_id = m.patient_id
LEFT JOIN diagnoses d ON m.record_id = d.record_id
WHERE p.patient_id = {p(1)}
ORDER BY m.admission_date DESC"""

        return queries

    def generate_sensitive_queries(self, db_type: str) -> Dict[str, str]:
        """Generate queries that access sensitive/confidential data.

        Args:
            db_type: Database type

        Returns:
            Dictionary of query name to SQL
        """
        p = lambda i: self._get_placeholder(db_type, i)
        queries = {}

        queries['select_patient_with_ssn'] = f"""-- Select patient with SSN (SENSITIVE)
SELECT patient_id, first_name, last_name, ssn, date_of_birth,
       medicare_id, address_line1, city, state, zip_code
FROM patients
WHERE patient_id = {p(1)}"""

        queries['select_credit_card_details'] = f"""-- Select credit card details (SENSITIVE)
SELECT card_id, card_number, cvv, expiry_month, expiry_year,
       cardholder_name, credit_limit, current_balance
FROM credit_cards
WHERE account_id = {p(1)}"""

        queries['select_account_with_balance'] = f"""-- Select account with sensitive info (SENSITIVE)
SELECT a.account_id, a.account_number, a.routing_number,
       a.current_balance, a.available_balance
FROM accounts a
WHERE a.account_id = {p(1)}"""

        queries['select_user_credentials'] = f"""-- Select user security info (SENSITIVE)
SELECT user_id, username, email, password_hash,
       last_login_at, failed_login_count
FROM users
WHERE user_id = {p(1)}"""

        return queries

    def generate_ddl_queries(self, db_type: str) -> Dict[str, str]:
        """Generate DDL queries for schema modifications.

        Args:
            db_type: Database type

        Returns:
            Dictionary of query name to SQL
        """
        queries = {}

        if db_type == 'postgresql':
            queries['alter_add_column'] = """-- Add column if not exists
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = $1 AND column_name = $2) THEN
        EXECUTE format('ALTER TABLE %I ADD COLUMN %I %s', $1, $2, $3);
    END IF;
END $$"""

        elif db_type == 'mssql':
            queries['alter_add_column'] = """-- Add column if not exists
IF NOT EXISTS (SELECT * FROM sys.columns
               WHERE object_id = OBJECT_ID(?) AND name = ?)
    EXEC('ALTER TABLE ' + ? + ' ADD ' + ? + ' ' + ?)"""

        elif db_type == 'oracle':
            queries['alter_add_column'] = """-- Add column if not exists
DECLARE
    column_exists NUMBER;
BEGIN
    SELECT COUNT(*) INTO column_exists FROM user_tab_columns
    WHERE table_name = UPPER(:1) AND column_name = UPPER(:2);
    IF column_exists = 0 THEN
        EXECUTE IMMEDIATE 'ALTER TABLE ' || :3 || ' ADD ' || :4 || ' ' || :5;
    END IF;
END;"""

        else:
            queries['alter_add_column'] = """-- Add column
ALTER TABLE ? ADD COLUMN ? ?"""

        return queries

    def generate_grant_queries(self, db_type: str) -> Dict[str, str]:
        """Generate GRANT/REVOKE queries.

        Args:
            db_type: Database type

        Returns:
            Dictionary of query name to SQL
        """
        p = lambda i: self._get_placeholder(db_type, i)
        queries = {}

        if db_type == 'postgresql':
            queries['grant_select'] = f"GRANT SELECT ON {p(1)} TO {p(2)}"
            queries['grant_readwrite'] = f"GRANT SELECT, INSERT, UPDATE, DELETE ON {p(1)} TO {p(2)}"
            queries['revoke_all'] = f"REVOKE ALL ON {p(1)} FROM {p(2)}"

        elif db_type == 'mssql':
            queries['grant_select'] = "GRANT SELECT ON ? TO ?"
            queries['grant_readwrite'] = "GRANT SELECT, INSERT, UPDATE, DELETE ON ? TO ?"
            queries['revoke_all'] = "REVOKE ALL ON ? FROM ?"

        elif db_type == 'oracle':
            queries['grant_select'] = f"GRANT SELECT ON {p(1)} TO {p(2)}"
            queries['grant_readwrite'] = f"GRANT SELECT, INSERT, UPDATE, DELETE ON {p(1)} TO {p(2)}"
            queries['revoke_all'] = f"REVOKE ALL ON {p(1)} FROM {p(2)}"

        return queries

    def generate_all(self, db_type: str, output_dir: str) -> Dict[str, str]:
        """Generate all query files for a database type.

        Args:
            db_type: Database type
            output_dir: Output directory path

        Returns:
            Dictionary of file paths
        """
        output_path = Path(output_dir)
        queries_path = output_path / "queries"

        # Create subdirectories
        for subdir in ['select', 'insert', 'update', 'delete', 'complex', 'sensitive', 'ddl', 'grant']:
            (queries_path / subdir).mkdir(parents=True, exist_ok=True)

        files = {}

        # Generate and write each category
        categories = [
            ('select', self.generate_select_queries),
            ('insert', self.generate_insert_queries),
            ('update', self.generate_update_queries),
            ('delete', self.generate_delete_queries),
            ('complex', self.generate_complex_queries),
            ('sensitive', self.generate_sensitive_queries),
            ('ddl', self.generate_ddl_queries),
            ('grant', self.generate_grant_queries),
        ]

        for category, generator in categories:
            queries = generator(db_type)
            for name, sql in queries.items():
                file_path = queries_path / category / f"{name}.sql"
                file_path.write_text(sql)
                files[f"{category}/{name}.sql"] = str(file_path)

        print(f"Generated queries for {db_type} in {queries_path}")
        return files
