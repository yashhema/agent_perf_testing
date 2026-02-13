"""Operation Sequence Generators for deterministic JMeter test execution.

Generates pre-computed CSV files that define the exact operation sequence
JMeter will follow. Each template type has its own generator with
template-specific columns. Operations are distributed according to the
configured ratios and seeded deterministically so that:
  - Same (test_run_id, load_profile) always produces the same sequence
  - Different load profiles get different sequences
  - Base and Initial phases use the SAME sequence (for valid comparison)

Usage (programmatic — called by orchestrator):
    gen = ServerNormalOpsGenerator("run-001", "low")
    ops = gen.generate(count=288000)
    gen.write_csv(ops, "/path/to/ops_sequence_low.csv")

Usage (CLI):
    python -m generator.main ops-sequence --test-run-id run-001 \\
        --template server-normal --loadprofile low --thread-count 10 --duration 3600
"""

import csv
import hashlib
import random
from pathlib import Path
from typing import Dict, List, Optional


class OpsSequenceGenerator:
    """Base class for operation sequence generators.

    Provides deterministic seeding and sequence length calculation.
    Subclasses implement generate() and write_csv() for each template type.
    """

    def __init__(self, test_run_id: str, load_profile: str):
        """Initialize with deterministic seed.

        Args:
            test_run_id: Unique test run identifier (e.g., "run-001")
            load_profile: Load profile name (e.g., "low", "medium", "high")
        """
        seed_str = f"{test_run_id}:{load_profile}"
        seed = int(hashlib.sha256(seed_str.encode()).hexdigest()[:8], 16)
        self.rng = random.Random(seed)
        self.test_run_id = test_run_id
        self.load_profile = load_profile

    @staticmethod
    def calculate_sequence_length(
        thread_count: int,
        duration_sec: int,
        avg_op_duration_ms: int = 150,
    ) -> int:
        """Calculate how many rows the CSV needs.

        Formula: (duration_sec * 1000 / avg_op_duration_ms) * thread_count * 1.2
        The 1.2 buffer ensures JMeter doesn't run out of rows before the test
        ends; if it does, CSV recycles from the top.

        Args:
            thread_count: Calibrated thread count for this load profile
            duration_sec: Test duration from LoadProfileORM
            avg_op_duration_ms: Estimated average operation duration

        Returns:
            Number of rows to generate
        """
        ops_per_thread = (duration_sec * 1000) / avg_op_duration_ms
        return int(ops_per_thread * thread_count * 1.2)


class ServerNormalOpsGenerator(OpsSequenceGenerator):
    """Generate operation sequence for server-normal.jmx.

    CSV columns: seq_id, op_type
    Distribution: 40% cpu, 30% mem, 29% disk, 1% anomaly
    """

    OP_POOL = (
        ['cpu'] * 40 +
        ['mem'] * 30 +
        ['disk'] * 29 +
        ['anomaly'] * 1
    )

    FIELDNAMES = ['seq_id', 'op_type']

    def generate(self, count: int) -> List[Dict]:
        """Generate deterministic operation sequence.

        Args:
            count: Number of operations to generate

        Returns:
            List of dicts with seq_id and op_type
        """
        operations = []
        for seq_id in range(1, count + 1):
            op_type = self.rng.choice(self.OP_POOL)
            operations.append({
                'seq_id': seq_id,
                'op_type': op_type,
            })
        return operations

    def write_csv(self, operations: List[Dict], output_path: str) -> str:
        """Write operations to CSV file.

        Args:
            operations: List from generate()
            output_path: Filesystem path for the CSV

        Returns:
            The output_path written to
        """
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=self.FIELDNAMES)
            writer.writeheader()
            writer.writerows(operations)
        return output_path


class ServerFileHeavyOpsGenerator(OpsSequenceGenerator):
    """Generate operation sequence for server-file-heavy.jmx.

    CSV columns: seq_id, op_type, size_bracket, target_size_kb,
                 output_format, output_folder_idx, is_confidential,
                 make_zip, source_file_ids

    Distribution: 35% cpu, 34% mem, 30% file, 1% anomaly

    For file operations, all parameters are pre-determined in the CSV so that
    the same CSV produces identical file I/O patterns across base and initial
    phases. Non-file rows have empty file columns.
    """

    OP_POOL = (
        ['cpu'] * 35 +
        ['mem'] * 34 +
        ['file'] * 30 +
        ['anomaly'] * 1
    )

    SIZE_BRACKETS = {
        'small': (50, 100),
        'medium': (100, 500),
        'large': (500, 2048),
        'xlarge': (2048, 10240),
    }

    # Weight distribution: 25% small, 40% medium, 25% large, 10% xlarge
    SIZE_POOL: List[str] = (
        ['small'] * 25 +
        ['medium'] * 40 +
        ['large'] * 25 +
        ['xlarge'] * 10
    )

    OUTPUT_FORMATS = ['txt', 'csv', 'doc', 'xls', 'pdf']

    FIELDNAMES = [
        'seq_id', 'op_type', 'size_bracket', 'target_size_kb',
        'output_format', 'output_folder_idx', 'is_confidential',
        'make_zip', 'source_file_ids',
    ]

    def __init__(
        self,
        test_run_id: str,
        load_profile: str,
        normal_files: List[str],
        confidential_files: List[str],
        num_output_folders: int = 4,
    ):
        """Initialize with source file lists.

        Args:
            test_run_id: Unique test run identifier
            load_profile: Load profile name
            normal_files: List of normal source file IDs (e.g., ["rfc791", "rfc793"])
            confidential_files: List of confidential source file IDs (e.g., ["conf001"])
            num_output_folders: Number of output folder indices (0..N-1)
        """
        super().__init__(test_run_id, load_profile)
        self.normal_files = normal_files
        self.confidential_files = confidential_files
        self.num_output_folders = num_output_folders

    def generate(
        self,
        count: int,
        confidential_percent: float = 10.0,
        zip_percent: float = 20.0,
    ) -> List[Dict]:
        """Generate merged operation sequence with file parameters.

        Args:
            count: Number of operations to generate
            confidential_percent: % of file ops that include confidential data
            zip_percent: % of file ops that produce zipped output

        Returns:
            List of dicts with all CSV columns populated
        """
        operations = []

        for seq_id in range(1, count + 1):
            op_type = self.rng.choice(self.OP_POOL)
            row: Dict = {'seq_id': seq_id, 'op_type': op_type}

            if op_type == 'file':
                size_bracket = self.rng.choice(self.SIZE_POOL)
                size_range = self.SIZE_BRACKETS[size_bracket]
                target_size_kb = self.rng.randint(size_range[0], size_range[1])
                output_format = self.rng.choice(self.OUTPUT_FORMATS)
                output_folder_idx = self.rng.randint(0, self.num_output_folders - 1)
                is_confidential = self.rng.random() * 100 < confidential_percent
                make_zip = self.rng.random() * 100 < zip_percent

                source_files = self._select_source_files(
                    target_size_kb, is_confidential
                )

                row.update({
                    'size_bracket': size_bracket,
                    'target_size_kb': target_size_kb,
                    'output_format': output_format,
                    'output_folder_idx': output_folder_idx,
                    'is_confidential': str(is_confidential).lower(),
                    'make_zip': str(make_zip).lower(),
                    'source_file_ids': ';'.join(source_files),
                })
            else:
                row.update({
                    'size_bracket': '',
                    'target_size_kb': '',
                    'output_format': '',
                    'output_folder_idx': '',
                    'is_confidential': '',
                    'make_zip': '',
                    'source_file_ids': '',
                })

            operations.append(row)
        return operations

    def _select_source_files(
        self, target_size_kb: int, is_confidential: bool
    ) -> List[str]:
        """Select source files to approximate target size.

        Heuristic: ~50KB per source file, so num_files = target_size_kb / 50.
        If confidential, mix in some confidential file IDs.

        Args:
            target_size_kb: Target output size
            is_confidential: Whether to include confidential sources

        Returns:
            List of source file ID strings
        """
        num_files = max(1, target_size_kb // 50)

        if is_confidential and self.confidential_files:
            normal_count = max(1, num_files - 2)
            conf_count = min(
                len(self.confidential_files),
                num_files - normal_count,
            )
            selected = (
                [self.rng.choice(self.normal_files) for _ in range(normal_count)] +
                [self.rng.choice(self.confidential_files) for _ in range(conf_count)]
            )
        else:
            selected = [self.rng.choice(self.normal_files) for _ in range(num_files)]
        return selected

    def write_csv(self, operations: List[Dict], output_path: str) -> str:
        """Write merged operations to CSV file.

        Args:
            operations: List from generate()
            output_path: Filesystem path for the CSV

        Returns:
            The output_path written to
        """
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=self.FIELDNAMES)
            writer.writeheader()
            writer.writerows(operations)
        return output_path


class DbLoadOpsGenerator(OpsSequenceGenerator):
    """Generate operation sequence for db-load-{db_type}.jmx.

    CSV columns: seq_id, op_type, customer_id, order_id, status, amount,
                 product_id, patient_id, account_id, start_date, end_date,
                 ddl_table_name, ddl_column_name, ddl_column_type,
                 grant_table, grant_user, new_username, new_password

    Distribution: 30% select_simple, 15% select_complex, 15% insert,
                  15% update, 10% delete, 5% sensitive, 3% ddl, 3% grant,
                  2% create_user, 2% auth

    All query parameters are embedded in the CSV so that the same CSV
    produces identical DB operations across base and initial phases.
    """

    OP_POOL = (
        ['select_simple'] * 30 +
        ['select_complex'] * 15 +
        ['insert'] * 15 +
        ['update'] * 15 +
        ['delete'] * 10 +
        ['sensitive'] * 5 +
        ['ddl'] * 3 +
        ['grant'] * 3 +
        ['create_user'] * 2 +
        ['auth'] * 2
    )

    FIELDNAMES = [
        'seq_id', 'op_type', 'customer_id', 'order_id', 'status',
        'amount', 'product_id', 'patient_id', 'account_id',
        'start_date', 'end_date', 'ddl_table_name', 'ddl_column_name',
        'ddl_column_type', 'grant_table', 'grant_user',
        'new_username', 'new_password',
    ]

    def __init__(
        self,
        test_run_id: str,
        load_profile: str,
        customer_ids: List[int],
        order_params: List[Dict],
        product_ids: List[int],
        patient_ids: List[int],
        account_ids: List[int],
        ddl_params: List[Dict],
        grant_params: List[Dict],
        temp_users: List[Dict],
        config_users: List[str],
        db_type: str = 'postgresql',
    ):
        """Initialize with actual seed-data-derived parameter pools.

        All list parameters should come from the seed data generator's
        single-pass output, ensuring JMeter queries reference data that
        actually exists in the database.

        Args:
            test_run_id: Unique test run identifier
            load_profile: Load profile name
            customer_ids: Pool of valid customer IDs from seed data
            order_params: Pool of dicts with order_id, status, amount
            product_ids: Pool of valid product IDs from seed data
            patient_ids: Pool of valid patient IDs (for sensitive queries)
            account_ids: Pool of valid account IDs
            ddl_params: Pool of dicts with table_name, column_name, column_type
            grant_params: Pool of dicts with table_name, username
            temp_users: Pool of dicts with username, password (for CREATE USER)
            config_users: Pool of usernames (for SET ROLE / auth)
            db_type: Database vendor ('postgresql', 'mssql', 'oracle', 'db2')
        """
        super().__init__(test_run_id, load_profile)
        self.customer_ids = customer_ids
        self.order_params = order_params
        self.product_ids = product_ids
        self.patient_ids = patient_ids
        self.account_ids = account_ids
        self.ddl_params = ddl_params
        self.grant_params = grant_params
        self.temp_users = temp_users
        self.config_users = config_users
        self.db_type = db_type

    def generate(self, count: int) -> List[Dict]:
        """Generate merged DB operation sequence with all query parameters.

        Each row contains the op_type and only the columns relevant to that
        operation; unused columns are empty strings.

        Args:
            count: Number of operations to generate

        Returns:
            List of dicts with all 18 CSV columns
        """
        empty_row = {
            'customer_id': '', 'order_id': '', 'status': '', 'amount': '',
            'product_id': '', 'patient_id': '', 'account_id': '',
            'start_date': '', 'end_date': '',
            'ddl_table_name': '', 'ddl_column_name': '', 'ddl_column_type': '',
            'grant_table': '', 'grant_user': '',
            'new_username': '', 'new_password': '',
        }

        operations = []
        for seq_id in range(1, count + 1):
            op_type = self.rng.choice(self.OP_POOL)
            row = {'seq_id': seq_id, 'op_type': op_type, **empty_row}

            if op_type == 'select_simple':
                row['customer_id'] = self.rng.choice(self.customer_ids)

            elif op_type == 'select_complex':
                op = self.rng.choice(self.order_params)
                row['order_id'] = op['order_id']
                row['status'] = op['status']
                row['amount'] = op['amount']

            elif op_type == 'insert':
                row['customer_id'] = self.rng.choice(self.customer_ids)
                row['amount'] = round(self.rng.uniform(10, 5000), 2)

            elif op_type == 'update':
                op = self.rng.choice(self.order_params)
                row['order_id'] = op['order_id']
                row['status'] = self.rng.choice(
                    ['SHIPPED', 'DELIVERED', 'CANCELLED']
                )

            elif op_type == 'delete':
                row['customer_id'] = self.rng.choice(self.customer_ids)

            elif op_type == 'sensitive':
                row['patient_id'] = self.rng.choice(self.patient_ids)

            elif op_type == 'ddl':
                ddl = self.rng.choice(self.ddl_params)
                row['ddl_table_name'] = ddl['table_name']
                row['ddl_column_name'] = ddl['column_name']
                row['ddl_column_type'] = ddl['column_type']

            elif op_type == 'grant':
                g = self.rng.choice(self.grant_params)
                row['grant_table'] = g['table_name']
                row['grant_user'] = g['username']

            elif op_type == 'create_user':
                u = self.rng.choice(self.temp_users)
                row['new_username'] = u['username']
                row['new_password'] = u['password']

            elif op_type == 'auth':
                row['grant_user'] = self.rng.choice(self.config_users)

            operations.append(row)
        return operations

    def write_csv(self, operations: List[Dict], output_path: str) -> str:
        """Write merged DB operations to CSV file.

        Args:
            operations: List from generate()
            output_path: Filesystem path for the CSV

        Returns:
            The output_path written to
        """
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=self.FIELDNAMES)
            writer.writeheader()
            writer.writerows(operations)
        return output_path
