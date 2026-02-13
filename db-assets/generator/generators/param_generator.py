"""Parameter generator for creating CSV files for JMeter."""

import csv
import random
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import List, Dict, Any, Optional

from ..config import GeneratorConfig
from ..loaders.confidential_loader import ConfidentialDataLoader
from ..utils.faker_providers import get_faker
from ..utils.db_type_mapper import get_cached_ddl_types


class ParamGenerator:
    """Generate CSV parameter files for JMeter testing."""

    def __init__(self, config: GeneratorConfig, confidential_loader: ConfidentialDataLoader = None, db_type: str = 'postgresql'):
        """Initialize the parameter generator.

        Args:
            config: Generator configuration
            confidential_loader: Optional loader for confidential data
            db_type: Database type for vendor-specific type mapping ('postgresql', 'mssql', 'oracle', 'db2')
        """
        self.config = config
        self.conf_loader = confidential_loader
        self.fake = get_faker()
        self.rows_per_file = config.query_generation.param_rows_per_query
        self.db_type = db_type

    def _random_date(self, start_days_ago: int = 365, end_days_ago: int = 0) -> str:
        """Generate a random date string.

        Args:
            start_days_ago: Maximum days in the past
            end_days_ago: Minimum days in the past

        Returns:
            Date string in ISO format
        """
        days = random.randint(end_days_ago, start_days_ago)
        d = datetime.now() - timedelta(days=days)
        return d.strftime('%Y-%m-%d')

    def _random_datetime(self, start_days_ago: int = 365, end_days_ago: int = 0) -> str:
        """Generate a random datetime string.

        Args:
            start_days_ago: Maximum days in the past
            end_days_ago: Minimum days in the past

        Returns:
            Datetime string in ISO format
        """
        days = random.randint(end_days_ago, start_days_ago)
        dt = datetime.now() - timedelta(days=days, hours=random.randint(0, 23), minutes=random.randint(0, 59))
        return dt.strftime('%Y-%m-%d %H:%M:%S')

    def generate_customer_ids(self, count: int = None) -> List[Dict[str, Any]]:
        """Generate customer ID parameters.

        Args:
            count: Number of rows to generate

        Returns:
            List of parameter dictionaries
        """
        count = count or self.rows_per_file
        return [{'customer_id': i + 1} for i in range(count)]

    def generate_order_ids(self, count: int = None) -> List[Dict[str, Any]]:
        """Generate order ID parameters.

        Args:
            count: Number of rows to generate

        Returns:
            List of parameter dictionaries
        """
        count = count or self.rows_per_file
        return [{'order_id': i + 1} for i in range(count)]

    def generate_patient_ids(self, count: int = None) -> List[Dict[str, Any]]:
        """Generate patient ID parameters.

        Args:
            count: Number of rows to generate

        Returns:
            List of parameter dictionaries
        """
        count = count or self.rows_per_file
        return [{'patient_id': i + 1} for i in range(count)]

    def generate_account_ids(self, count: int = None) -> List[Dict[str, Any]]:
        """Generate account ID parameters.

        Args:
            count: Number of rows to generate

        Returns:
            List of parameter dictionaries
        """
        count = count or self.rows_per_file
        return [{'account_id': i + 1} for i in range(count)]

    def generate_date_ranges(self, count: int = None) -> List[Dict[str, Any]]:
        """Generate date range parameters.

        Args:
            count: Number of rows to generate

        Returns:
            List of parameter dictionaries
        """
        count = count or self.rows_per_file
        params = []
        for _ in range(count):
            end_date = datetime.now() - timedelta(days=random.randint(0, 30))
            start_date = end_date - timedelta(days=random.randint(7, 90))
            params.append({
                'start_date': start_date.strftime('%Y-%m-%d'),
                'end_date': end_date.strftime('%Y-%m-%d'),
            })
        return params

    def generate_order_search_params(self, count: int = None) -> List[Dict[str, Any]]:
        """Generate order search parameters.

        Args:
            count: Number of rows to generate

        Returns:
            List of parameter dictionaries
        """
        count = count or self.rows_per_file
        statuses = ['PENDING', 'PROCESSING', 'SHIPPED', 'DELIVERED']
        params = []
        for _ in range(count):
            end_date = datetime.now() - timedelta(days=random.randint(0, 30))
            start_date = end_date - timedelta(days=random.randint(7, 90))
            params.append({
                'start_date': start_date.strftime('%Y-%m-%d'),
                'end_date': end_date.strftime('%Y-%m-%d'),
                'status': random.choice(statuses),
                'min_amount': round(random.uniform(10, 100), 2),
            })
        return params

    def generate_transaction_params(self, count: int = None) -> List[Dict[str, Any]]:
        """Generate transaction search parameters.

        Args:
            count: Number of rows to generate

        Returns:
            List of parameter dictionaries
        """
        count = count or self.rows_per_file
        params = []
        for _ in range(count):
            end_date = datetime.now() - timedelta(days=random.randint(0, 30))
            start_date = end_date - timedelta(days=random.randint(7, 90))
            params.append({
                'start_date': start_date.strftime('%Y-%m-%d %H:%M:%S'),
                'end_date': end_date.strftime('%Y-%m-%d %H:%M:%S'),
                'account_id': random.randint(1, 5000),
            })
        return params

    def generate_insert_order_params(self, count: int = None) -> List[Dict[str, Any]]:
        """Generate parameters for order insertion.

        Args:
            count: Number of rows to generate

        Returns:
            List of parameter dictionaries
        """
        count = count or self.rows_per_file
        params = []
        for i in range(count):
            subtotal = round(random.uniform(25, 500), 2)
            tax = round(subtotal * 0.08, 2)
            params.append({
                'customer_id': random.randint(1, 5000),
                'order_number': f"ORD-{100000 + i}",
                'order_date': self._random_datetime(30),
                'status': 'PENDING',
                'subtotal': subtotal,
                'tax_total': tax,
                'grand_total': round(subtotal + tax, 2),
            })
        return params

    def generate_update_status_params(self, count: int = None) -> List[Dict[str, Any]]:
        """Generate parameters for status updates.

        Args:
            count: Number of rows to generate

        Returns:
            List of parameter dictionaries
        """
        count = count or self.rows_per_file
        statuses = ['PENDING', 'PROCESSING', 'SHIPPED', 'DELIVERED', 'CANCELLED']
        params = []
        for _ in range(count):
            params.append({
                'new_status': random.choice(statuses),
                'order_id': random.randint(1, 5000),
            })
        return params

    def generate_ddl_params(self, count: int = None) -> List[Dict[str, Any]]:
        """Generate parameters for DDL operations.

        Uses SQLAlchemy dialect to get vendor-specific type strings.

        Args:
            count: Number of rows to generate

        Returns:
            List of parameter dictionaries
        """
        count = count or min(self.rows_per_file, 100)  # Limit DDL params

        # Use DDL test tables (not data tables) for ALTER TABLE operations
        # These are created in setUp Thread Group before the main test
        ddl_test_tables = [f'ddl_test_{i:03d}' for i in range(1, 21)]

        # Get vendor-specific column types using SQLAlchemy dialect
        column_types = get_cached_ddl_types(self.db_type)

        params = []
        for i in range(count):
            params.append({
                'table_name': random.choice(ddl_test_tables),
                'column_name': f"test_field_{i:03d}",
                'column_type': random.choice(column_types),
            })
        return params

    def generate_grant_params(self, count: int = None) -> List[Dict[str, Any]]:
        """Generate parameters for GRANT operations.

        Args:
            count: Number of rows to generate

        Returns:
            List of parameter dictionaries
        """
        count = count or min(self.rows_per_file, 100)  # Limit grant params
        tables = ['orders', 'customers', 'products', 'accounts', 'patients',
                  'credit_cards', 'medical_records', 'bank_transactions']
        users = ['test_user_1', 'test_user_2', 'test_admin']
        params = []
        for _ in range(count):
            params.append({
                'table_name': random.choice(tables),
                'username': random.choice(users),
            })
        return params

    def generate_user_credentials(self) -> List[Dict[str, Any]]:
        """Generate user credential parameters.

        Returns:
            List of parameter dictionaries
        """
        return [
            {'username': user.username, 'password': user.password, 'role': user.role}
            for user in self.config.test_users
        ]

    def generate_sensitive_patient_ids(self, count: int = None) -> List[Dict[str, Any]]:
        """Generate patient IDs for sensitive queries.

        Args:
            count: Number of rows to generate

        Returns:
            List of parameter dictionaries
        """
        count = count or self.rows_per_file
        return [{'patient_id': random.randint(1, 5000)} for _ in range(count)]

    def generate_sensitive_account_ids(self, count: int = None) -> List[Dict[str, Any]]:
        """Generate account IDs for sensitive queries.

        Args:
            count: Number of rows to generate

        Returns:
            List of parameter dictionaries
        """
        count = count or self.rows_per_file
        return [{'account_id': random.randint(1, 5000)} for _ in range(count)]

    def _write_csv(self, file_path: Path, data: List[Dict[str, Any]]) -> str:
        """Write data to CSV file.

        Args:
            file_path: Path to write to
            data: List of dictionaries to write

        Returns:
            Path to written file
        """
        if not data:
            return str(file_path)

        with open(file_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=data[0].keys())
            writer.writeheader()
            writer.writerows(data)

        return str(file_path)

    def generate_all(self, output_dir: str) -> Dict[str, str]:
        """Generate all parameter files.

        Args:
            output_dir: Output directory path

        Returns:
            Dictionary of file paths
        """
        output_path = Path(output_dir)
        params_path = output_path / "params"
        params_path.mkdir(parents=True, exist_ok=True)

        files = {}

        # Define all parameter generators
        param_configs = [
            ('customer_ids.csv', self.generate_customer_ids),
            ('order_ids.csv', self.generate_order_ids),
            ('patient_ids.csv', self.generate_patient_ids),
            ('account_ids.csv', self.generate_account_ids),
            ('date_ranges.csv', self.generate_date_ranges),
            ('order_search_params.csv', self.generate_order_search_params),
            ('transaction_params.csv', self.generate_transaction_params),
            ('insert_order_params.csv', self.generate_insert_order_params),
            ('update_status_params.csv', self.generate_update_status_params),
            ('ddl_add_column_params.csv', self.generate_ddl_params),
            ('grant_select_params.csv', self.generate_grant_params),
            ('user_credentials.csv', self.generate_user_credentials),
            ('sensitive_patient_ids.csv', self.generate_sensitive_patient_ids),
            ('sensitive_account_ids.csv', self.generate_sensitive_account_ids),
        ]

        for filename, generator in param_configs:
            file_path = params_path / filename
            data = generator() if callable(generator) else generator
            self._write_csv(file_path, data)
            files[filename] = str(file_path)

        print(f"Generated parameter files in {params_path}")
        return files
