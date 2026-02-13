"""Seed data generator for populating tables with realistic data.

CRITICAL: This generator implements SINGLE-PASS generation where seed data
and parameter CSV files are generated together. This ensures that params
contain ACTUAL values from the seed data, not random/hardcoded values.
"""

import csv
import random
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import List, Dict, Any, Optional, Set
from decimal import Decimal

from ..config import GeneratorConfig
from ..loaders.confidential_loader import ConfidentialDataLoader
from ..utils.faker_providers import get_faker
from ..utils.db_type_mapper import get_cached_ddl_types


class ParamCollector:
    """Collects actual values during seed data generation for params CSV files.

    This ensures single-pass generation where params contain real values
    that exist in the database.
    """

    def __init__(self, max_rows: int = 5000):
        """Initialize the param collector.

        Args:
            max_rows: Maximum rows to collect per param type
        """
        self.max_rows = max_rows
        self._data: Dict[str, List[Dict[str, Any]]] = {}

    def add(self, param_type: str, values: Dict[str, Any]):
        """Add a row of values for a param type.

        Args:
            param_type: Name of the param file (e.g., 'customer_ids')
            values: Dictionary of column names to values
        """
        if param_type not in self._data:
            self._data[param_type] = []

        if len(self._data[param_type]) < self.max_rows:
            self._data[param_type].append(values)

    def get(self, param_type: str) -> List[Dict[str, Any]]:
        """Get collected values for a param type."""
        return self._data.get(param_type, [])

    def write_csv(self, param_type: str, file_path: Path) -> str:
        """Write collected values to a CSV file.

        Args:
            param_type: Name of the param type
            file_path: Path to write the CSV file

        Returns:
            Path to the written file
        """
        data = self._data.get(param_type, [])
        if not data:
            return str(file_path)

        with open(file_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=data[0].keys())
            writer.writeheader()
            writer.writerows(data)

        return str(file_path)

    def write_all(self, output_dir: Path) -> Dict[str, str]:
        """Write all collected params to CSV files.

        Args:
            output_dir: Directory to write CSV files

        Returns:
            Dictionary of param_type to file path
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        files = {}

        for param_type, data in self._data.items():
            if data:
                file_path = output_dir / f"{param_type}.csv"
                self.write_csv(param_type, file_path)
                files[param_type] = str(file_path)

        return files


class SeedDataGenerator:
    """Generate seed data for all tables using ConfidentialData and Faker.

    CRITICAL: This class implements SINGLE-PASS generation. As seed data is
    generated, actual values are captured in ParamCollector for CSV params.
    This ensures JMeter params reference data that actually exists in the DB.
    """

    def __init__(self, config: GeneratorConfig, confidential_loader: ConfidentialDataLoader):
        """Initialize the seed data generator.

        Args:
            config: Generator configuration
            confidential_loader: Loader for confidential PII data
        """
        self.config = config
        self.conf_loader = confidential_loader
        self.fake = get_faker()
        self.records_per_table = config.seed_data.records_per_table
        self.batch_size = config.seed_data.batch_size

        # Track generated IDs for foreign key references
        self._id_cache: Dict[str, List[int]] = {}

        # SINGLE-PASS: Collect actual values for params CSV as we generate seed data
        self.params = ParamCollector(max_rows=config.query_generation.param_rows_per_query)

    def _get_random_id(self, table_name: str, count: int = 1) -> int:
        """Get random ID(s) from a previously generated table.

        Args:
            table_name: Name of the table to get IDs from
            count: Number of IDs to return (1 = single int, >1 = list)

        Returns:
            Random ID or list of IDs
        """
        if table_name not in self._id_cache or not self._id_cache[table_name]:
            # Return a placeholder
            return 1 if count == 1 else [1] * count

        if count == 1:
            return random.choice(self._id_cache[table_name])
        return random.choices(self._id_cache[table_name], k=count)

    def _cache_ids(self, table_name: str, ids: List[int]):
        """Cache generated IDs for foreign key references.

        Args:
            table_name: Table name
            ids: List of generated IDs
        """
        self._id_cache[table_name] = ids

    def _format_value(self, value: Any, db_type: str = 'postgresql') -> str:
        """Format a value for SQL INSERT statement.

        Args:
            value: Value to format
            db_type: Database type

        Returns:
            Formatted SQL string
        """
        if value is None:
            return "NULL"
        elif isinstance(value, bool):
            if db_type == 'postgresql':
                return 'TRUE' if value else 'FALSE'
            elif db_type == 'mssql':
                return '1' if value else '0'
            else:
                return '1' if value else '0'
        elif isinstance(value, (int, float, Decimal)):
            return str(value)
        elif isinstance(value, datetime):
            if db_type == 'mssql':
                # SQL Server datetime only supports milliseconds (3 digits)
                # Format: YYYY-MM-DD HH:MM:SS.mmm
                return f"'{value.strftime('%Y-%m-%d %H:%M:%S')}.{value.microsecond // 1000:03d}'"
            else:
                return f"'{value.isoformat()}'"
        elif isinstance(value, date):
            return f"'{value.isoformat()}'"
        else:
            # Escape single quotes
            escaped = str(value).replace("'", "''")
            return f"'{escaped}'"

    def _random_datetime(self, start_days_ago: int = 365, end_days_ago: int = 0) -> datetime:
        """Generate a random datetime.

        Args:
            start_days_ago: Days ago for start of range. Positive = past, negative = future.
            end_days_ago: Days ago for end of range. Positive = past, negative = future.

        Returns:
            Random datetime
        """
        # Ensure we get a valid range regardless of sign
        min_days = min(start_days_ago, end_days_ago)
        max_days = max(start_days_ago, end_days_ago)
        days = random.randint(min_days, max_days)
        return datetime.now() - timedelta(days=days, hours=random.randint(0, 23), minutes=random.randint(0, 59))

    def _random_date(self, start_days_ago: int = 365, end_days_ago: int = 0) -> date:
        """Generate a random date.

        Args:
            start_days_ago: Maximum days in the past
            end_days_ago: Minimum days in the past

        Returns:
            Random date
        """
        days = random.randint(end_days_ago, start_days_ago)
        return (datetime.now() - timedelta(days=days)).date()

    # =========================================================================
    # Shared Domain Generators
    # =========================================================================

    def generate_users(self, count: int) -> List[Dict[str, Any]]:
        """Generate user records."""
        records = []
        for i in range(count):
            conf = self.conf_loader.get_next()
            records.append({
                'user_id': i + 1,
                'username': self.fake.user_name() + str(i),
                'email': conf.get('EMAIL') or self.fake.email(),
                'password_hash': self.fake.sha256(),
                'first_name': conf.get('FIRSTNAME') or self.fake.first_name(),
                'last_name': conf.get('LASTNAME') or self.fake.last_name(),
                'phone': conf.get('PHONE') or self.fake.phone_number()[:20],
                'is_verified': random.random() > 0.2,
                'last_login_at': self._random_datetime(30),
                'failed_login_count': random.randint(0, 3),
                'is_active': random.random() > 0.05,
                'created_at': self._random_datetime(730),
            })
        self._cache_ids('users', [r['user_id'] for r in records])
        return records

    def generate_countries(self) -> List[Dict[str, Any]]:
        """Generate country reference data."""
        countries = [
            ('USA', 'United States', '+1', 'USD'),
            ('CAN', 'Canada', '+1', 'CAD'),
            ('GBR', 'United Kingdom', '+44', 'GBP'),
            ('DEU', 'Germany', '+49', 'EUR'),
            ('FRA', 'France', '+33', 'EUR'),
            ('JPN', 'Japan', '+81', 'JPY'),
            ('AUS', 'Australia', '+61', 'AUD'),
            ('MEX', 'Mexico', '+52', 'MXN'),
            ('BRA', 'Brazil', '+55', 'BRL'),
            ('IND', 'India', '+91', 'INR'),
        ]
        records = []
        for i, (code, name, phone, currency) in enumerate(countries):
            records.append({
                'country_id': i + 1,
                'country_code': code,
                'country_name': name,
                'phone_code': phone,
                'currency_code': currency,
            })
        self._cache_ids('countries', [r['country_id'] for r in records])
        return records

    def generate_roles(self) -> List[Dict[str, Any]]:
        """Generate role records."""
        roles = [
            ('ADMIN', 'Administrator', True),
            ('USER', 'Standard User', False),
            ('READONLY', 'Read Only User', False),
            ('MANAGER', 'Manager', False),
            ('SUPPORT', 'Support Staff', False),
        ]
        records = []
        for i, (name, desc, is_system) in enumerate(roles):
            records.append({
                'role_id': i + 1,
                'role_name': name,
                'description': desc,
                'is_system_role': is_system,
            })
        self._cache_ids('roles', [r['role_id'] for r in records])
        return records

    def generate_permissions(self) -> List[Dict[str, Any]]:
        """Generate permission records."""
        permissions = [
            ('users', 'read'), ('users', 'write'), ('users', 'delete'),
            ('orders', 'read'), ('orders', 'write'), ('orders', 'delete'),
            ('products', 'read'), ('products', 'write'), ('products', 'delete'),
            ('accounts', 'read'), ('accounts', 'write'), ('accounts', 'delete'),
            ('patients', 'read'), ('patients', 'write'), ('patients', 'delete'),
            ('reports', 'read'), ('reports', 'write'), ('admin', 'access'),
            ('settings', 'read'), ('settings', 'write'),
        ]
        records = []
        for i, (resource, action) in enumerate(permissions):
            records.append({
                'permission_id': i + 1,
                'permission_name': f"{resource}_{action}",
                'resource': resource,
                'action': action,
                'description': f"Permission to {action} {resource}",
                'created_at': self._random_datetime(365),
            })
        self._cache_ids('permissions', [r['permission_id'] for r in records])
        return records

    def generate_states(self, count: int = 50) -> List[Dict[str, Any]]:
        """Generate state records."""
        us_states = [
            ('AL', 'Alabama'), ('AK', 'Alaska'), ('AZ', 'Arizona'), ('AR', 'Arkansas'),
            ('CA', 'California'), ('CO', 'Colorado'), ('CT', 'Connecticut'), ('DE', 'Delaware'),
            ('FL', 'Florida'), ('GA', 'Georgia'), ('HI', 'Hawaii'), ('ID', 'Idaho'),
            ('IL', 'Illinois'), ('IN', 'Indiana'), ('IA', 'Iowa'), ('KS', 'Kansas'),
            ('KY', 'Kentucky'), ('LA', 'Louisiana'), ('ME', 'Maine'), ('MD', 'Maryland'),
            ('MA', 'Massachusetts'), ('MI', 'Michigan'), ('MN', 'Minnesota'), ('MS', 'Mississippi'),
            ('MO', 'Missouri'), ('MT', 'Montana'), ('NE', 'Nebraska'), ('NV', 'Nevada'),
            ('NH', 'New Hampshire'), ('NJ', 'New Jersey'), ('NM', 'New Mexico'), ('NY', 'New York'),
            ('NC', 'North Carolina'), ('ND', 'North Dakota'), ('OH', 'Ohio'), ('OK', 'Oklahoma'),
            ('OR', 'Oregon'), ('PA', 'Pennsylvania'), ('RI', 'Rhode Island'), ('SC', 'South Carolina'),
            ('SD', 'South Dakota'), ('TN', 'Tennessee'), ('TX', 'Texas'), ('UT', 'Utah'),
            ('VT', 'Vermont'), ('VA', 'Virginia'), ('WA', 'Washington'), ('WV', 'West Virginia'),
            ('WI', 'Wisconsin'), ('WY', 'Wyoming'),
        ]
        records = []
        for i, (code, name) in enumerate(us_states[:count]):
            records.append({
                'state_id': i + 1,
                'country_id': 1,  # USA
                'state_code': code,
                'state_name': name,
                'created_at': self._random_datetime(365),
            })
        self._cache_ids('states', [r['state_id'] for r in records])
        return records

    def generate_cities(self, count: int = 200) -> List[Dict[str, Any]]:
        """Generate city records."""
        records = []
        for i in range(count):
            state_id = self._get_random_id('states')
            records.append({
                'city_id': i + 1,
                'state_id': state_id,
                'city_name': self.fake.city(),
                'zip_code': self.fake.zipcode(),
                'latitude': round(random.uniform(25.0, 49.0), 7),
                'longitude': round(random.uniform(-125.0, -67.0), 7),
                'created_at': self._random_datetime(365),
            })
        self._cache_ids('cities', [r['city_id'] for r in records])
        return records

    def generate_addresses(self, count: int = 500) -> List[Dict[str, Any]]:
        """Generate address records."""
        records = []
        for i in range(count):
            records.append({
                'address_id': i + 1,
                'address_type': random.choice(['HOME', 'WORK', 'BILLING', 'SHIPPING']),
                'address_line1': self.fake.street_address(),
                'address_line2': self.fake.secondary_address() if random.random() > 0.7 else None,
                'city_id': self._get_random_id('cities'),
                'city_name': self.fake.city(),
                'state_code': self.fake.state_abbr(),
                'postal_code': self.fake.zipcode(),
                'country_code': 'USA',
                'is_verified': random.random() > 0.3,
                'verified_at': self._random_datetime(30) if random.random() > 0.5 else None,
                'is_active': True,
                'created_at': self._random_datetime(365),
            })
        self._cache_ids('addresses', [r['address_id'] for r in records])
        return records

    def generate_user_roles(self, count: int = 500) -> List[Dict[str, Any]]:
        """Generate user-role assignment records."""
        records = []
        used_pairs = set()
        for i in range(count):
            user_id = self._get_random_id('users')
            role_id = self._get_random_id('roles')
            pair = (user_id, role_id)
            if pair in used_pairs:
                continue
            used_pairs.add(pair)
            records.append({
                'user_role_id': len(records) + 1,
                'user_id': user_id,
                'role_id': role_id,
                'granted_by': self._get_random_id('users'),
                'expires_at': self._random_datetime(-365) if random.random() > 0.8 else None,
                'created_at': self._random_datetime(365),
            })
        return records

    def generate_role_permissions(self) -> List[Dict[str, Any]]:
        """Generate role-permission assignment records."""
        records = []
        used_pairs = set()
        record_id = 1
        # Admin gets all permissions
        for perm_id in self._id_cache.get('permissions', range(1, 21)):
            records.append({
                'role_permission_id': record_id,
                'role_id': 1,  # ADMIN
                'permission_id': perm_id,
                'created_at': self._random_datetime(365),
            })
            used_pairs.add((1, perm_id))
            record_id += 1
        # Other roles get random permissions
        for role_id in range(2, 6):
            for perm_id in random.sample(list(self._id_cache.get('permissions', range(1, 21))), random.randint(3, 10)):
                if (role_id, perm_id) not in used_pairs:
                    records.append({
                        'role_permission_id': record_id,
                        'role_id': role_id,
                        'permission_id': perm_id,
                        'created_at': self._random_datetime(365),
                    })
                    used_pairs.add((role_id, perm_id))
                    record_id += 1
        return records

    def generate_sessions(self, count: int = 500) -> List[Dict[str, Any]]:
        """Generate session records."""
        records = []
        for i in range(count):
            records.append({
                'session_id': i + 1,
                'user_id': self._get_random_id('users'),
                'session_token': f"sess_{self.fake.uuid4()}",
                'ip_address': self.fake.ipv4(),
                'user_agent': self.fake.user_agent()[:500],
                'expires_at': self._random_datetime(-7),
                'is_revoked': random.random() > 0.9,
                'created_at': self._random_datetime(30),
            })
        return records

    def generate_api_keys(self, count: int = 100) -> List[Dict[str, Any]]:
        """Generate API key records."""
        records = []
        for i in range(count):
            records.append({
                'api_key_id': i + 1,
                'user_id': self._get_random_id('users'),
                'key_hash': self.fake.sha256(),
                'key_prefix': f"ak_{i:04d}",
                'name': f"API Key {i + 1}",
                'scopes': random.choice(['read', 'read,write', 'admin', 'read,write,delete']),
                'expires_at': self._random_datetime(-365) if random.random() > 0.3 else None,
                'last_used_at': self._random_datetime(7) if random.random() > 0.5 else None,
                'is_revoked': random.random() > 0.9,
                'created_at': self._random_datetime(365),
            })
        return records

    def generate_password_history(self, count: int = 500) -> List[Dict[str, Any]]:
        """Generate password history records."""
        records = []
        for i in range(count):
            records.append({
                'history_id': i + 1,
                'user_id': self._get_random_id('users'),
                'password_hash': self.fake.sha256(),
                'created_at': self._random_datetime(730),
            })
        return records

    def generate_login_attempts(self, count: int = 1000) -> List[Dict[str, Any]]:
        """Generate login attempt records."""
        records = []
        for i in range(count):
            success = random.random() > 0.15
            records.append({
                'attempt_id': i + 1,
                'user_id': self._get_random_id('users') if success or random.random() > 0.5 else None,
                'username_attempted': self.fake.user_name(),
                'ip_address': self.fake.ipv4(),
                'user_agent': self.fake.user_agent()[:500],
                'success': success,
                'failure_reason': None if success else random.choice(['INVALID_PASSWORD', 'ACCOUNT_LOCKED', 'USER_NOT_FOUND']),
                'attempted_at': self._random_datetime(90),
            })
        return records

    def generate_audit_logs(self, count: int = 1000) -> List[Dict[str, Any]]:
        """Generate audit log records."""
        records = []
        for i in range(count):
            records.append({
                'audit_id': i + 1,
                'user_id': self._get_random_id('users'),
                'action': random.choice(['CREATE', 'READ', 'UPDATE', 'DELETE', 'LOGIN', 'LOGOUT']),
                'entity_type': random.choice(['User', 'Order', 'Product', 'Account', 'Patient']),
                'entity_id': str(random.randint(1, 1000)),
                'old_values': '{"status": "pending"}' if random.random() > 0.5 else None,
                'new_values': '{"status": "completed"}' if random.random() > 0.5 else None,
                'ip_address': self.fake.ipv4(),
                'user_agent': self.fake.user_agent()[:500],
                'performed_at': self._random_datetime(90),
            })
        return records

    def generate_data_changes(self, count: int = 500) -> List[Dict[str, Any]]:
        """Generate data change records."""
        records = []
        for i in range(count):
            records.append({
                'change_id': i + 1,
                'table_name': random.choice(['users', 'orders', 'products', 'accounts', 'patients']),
                'record_id': str(random.randint(1, 1000)),
                'column_name': random.choice(['status', 'email', 'phone', 'balance', 'is_active']),
                'old_value': 'old_value',
                'new_value': 'new_value',
                'change_type': random.choice(['INSERT', 'UPDATE', 'DELETE']),
                'changed_by': self._get_random_id('users'),
                'changed_at': self._random_datetime(90),
            })
        return records

    def generate_access_logs(self, count: int = 1000) -> List[Dict[str, Any]]:
        """Generate access log records."""
        records = []
        for i in range(count):
            records.append({
                'access_id': i + 1,
                'user_id': self._get_random_id('users'),
                'resource_type': random.choice(['Patient', 'Account', 'Order', 'CreditCard', 'MedicalRecord']),
                'resource_id': str(random.randint(1, 1000)),
                'access_type': random.choice(['READ', 'WRITE', 'DELETE']),
                'query_text': f"SELECT * FROM table WHERE id = {random.randint(1, 1000)}",
                'row_count': random.randint(1, 100),
                'ip_address': self.fake.ipv4(),
                'accessed_at': self._random_datetime(30),
            })
        return records

    def generate_system_events(self, count: int = 500) -> List[Dict[str, Any]]:
        """Generate system event records."""
        records = []
        for i in range(count):
            records.append({
                'event_id': i + 1,
                'event_type': random.choice(['STARTUP', 'SHUTDOWN', 'BACKUP', 'RESTORE', 'MAINTENANCE', 'ALERT']),
                'severity': random.choice(['INFO', 'WARNING', 'ERROR', 'CRITICAL']),
                'source': random.choice(['WebServer', 'Database', 'Cache', 'Queue', 'Scheduler']),
                'message': f"System event message {i + 1}",
                'details': '{"key": "value"}' if random.random() > 0.5 else None,
                'occurred_at': self._random_datetime(90),
                'acknowledged_at': self._random_datetime(30) if random.random() > 0.7 else None,
                'acknowledged_by': self._get_random_id('users') if random.random() > 0.7 else None,
            })
        return records

    def generate_error_logs(self, count: int = 500) -> List[Dict[str, Any]]:
        """Generate error log records."""
        records = []
        for i in range(count):
            records.append({
                'error_id': i + 1,
                'error_code': f"ERR{random.randint(1000, 9999)}",
                'error_type': random.choice(['NullPointerException', 'SQLException', 'ValidationError', 'AuthError', 'TimeoutError']),
                'message': f"Error message {i + 1}",
                'stack_trace': 'at com.example.Class.method(Class.java:123)' if random.random() > 0.3 else None,
                'user_id': self._get_random_id('users') if random.random() > 0.5 else None,
                'request_url': f"/api/v1/{random.choice(['users', 'orders', 'products'])}/{random.randint(1, 1000)}",
                'request_method': random.choice(['GET', 'POST', 'PUT', 'DELETE']),
                'request_body': '{"key": "value"}' if random.random() > 0.7 else None,
                'ip_address': self.fake.ipv4(),
                'occurred_at': self._random_datetime(90),
                'resolved_at': self._random_datetime(30) if random.random() > 0.6 else None,
                'resolved_by': self._get_random_id('users') if random.random() > 0.6 else None,
            })
        return records

    def generate_system_config(self) -> List[Dict[str, Any]]:
        """Generate system config records."""
        configs = [
            ('app.name', 'Agent Performance Testing', 'STRING', 'application'),
            ('app.version', '1.0.0', 'STRING', 'application'),
            ('db.pool.size', '10', 'INTEGER', 'database'),
            ('db.timeout', '30000', 'INTEGER', 'database'),
            ('cache.enabled', 'true', 'BOOLEAN', 'cache'),
            ('cache.ttl', '3600', 'INTEGER', 'cache'),
            ('security.session.timeout', '1800', 'INTEGER', 'security'),
            ('security.max.login.attempts', '5', 'INTEGER', 'security'),
            ('email.smtp.host', 'smtp.example.com', 'STRING', 'email'),
            ('email.smtp.port', '587', 'INTEGER', 'email'),
        ]
        records = []
        for i, (key, value, vtype, category) in enumerate(configs):
            records.append({
                'config_id': i + 1,
                'config_key': key,
                'config_value': value,
                'value_type': vtype,
                'category': category,
                'description': f"Configuration for {key}",
                'is_encrypted': 'password' in key.lower() or 'secret' in key.lower(),
                'is_active': True,
                'created_at': self._random_datetime(365),
            })
        return records

    def generate_feature_flags(self) -> List[Dict[str, Any]]:
        """Generate feature flag records."""
        flags = [
            ('dark_mode', 'Dark Mode', 'Enable dark mode theme'),
            ('new_checkout', 'New Checkout Flow', 'New streamlined checkout'),
            ('ai_recommendations', 'AI Recommendations', 'AI-powered product recommendations'),
            ('two_factor_auth', 'Two Factor Auth', 'Require 2FA for all users'),
            ('beta_features', 'Beta Features', 'Enable beta features'),
        ]
        records = []
        for i, (key, name, desc) in enumerate(flags):
            start_date = self._random_datetime(30) if random.random() > 0.5 else None
            # End date is 30-90 days after start_date if set
            end_date = None
            if start_date and random.random() > 0.7:
                end_date = start_date + timedelta(days=random.randint(30, 90))
            records.append({
                'flag_id': i + 1,
                'flag_key': key,
                'flag_name': name,
                'description': desc,
                'is_enabled': random.random() > 0.5,
                'rollout_percentage': random.randint(0, 100),
                'target_users': None,
                'target_roles': None,
                'start_date': start_date,
                'end_date': end_date,
                'is_active': True,
                'created_at': self._random_datetime(180),
            })
        return records

    def generate_notifications(self, count: int = 500) -> List[Dict[str, Any]]:
        """Generate notification records."""
        records = []
        for i in range(count):
            is_read = random.random() > 0.4
            records.append({
                'notification_id': i + 1,
                'user_id': self._get_random_id('users'),
                'notification_type': random.choice(['ORDER_UPDATE', 'PAYMENT_RECEIVED', 'ACCOUNT_ALERT', 'SYSTEM_MESSAGE', 'PROMOTION']),
                'title': f"Notification {i + 1}",
                'message': f"This is notification message {i + 1}",
                'priority': random.choice(['LOW', 'NORMAL', 'HIGH', 'URGENT']),
                'is_read': is_read,
                'read_at': self._random_datetime(7) if is_read else None,
                'action_url': f"/notifications/{i + 1}" if random.random() > 0.5 else None,
                'expires_at': self._random_datetime(-30) if random.random() > 0.7 else None,
                'is_active': True,
                'created_at': self._random_datetime(30),
            })
        return records

    # =========================================================================
    # E-Commerce Domain Generators
    # =========================================================================

    def generate_customers(self, count: int) -> List[Dict[str, Any]]:
        """Generate customer records using ConfidentialData.

        SINGLE-PASS: Also collects actual customer_id values for params.
        """
        records = []
        for i in range(count):
            conf = self.conf_loader.get_next()
            record = {
                'customer_id': i + 1,
                'email': conf.get('EMAIL') or self.fake.email(),
                'first_name': conf.get('FIRSTNAME') or self.fake.first_name(),
                'last_name': conf.get('LASTNAME') or self.fake.last_name(),
                'phone': conf.get('PHONE') or self.fake.phone_number()[:20],
                'date_of_birth': conf.get('BIRTHDAY') if conf.get('BIRTHDAY') else self._random_date(365 * 60, 365 * 18),
                'gender': random.choice(['M', 'F', None]),
                'referral_code': f"REF{i + 1:06d}",  # Unique referral code
                'loyalty_points': random.randint(0, 10000),
                'loyalty_tier': random.choice(['STANDARD', 'SILVER', 'GOLD', 'PLATINUM']),
                'marketing_consent': random.random() > 0.3,
                'total_orders': random.randint(0, 50),
                'total_spent': round(random.uniform(0, 50000), 2),
                'is_active': random.random() > 0.05,
                'created_at': self._random_datetime(730),
            }
            records.append(record)

            # SINGLE-PASS: Collect actual values for params
            self.params.add('customer_ids', {'customer_id': record['customer_id']})

        self._cache_ids('customers', [r['customer_id'] for r in records])
        return records

    def generate_categories(self) -> List[Dict[str, Any]]:
        """Generate product category records."""
        categories = [
            'Electronics', 'Clothing', 'Home & Garden', 'Sports & Outdoors',
            'Books', 'Toys & Games', 'Beauty', 'Automotive', 'Health', 'Grocery',
            'Computers', 'Phones', 'Cameras', 'Audio', 'Appliances',
        ]
        records = []
        for i, name in enumerate(categories):
            records.append({
                'category_id': i + 1,
                'category_name': name,
                'slug': name.lower().replace(' & ', '-').replace(' ', '-'),
                'description': f"Products in the {name} category",
                'is_visible': True,
                'is_active': True,
                'sort_order': i,
            })
        self._cache_ids('categories', [r['category_id'] for r in records])
        return records

    def generate_brands(self, count: int = 50) -> List[Dict[str, Any]]:
        """Generate brand records."""
        records = []
        for i in range(count):
            name = self.fake.company()
            records.append({
                'brand_id': i + 1,
                'brand_name': name,
                'slug': name.lower().replace(' ', '-').replace('.', '').replace(',', '')[:100],
                'description': f"Products by {name}",
                'is_featured': random.random() > 0.8,
                'is_active': True,
            })
        self._cache_ids('brands', [r['brand_id'] for r in records])
        return records

    def generate_products(self, count: int) -> List[Dict[str, Any]]:
        """Generate product records.

        SINGLE-PASS: Also collects product_ids for JMX params.
        """
        records = []
        for i in range(count):
            name = f"{self.fake.word().capitalize()} {self.fake.word().capitalize()}"
            price = round(random.uniform(9.99, 999.99), 2)
            record = {
                'product_id': i + 1,
                'sku': f"SKU-{i + 1:06d}",  # Guaranteed unique SKU
                'product_name': name,
                'slug': f"product-{i + 1:06d}",  # Guaranteed unique slug
                'description': self.fake.text(max_nb_chars=500),
                'short_description': self.fake.text(max_nb_chars=100),
                'category_id': self._get_random_id('categories'),
                'brand_id': self._get_random_id('brands'),
                'price': price,
                'compare_at_price': round(price * 1.2, 2) if random.random() > 0.7 else None,
                'cost_price': round(price * 0.6, 2),
                'weight': round(random.uniform(0.1, 50), 2),
                'is_taxable': True,
                'is_visible': random.random() > 0.1,
                'is_featured': random.random() > 0.9,
                'requires_shipping': True,
                'is_active': random.random() > 0.05,
                'created_at': self._random_datetime(365),
            }
            records.append(record)

            # SINGLE-PASS: Collect product_ids for JMX params
            self.params.add('product_ids', {'product_id': record['product_id']})

        self._cache_ids('products', [r['product_id'] for r in records])
        return records

    def generate_orders(self, count: int) -> List[Dict[str, Any]]:
        """Generate order records.

        SINGLE-PASS: Also collects order_id, order_search, update_status params.
        """
        records = []
        for i in range(count):
            subtotal = round(random.uniform(25, 500), 2)
            tax = round(subtotal * 0.08, 2)
            shipping = round(random.uniform(5, 25), 2)
            order_date = self._random_datetime(365)
            status = self.fake.order_status()
            customer_id = self._get_random_id('customers')

            record = {
                'order_id': i + 1,
                'order_number': f"ORD-{i + 1:06d}",
                'customer_id': customer_id,
                'order_date': order_date,
                'status': status,
                'subtotal': subtotal,
                'discount_total': round(random.uniform(0, subtotal * 0.2), 2),
                'tax_total': tax,
                'shipping_total': shipping,
                'grand_total': round(subtotal + tax + shipping, 2),
                'currency_code': 'USD',
                'payment_status': self.fake.payment_status(),
                'shipping_method': random.choice(['Standard', 'Express', '2-Day', 'Overnight']),
                'shipping_carrier': self.fake.shipping_carrier(),
                'is_active': True,
                'created_at': self._random_datetime(365),
            }
            records.append(record)

            # SINGLE-PASS: Collect actual values for params
            # order_params - used by JMX for SELECT/UPDATE queries
            self.params.add('order_params', {
                'order_id': record['order_id'],
                'status': status,
                'amount': round(subtotal, 2),
            })

        self._cache_ids('orders', [r['order_id'] for r in records])
        return records

    def generate_customer_addresses(self, count: int = 2000) -> List[Dict[str, Any]]:
        """Generate customer address records."""
        records = []
        for i in range(count):
            records.append({
                'address_id': i + 1,
                'customer_id': self._get_random_id('customers'),
                'address_type': random.choice(['SHIPPING', 'BILLING']),
                'is_default': i % 2 == 0,
                'first_name': self.fake.first_name(),
                'last_name': self.fake.last_name(),
                'company': self.fake.company() if random.random() > 0.7 else None,
                'address_line1': self.fake.street_address(),
                'address_line2': self.fake.secondary_address() if random.random() > 0.7 else None,
                'city': self.fake.city(),
                'state': self.fake.state_abbr(),
                'postal_code': self.fake.zipcode(),
                'country_code': 'USA',
                'phone': self.fake.phone_number()[:20],
                'created_at': self._random_datetime(365),
            })
        return records

    def generate_customer_preferences(self, count: int = 1000) -> List[Dict[str, Any]]:
        """Generate customer preference records."""
        records = []
        prefs = ['newsletter', 'sms_alerts', 'dark_mode', 'language', 'currency']
        used_pairs = set()
        for i in range(count):
            cust = self._get_random_id('customers')
            pref = random.choice(prefs)
            # Ensure unique (customer_id, preference_key) pairs
            if (cust, pref) in used_pairs:
                continue
            used_pairs.add((cust, pref))
            records.append({
                'preference_id': len(records) + 1,
                'customer_id': cust,
                'preference_key': pref,
                'preference_value': random.choice(['true', 'false', 'en', 'USD']),
                'created_at': self._random_datetime(365),
            })
        return records

    def generate_customer_segments(self) -> List[Dict[str, Any]]:
        """Generate customer segment records."""
        segments = [
            ('VIP', 'High-value customers'),
            ('NEW', 'New customers (< 30 days)'),
            ('INACTIVE', 'Customers inactive > 90 days'),
            ('FREQUENT', 'Frequent buyers'),
            ('BARGAIN', 'Discount seekers'),
        ]
        records = []
        for i, (name, desc) in enumerate(segments):
            records.append({
                'segment_id': i + 1,
                'segment_name': name,
                'description': desc,
                'criteria': '{}',
                'is_dynamic': random.random() > 0.5,
                'is_active': True,
                'created_at': self._random_datetime(365),
            })
        self._cache_ids('customer_segments', [r['segment_id'] for r in records])
        return records

    def generate_customer_segment_members(self, count: int = 500) -> List[Dict[str, Any]]:
        """Generate customer segment member records."""
        records = []
        used_pairs = set()
        sources = ['MANUAL', 'IMPORT', 'RULE', 'CAMPAIGN', 'API']
        for i in range(count):
            cust = self._get_random_id('customers')
            seg = self._get_random_id('customer_segments')
            if (cust, seg) in used_pairs:
                continue
            used_pairs.add((cust, seg))
            records.append({
                'member_id': len(records) + 1,
                'segment_id': seg,
                'customer_id': cust,
                'added_at': self._random_datetime(180),
                'source': random.choice(sources),
                'created_at': self._random_datetime(180),
            })
        return records

    def generate_customer_notes(self, count: int = 500) -> List[Dict[str, Any]]:
        """Generate customer note records."""
        records = []
        for i in range(count):
            records.append({
                'note_id': i + 1,
                'customer_id': self._get_random_id('customers'),
                'note_type': random.choice(['GENERAL', 'COMPLAINT', 'FEEDBACK', 'INTERNAL']),
                'note_text': self.fake.text(max_nb_chars=200),
                'created_by_user_id': self._get_random_id('users'),
                'is_internal': random.choice([True, False]),
                'created_at': self._random_datetime(180),
            })
        return records

    def generate_customer_tags(self) -> List[Dict[str, Any]]:
        """Generate customer tag records."""
        tags = ['VIP', 'Wholesale', 'Retail', 'B2B', 'B2C', 'Premium', 'Standard', 'Trial']
        records = []
        for i, tag in enumerate(tags):
            records.append({
                'tag_id': i + 1,
                'tag_name': tag,
                'tag_color': f"#{random.randint(0, 0xFFFFFF):06x}",
                'created_at': self._random_datetime(365),
            })
        self._cache_ids('customer_tags', [r['tag_id'] for r in records])
        return records

    def generate_customer_tag_assignments(self, count: int = 500) -> List[Dict[str, Any]]:
        """Generate customer tag assignment records."""
        records = []
        used_pairs = set()
        for i in range(count):
            cust = self._get_random_id('customers')
            tag = self._get_random_id('customer_tags')
            if (cust, tag) in used_pairs:
                continue
            used_pairs.add((cust, tag))
            records.append({
                'assignment_id': len(records) + 1,
                'customer_id': cust,
                'tag_id': tag,
                'created_at': self._random_datetime(180),
            })
        return records

    def generate_product_images(self, count: int = 2000) -> List[Dict[str, Any]]:
        """Generate product image records."""
        records = []
        for i in range(count):
            records.append({
                'image_id': i + 1,
                'product_id': self._get_random_id('products'),
                'image_url': f"https://cdn.example.com/products/{random.randint(1000, 9999)}.jpg",
                'alt_text': f"Product image {i + 1}",
                'sort_order': random.randint(1, 5),
                'is_primary': i % 5 == 0,
                'created_at': self._random_datetime(365),
            })
        return records

    def generate_product_reviews(self, count: int = 1000) -> List[Dict[str, Any]]:
        """Generate product review records."""
        records = []
        for i in range(count):
            records.append({
                'review_id': i + 1,
                'product_id': self._get_random_id('products'),
                'customer_id': self._get_random_id('customers'),
                'rating': random.randint(1, 5),
                'title': f"Review {i + 1}",
                'review_text': self.fake.text(max_nb_chars=300),
                'is_verified_purchase': random.random() > 0.3,
                'is_approved': random.random() > 0.1,
                'is_active': True,
                'helpful_votes': random.randint(0, 50),
                'created_at': self._random_datetime(365),
            })
        return records

    def generate_inventory(self, count: int = 1000) -> List[Dict[str, Any]]:
        """Generate inventory records.

        Unique constraint: (product_id, variant_id, warehouse_code)
        """
        records = []
        used_pairs = set()  # Track unique (product_id, variant_id, warehouse_code) combinations
        warehouses = ['WH1', 'WH2', 'WH3']
        attempts = 0
        max_attempts = count * 10

        while len(records) < count and attempts < max_attempts:
            attempts += 1
            product_id = self._get_random_id('products')
            variant_id = None  # For simplicity, keeping variant_id as None
            warehouse_code = random.choice(warehouses)

            # Check unique constraint
            key = (product_id, variant_id, warehouse_code)
            if key in used_pairs:
                continue
            used_pairs.add(key)

            qty_on_hand = random.randint(0, 500)
            qty_reserved = random.randint(0, min(50, qty_on_hand))
            records.append({
                'inventory_id': len(records) + 1,
                'product_id': product_id,
                'variant_id': variant_id,
                'warehouse_code': warehouse_code,
                'quantity_on_hand': qty_on_hand,
                'quantity_reserved': qty_reserved,
                'quantity_available': qty_on_hand - qty_reserved,
                'reorder_point': random.randint(10, 50),
                'reorder_quantity': random.randint(50, 200),
                'last_restock_date': self._random_date(90),
                'created_at': self._random_datetime(365),
            })
        return records

    def generate_product_attributes(self) -> List[Dict[str, Any]]:
        """Generate product attribute records."""
        attrs = [
            ('Color', 'color', 'SELECT'), ('Size', 'size', 'SELECT'), ('Material', 'material', 'TEXT'),
            ('Weight', 'weight', 'NUMBER'), ('Brand', 'brand', 'TEXT'), ('Model', 'model', 'TEXT'),
        ]
        records = []
        for i, (name, code, atype) in enumerate(attrs):
            records.append({
                'attribute_id': i + 1,
                'attribute_name': name,
                'attribute_code': code,
                'attribute_type': atype,
                'is_required': random.random() > 0.5,
                'is_filterable': random.random() > 0.3,
                'created_at': self._random_datetime(365),
            })
        self._cache_ids('product_attributes', [r['attribute_id'] for r in records])
        return records

    def generate_product_attribute_values(self, count: int = 500) -> List[Dict[str, Any]]:
        """Generate product attribute value records.

        Unique constraint: (attribute_id, value_code)
        """
        values = ['Red', 'Blue', 'Green', 'Large', 'Medium', 'Small', 'XL', 'XXL', '100g', '250g', '500g', 'Cotton', 'Polyester', 'Wool']
        records = []
        used_pairs = set()  # Track unique (attribute_id, value_code) pairs
        attempts = 0
        max_attempts = count * 10

        while len(records) < count and attempts < max_attempts:
            attempts += 1
            attr_id = self._get_random_id('product_attributes')
            val = random.choice(values)
            value_code = val.lower().replace(' ', '_')

            # Check unique constraint
            key = (attr_id, value_code)
            if key in used_pairs:
                continue
            used_pairs.add(key)

            records.append({
                'value_id': len(records) + 1,
                'attribute_id': attr_id,
                'value_label': val,
                'value_code': value_code,
                'sort_order': random.randint(1, 10),
                'swatch_value': f"#{random.randint(0, 0xFFFFFF):06x}" if random.random() > 0.5 else None,
                'created_at': self._random_datetime(365),
            })
        self._cache_ids('product_attribute_values', [r['value_id'] for r in records])
        return records

    def generate_product_variants(self, count: int = 500) -> List[Dict[str, Any]]:
        """Generate product variant records."""
        records = []
        for i in range(count):
            price = round(random.uniform(9.99, 499.99), 2)
            records.append({
                'variant_id': i + 1,
                'product_id': self._get_random_id('products'),
                'sku': f"VAR-{i + 1:06d}",
                'price': price,
                'compare_at_price': round(price * random.uniform(1.1, 1.5), 2) if random.random() > 0.5 else None,
                'weight': round(random.uniform(0.1, 50.0), 2),
                'barcode': f"{random.randint(100000000000, 999999999999)}",
                'is_default': i % 5 == 0,
                'created_by': self._get_random_id('users'),
                'is_active': True,
                'created_at': self._random_datetime(365),
            })
        self._cache_ids('product_variants', [r['variant_id'] for r in records])
        return records

    def generate_product_variant_attributes(self, count: int = 500) -> List[Dict[str, Any]]:
        """Generate product variant attribute records.

        Unique constraint: (variant_id, attribute_id)
        """
        records = []
        used_pairs = set()  # Track unique (variant_id, attribute_id) pairs
        attempts = 0
        max_attempts = count * 10

        while len(records) < count and attempts < max_attempts:
            attempts += 1
            variant_id = self._get_random_id('product_variants')
            attribute_id = self._get_random_id('product_attributes')

            # Check unique constraint
            key = (variant_id, attribute_id)
            if key in used_pairs:
                continue
            used_pairs.add(key)

            records.append({
                'id': len(records) + 1,
                'variant_id': variant_id,
                'attribute_id': attribute_id,
                'value_id': self._get_random_id('product_attribute_values') if random.random() > 0.3 else None,
                'text_value': random.choice(['Red', 'Blue', 'Green', 'S', 'M', 'L', 'XL']) if random.random() > 0.5 else None,
                'created_at': self._random_datetime(365),
            })
        return records

    def generate_product_bundles(self, count: int = 50) -> List[Dict[str, Any]]:
        """Generate product bundle records."""
        records = []
        for i in range(count):
            records.append({
                'bundle_id': i + 1,
                'bundle_name': f"Bundle {i + 1}",
                'description': f"Product bundle {i + 1}",
                'bundle_price': round(random.uniform(50, 300), 2),
                'discount_type': random.choice(['PERCENTAGE', 'FIXED']),
                'discount_value': round(random.uniform(5, 30), 2),
                'created_by': self._get_random_id('users') if 'users' in self._id_cache else None,
                'is_active': True,
                'created_at': self._random_datetime(365),
            })
        self._cache_ids('product_bundles', [r['bundle_id'] for r in records])
        return records

    def generate_product_bundle_items(self, count: int = 150) -> List[Dict[str, Any]]:
        """Generate product bundle item records."""
        records = []
        for i in range(count):
            records.append({
                'item_id': i + 1,
                'bundle_id': self._get_random_id('product_bundles'),
                'product_id': self._get_random_id('products'),
                'variant_id': self._get_random_id('product_variants') if random.random() > 0.5 else None,
                'quantity': random.randint(1, 3),
                'created_at': self._random_datetime(365),
            })
        return records

    def generate_order_items(self, count: int = 3000) -> List[Dict[str, Any]]:
        """Generate order item records."""
        records = []
        for i in range(count):
            quantity = random.randint(1, 5)
            price = round(random.uniform(9.99, 199.99), 2)
            is_gift = random.random() > 0.9
            records.append({
                'item_id': i + 1,
                'order_id': self._get_random_id('orders'),
                'product_id': self._get_random_id('products'),
                'variant_id': None,
                'sku': f"SKU-{random.randint(1, 1000):06d}",
                'product_name': f"Product {random.randint(1, 1000)}",
                'quantity': quantity,
                'unit_price': price,
                'discount_amount': round(price * 0.1, 2) if random.random() > 0.7 else 0,
                'tax_amount': round(price * quantity * 0.08, 2),
                'line_total': round(price * quantity, 2),
                'is_gift': is_gift,
                'gift_message': self.fake.sentence() if is_gift else None,
                'created_at': self._random_datetime(365),
            })
        self._cache_ids('order_items', [r['item_id'] for r in records])
        return records

    def generate_order_status_history(self, count: int = 2000) -> List[Dict[str, Any]]:
        """Generate order status history records."""
        records = []
        for i in range(count):
            records.append({
                'history_id': i + 1,
                'order_id': self._get_random_id('orders'),
                'status': random.choice(['PENDING', 'CONFIRMED', 'PROCESSING', 'SHIPPED', 'DELIVERED']),
                'notes': f"Status update {i + 1}" if random.random() > 0.5 else None,
                'changed_by': self._get_random_id('users'),
                'changed_at': self._random_datetime(180),
            })
        return records

    def generate_shipments(self, count: int = 800) -> List[Dict[str, Any]]:
        """Generate shipment records."""
        records = []
        for i in range(count):
            carrier = random.choice(['UPS', 'FedEx', 'USPS', 'DHL'])
            records.append({
                'shipment_id': i + 1,
                'order_id': self._get_random_id('orders'),
                'shipment_number': f"SHP-{i + 1:08d}",
                'carrier': carrier,
                'service': random.choice(['Ground', 'Express', '2-Day', 'Overnight', 'Standard']),
                'tracking_number': f"TRK{random.randint(100000000, 999999999)}",
                'tracking_url': f"https://{carrier.lower()}.com/track/{random.randint(100000000, 999999999)}",
                'status': random.choice(['PENDING', 'IN_TRANSIT', 'DELIVERED', 'RETURNED']),
                'shipped_at': self._random_datetime(30) if random.random() > 0.3 else None,
                'delivered_at': self._random_datetime(7) if random.random() > 0.5 else None,
                'weight': round(random.uniform(0.5, 50.0), 3),
                'shipping_cost': round(random.uniform(5.0, 150.0), 2),
                'created_at': self._random_datetime(60),
            })
        self._cache_ids('shipments', [r['shipment_id'] for r in records])
        return records

    def generate_shipment_items(self, count: int = 1500) -> List[Dict[str, Any]]:
        """Generate shipment item records."""
        records = []
        for i in range(count):
            records.append({
                'id': i + 1,
                'shipment_id': self._get_random_id('shipments'),
                'order_item_id': self._get_random_id('order_items'),
                'quantity': random.randint(1, 3),
                'created_at': self._random_datetime(60),
            })
        return records

    def generate_returns(self, count: int = 200) -> List[Dict[str, Any]]:
        """Generate return records."""
        records = []
        for i in range(count):
            status = random.choice(['PENDING', 'APPROVED', 'RECEIVED', 'REFUNDED', 'REJECTED'])
            records.append({
                'return_id': i + 1,
                'order_id': self._get_random_id('orders'),
                'return_number': f"RET-{i + 1:06d}",
                'status': status,
                'reason': random.choice(['DEFECTIVE', 'WRONG_ITEM', 'NOT_AS_DESCRIBED', 'CHANGED_MIND']),
                'notes': self.fake.sentence() if random.random() > 0.5 else None,
                'requested_at': self._random_datetime(90),
                'approved_at': self._random_datetime(85) if status in ['APPROVED', 'RECEIVED', 'REFUNDED'] else None,
                'received_at': self._random_datetime(80) if status in ['RECEIVED', 'REFUNDED'] else None,
                'refund_amount': round(random.uniform(10, 200), 2),
                'created_by': self.fake.user_name(),
                'updated_by': self.fake.user_name() if random.random() > 0.5 else None,
                'is_active': True,
                'created_at': self._random_datetime(90),
            })
        self._cache_ids('returns', [r['return_id'] for r in records])
        return records

    def generate_return_items(self, count: int = 400) -> List[Dict[str, Any]]:
        """Generate return item records."""
        records = []
        for i in range(count):
            records.append({
                'id': i + 1,
                'return_id': self._get_random_id('returns'),
                'order_item_id': self._get_random_id('order_items'),
                'quantity': random.randint(1, 2),
                'reason': random.choice(['DEFECTIVE', 'WRONG_SIZE', 'NOT_AS_EXPECTED']),
                'condition': random.choice(['NEW', 'LIKE_NEW', 'GOOD', 'FAIR', 'POOR']),
                'created_at': self._random_datetime(90),
            })
        return records

    def generate_order_notes(self, count: int = 500) -> List[Dict[str, Any]]:
        """Generate order note records."""
        records = []
        for i in range(count):
            records.append({
                'note_id': i + 1,
                'order_id': self._get_random_id('orders'),
                'note_text': self.fake.text(max_nb_chars=200),
                'is_customer_visible': random.choice([True, False]),
                'created_by': self._get_random_id('users'),
                'created_at': self._random_datetime(180),
            })
        return records

    def generate_order_tags(self) -> List[Dict[str, Any]]:
        """Generate order tag records."""
        tags = ['RUSH', 'GIFT', 'FRAGILE', 'WHOLESALE', 'PRIORITY', 'HOLD']
        records = []
        for i, tag in enumerate(tags):
            records.append({
                'tag_id': i + 1,
                'tag_name': tag,
                'tag_color': f"#{random.randint(0, 0xFFFFFF):06x}",
                'created_at': self._random_datetime(365),
            })
        self._cache_ids('order_tags', [r['tag_id'] for r in records])
        return records

    def generate_order_discounts(self, count: int = 500) -> List[Dict[str, Any]]:
        """Generate order discount records."""
        records = []
        for i in range(count):
            records.append({
                'discount_id': i + 1,
                'order_id': self._get_random_id('orders'),
                'coupon_id': self._get_random_id('coupons') if random.random() > 0.3 else None,
                'discount_type': random.choice(['PERCENTAGE', 'FIXED', 'FREE_SHIPPING']),
                'description': random.choice(['Holiday Sale', 'First Order', 'Loyalty Reward', 'Promo Code', 'Bundle Discount']),
                'discount_value': round(random.uniform(5, 50), 2),
                'created_at': self._random_datetime(180),
            })
        return records

    def generate_shopping_carts(self, count: int = 500) -> List[Dict[str, Any]]:
        """Generate shopping cart records."""
        records = []
        for i in range(count):
            is_abandoned = random.random() > 0.7
            is_recovered = is_abandoned and random.random() > 0.8
            records.append({
                'cart_id': i + 1,
                'customer_id': self._get_random_id('customers') if random.random() > 0.3 else None,
                'session_id': f"sess_{self.fake.uuid4()}",
                'last_activity': self._random_datetime(7),
                'abandoned_at': self._random_datetime(14) if is_abandoned else None,
                'recovered_at': self._random_datetime(7) if is_recovered else None,
                'item_count': random.randint(1, 10),
                'subtotal': round(random.uniform(25, 500), 2),
                'created_at': self._random_datetime(30),
            })
        self._cache_ids('shopping_carts', [r['cart_id'] for r in records])
        return records

    def generate_cart_items(self, count: int = 1000) -> List[Dict[str, Any]]:
        """Generate cart item records."""
        records = []
        for i in range(count):
            records.append({
                'item_id': i + 1,
                'cart_id': self._get_random_id('shopping_carts'),
                'product_id': self._get_random_id('products'),
                'variant_id': None,
                'quantity': random.randint(1, 5),
                'unit_price': round(random.uniform(9.99, 199.99), 2),
                'created_at': self._random_datetime(30),
            })
        return records

    def generate_saved_for_later(self, count: int = 300) -> List[Dict[str, Any]]:
        """Generate saved for later records."""
        records = []
        for i in range(count):
            records.append({
                'id': i + 1,
                'cart_id': self._get_random_id('shopping_carts'),
                'product_id': self._get_random_id('products'),
                'variant_id': self._get_random_id('product_variants') if random.random() > 0.5 else None,
                'created_at': self._random_datetime(90),
            })
        return records

    def generate_order_fulfillment(self, count: int = 800) -> List[Dict[str, Any]]:
        """Generate order fulfillment records."""
        records = []
        for i in range(count):
            records.append({
                'fulfillment_id': i + 1,
                'order_id': self._get_random_id('orders'),
                'fulfillment_number': f"FUL-{i + 1:06d}",
                'status': random.choice(['PENDING', 'PICKING', 'PACKING', 'SHIPPED']),
                'location': random.choice(['WAREHOUSE_A', 'WAREHOUSE_B', 'WAREHOUSE_C', 'DC_EAST', 'DC_WEST']),
                'assigned_to': self._get_random_id('users') if random.random() > 0.5 else None,
                'created_at': self._random_datetime(60),
            })
        self._cache_ids('order_fulfillment', [r['fulfillment_id'] for r in records])
        return records

    def generate_fulfillment_items(self, count: int = 1500) -> List[Dict[str, Any]]:
        """Generate fulfillment item records."""
        records = []
        for i in range(count):
            picked_time = self._random_datetime(60)
            records.append({
                'id': i + 1,
                'fulfillment_id': self._get_random_id('order_fulfillment'),
                'order_item_id': self._get_random_id('order_items'),
                'quantity': random.randint(1, 3),
                'picked_at': picked_time if random.random() > 0.2 else None,
                'packed_at': picked_time + timedelta(hours=random.randint(1, 8)) if random.random() > 0.3 else None,
                'created_at': self._random_datetime(60),
            })
        return records

    def generate_payment_methods(self, count: int = 500) -> List[Dict[str, Any]]:
        """Generate payment method records."""
        records = []
        for i in range(count):
            records.append({
                'method_id': i + 1,
                'customer_id': self._get_random_id('customers'),
                'method_type': random.choice(['CREDIT_CARD', 'DEBIT_CARD', 'PAYPAL', 'BANK_ACCOUNT']),
                'provider': random.choice(['Stripe', 'PayPal', 'Square']),
                'last_four': str(random.randint(1000, 9999)),
                'expiry_month': random.randint(1, 12) if random.random() > 0.3 else None,
                'expiry_year': random.randint(2024, 2030) if random.random() > 0.3 else None,
                'is_default': i % 3 == 0,
                'is_active': True,
                'created_at': self._random_datetime(365),
            })
        self._cache_ids('payment_methods', [r['method_id'] for r in records])
        return records

    def generate_transactions_ecom(self, count: int = 1000) -> List[Dict[str, Any]]:
        """Generate e-commerce transaction records."""
        records = []
        gateways = ['Stripe', 'PayPal', 'Square', 'Braintree', 'Authorize.net']
        for i in range(count):
            status = random.choice(['PENDING', 'COMPLETED', 'FAILED', 'REFUNDED'])
            is_failed = status == 'FAILED'
            records.append({
                'transaction_id': i + 1,
                'order_id': self._get_random_id('orders'),
                'payment_method_id': self._get_random_id('payment_methods'),
                'transaction_type': random.choice(['CHARGE', 'REFUND', 'VOID']),
                'amount': round(random.uniform(10, 500), 2),
                'currency_code': 'USD',
                'status': status,
                'gateway': random.choice(gateways),
                'gateway_transaction_id': f"txn_{self.fake.uuid4()}",
                'processed_at': self._random_datetime(7) if status == 'COMPLETED' else None,
                'gateway_response': '{"status": "success"}' if not is_failed else '{"status": "failed"}',
                'error_code': random.choice(['E001', 'E002', 'E003', 'DECLINED']) if is_failed else None,
                'error_message': 'Transaction declined' if is_failed else None,
                'created_at': self._random_datetime(180),
            })
        self._cache_ids('transactions', [r['transaction_id'] for r in records])
        return records

    def generate_refunds(self, count: int = 200) -> List[Dict[str, Any]]:
        """Generate refund records."""
        records = []
        for i in range(count):
            records.append({
                'refund_id': i + 1,
                'order_id': self._get_random_id('orders'),
                'transaction_id': self._get_random_id('transactions'),
                'return_id': self._get_random_id('returns') if random.random() > 0.5 else None,
                'amount': round(random.uniform(10, 200), 2),
                'reason': random.choice(['CUSTOMER_REQUEST', 'DEFECTIVE', 'WRONG_ITEM', 'DUPLICATE']),
                'notes': self.fake.sentence() if random.random() > 0.5 else None,
                'status': random.choice(['PENDING', 'PROCESSED', 'FAILED']),
                'processed_at': self._random_datetime(30) if random.random() > 0.5 else None,
                'processed_by': self._get_random_id('users') if random.random() > 0.5 else None,
                'created_at': self._random_datetime(90),
            })
        return records

    def generate_invoices(self, count: int = 800) -> List[Dict[str, Any]]:
        """Generate invoice records."""
        records = []
        for i in range(count):
            subtotal = round(random.uniform(50, 500), 2)
            discount_total = round(random.uniform(0, 50), 2) if random.random() > 0.6 else 0
            tax_total = round(random.uniform(5, 50), 2)
            grand_total = round(subtotal - discount_total + tax_total, 2)
            is_paid = random.random() > 0.4
            amount_paid = grand_total if is_paid else round(random.uniform(0, grand_total), 2)
            records.append({
                'invoice_id': i + 1,
                'order_id': self._get_random_id('orders'),
                'invoice_number': f"INV-{i + 1:06d}",
                'invoice_date': self._random_date(180, 0),
                'subtotal': subtotal,
                'discount_total': discount_total,
                'tax_total': tax_total,
                'grand_total': grand_total,
                'amount_paid': amount_paid,
                'amount_due': round(grand_total - amount_paid, 2),
                'status': random.choice(['DRAFT', 'SENT', 'PAID', 'VOID']),
                'due_date': self._random_datetime(-30),
                'is_active': True,
                'created_at': self._random_datetime(180),
            })
        self._cache_ids('invoices', [r['invoice_id'] for r in records])
        return records

    def generate_invoice_items(self, count: int = 2000) -> List[Dict[str, Any]]:
        """Generate invoice item records."""
        records = []
        for i in range(count):
            qty = random.randint(1, 5)
            price = round(random.uniform(10, 100), 2)
            tax_rate = round(random.uniform(0.05, 0.12), 4)
            line_total = round(qty * price, 2)
            tax_amount = round(line_total * tax_rate, 2)
            records.append({
                'item_id': i + 1,
                'invoice_id': self._get_random_id('invoices'),
                'description': f"Invoice item {i + 1}",
                'quantity': qty,
                'unit_price': price,
                'line_total': line_total,
                'tax_rate': tax_rate,
                'tax_amount': tax_amount,
                'created_at': self._random_datetime(180),
            })
        return records

    def generate_gift_cards(self, count: int = 200) -> List[Dict[str, Any]]:
        """Generate gift card records."""
        records = []
        for i in range(count):
            amount = round(random.uniform(25, 200), 2)
            records.append({
                'card_id': i + 1,
                'card_code': f"GC{random.randint(100000000, 999999999)}",
                'initial_balance': amount,
                'current_balance': round(amount * random.uniform(0, 1), 2),
                'purchaser_customer_id': self._get_random_id('customers'),
                'recipient_email': self.fake.email() if random.random() > 0.5 else None,
                'is_active': True,
                'expires_at': self._random_datetime(-365),
                'created_at': self._random_datetime(180),
            })
        self._cache_ids('gift_cards', [r['card_id'] for r in records])
        return records

    def generate_gift_card_transactions(self, count: int = 400) -> List[Dict[str, Any]]:
        """Generate gift card transaction records."""
        records = []
        for i in range(count):
            amount = round(random.uniform(10, 100), 2)
            records.append({
                'transaction_id': i + 1,
                'card_id': self._get_random_id('gift_cards'),
                'order_id': self._get_random_id('orders') if random.random() > 0.3 else None,
                'transaction_type': random.choice(['PURCHASE', 'REDEMPTION', 'REFUND']),
                'amount': amount,
                'balance_after': round(random.uniform(0, 500), 2),
                'created_at': self._random_datetime(180),
            })
        return records

    def generate_payment_plans(self, count: int = 200) -> List[Dict[str, Any]]:
        """Generate payment plan records."""
        records = []
        for i in range(count):
            total_amount = round(random.uniform(200, 2000), 2)
            installment_count = random.choice([3, 6, 12])
            frequency = random.choice(['WEEKLY', 'BIWEEKLY', 'MONTHLY'])
            records.append({
                'plan_id': i + 1,
                'order_id': self._get_random_id('orders'),
                'customer_id': self._get_random_id('customers'),
                'total_amount': total_amount,
                'installment_count': installment_count,
                'installment_amount': round(total_amount / installment_count, 2),
                'frequency': frequency,
                'start_date': self._random_date(180, 30),
                'status': random.choice(['ACTIVE', 'COMPLETED', 'DEFAULTED']),
                'is_active': True,
                'created_at': self._random_datetime(180),
            })
        self._cache_ids('payment_plans', [r['plan_id'] for r in records])
        return records

    def generate_payment_plan_installments(self, count: int = 500) -> List[Dict[str, Any]]:
        """Generate payment plan installment records."""
        records = []
        for i in range(count):
            records.append({
                'installment_id': i + 1,
                'plan_id': self._get_random_id('payment_plans'),
                'installment_number': random.randint(1, 12),
                'amount': round(random.uniform(50, 500), 2),
                'due_date': self._random_datetime(-60),
                'paid_date': self._random_date(7, 0) if random.random() > 0.3 else None,
                'status': random.choice(['PENDING', 'PAID', 'OVERDUE']),
                'created_at': self._random_datetime(180),
            })
        return records

    def generate_wallets(self, count: int = 300) -> List[Dict[str, Any]]:
        """Generate wallet records."""
        records = []
        for i in range(count):
            records.append({
                'wallet_id': i + 1,
                'customer_id': self._get_random_id('customers'),
                'balance': round(random.uniform(0, 500), 2),
                'currency_code': 'USD',
                'is_active': True,
                'last_transaction_at': self._random_datetime(30) if random.random() > 0.3 else None,
                'created_at': self._random_datetime(365),
            })
        return records

    def generate_campaigns(self, count: int = 50) -> List[Dict[str, Any]]:
        """Generate campaign records."""
        records = []
        for i in range(count):
            records.append({
                'campaign_id': i + 1,
                'campaign_name': f"Campaign {i + 1}",
                'campaign_type': random.choice(['EMAIL', 'SMS', 'PUSH', 'SOCIAL']),
                'status': random.choice(['DRAFT', 'ACTIVE', 'PAUSED', 'COMPLETED']),
                'target_segment_id': self._get_random_id('customer_segments') if random.random() > 0.3 else None,
                'start_date': self._random_datetime(30),
                'end_date': self._random_datetime(-30) if random.random() > 0.5 else None,
                'budget': round(random.uniform(1000, 50000), 2) if random.random() > 0.5 else None,
                'is_active': True,
                'created_at': self._random_datetime(180),
            })
        self._cache_ids('campaigns', [r['campaign_id'] for r in records])
        return records

    def generate_promotions(self, count: int = 30) -> List[Dict[str, Any]]:
        """Generate promotion records."""
        records = []
        for i in range(count):
            records.append({
                'promotion_id': i + 1,
                'promotion_name': f"Promotion {i + 1}",
                'promotion_type': random.choice(['PERCENTAGE', 'FIXED', 'BOGO', 'FREE_SHIPPING']),
                'discount_value': round(random.uniform(5, 50), 2),
                'min_purchase': round(random.uniform(25, 100), 2) if random.random() > 0.5 else None,
                'max_discount': round(random.uniform(50, 200), 2) if random.random() > 0.5 else None,
                'start_date': self._random_datetime(30),
                'end_date': self._random_datetime(-30),
                'applies_to': random.choice(['ALL', 'CATEGORY', 'PRODUCT', 'BRAND']),
                'is_stackable': random.random() > 0.7,
                'is_active': True,
                'created_at': self._random_datetime(180),
            })
        self._cache_ids('promotions', [r['promotion_id'] for r in records])
        return records

    def generate_coupons(self, count: int = 100) -> List[Dict[str, Any]]:
        """Generate coupon records."""
        records = []
        for i in range(count):
            records.append({
                'coupon_id': i + 1,
                'coupon_code': f"SAVE{i + 1:03d}",
                'description': f"Discount coupon {i + 1}",
                'discount_type': random.choice(['PERCENTAGE', 'FIXED']),
                'discount_value': round(random.uniform(5, 30), 2),
                'min_purchase': round(random.uniform(25, 100), 2) if random.random() > 0.5 else None,
                'max_discount': round(random.uniform(50, 200), 2) if random.random() > 0.5 else None,
                'usage_limit': random.randint(100, 1000) if random.random() > 0.5 else None,
                'usage_count': random.randint(0, 100),
                'per_customer_limit': random.randint(1, 5) if random.random() > 0.5 else None,
                'start_date': self._random_datetime(30),
                'end_date': self._random_datetime(-60),
                'first_order_only': random.random() > 0.7,
                'is_active': True,
                'created_at': self._random_datetime(180),
            })
        self._cache_ids('coupons', [r['coupon_id'] for r in records])
        return records

    def generate_coupon_usage(self, count: int = 300) -> List[Dict[str, Any]]:
        """Generate coupon usage records."""
        records = []
        for i in range(count):
            records.append({
                'usage_id': i + 1,
                'coupon_id': self._get_random_id('coupons'),
                'order_id': self._get_random_id('orders'),
                'customer_id': self._get_random_id('customers'),
                'discount_amount': round(random.uniform(5, 50), 2),
                'created_at': self._random_datetime(90),
            })
        return records

    def generate_wishlists(self, count: int = 300) -> List[Dict[str, Any]]:
        """Generate wishlist records."""
        records = []
        for i in range(count):
            records.append({
                'wishlist_id': i + 1,
                'customer_id': self._get_random_id('customers'),
                'wishlist_name': random.choice(['My Wishlist', 'Birthday', 'Holiday', 'Ideas']),
                'is_public': random.random() > 0.7,
                'is_active': True,
                'created_at': self._random_datetime(180),
            })
        self._cache_ids('wishlists', [r['wishlist_id'] for r in records])
        return records

    def generate_wishlist_items(self, count: int = 800) -> List[Dict[str, Any]]:
        """Generate wishlist item records."""
        records = []
        for i in range(count):
            records.append({
                'item_id': i + 1,
                'wishlist_id': self._get_random_id('wishlists'),
                'product_id': self._get_random_id('products'),
                'priority': random.randint(1, 5) if random.random() > 0.5 else None,
                'notes': self.fake.text(max_nb_chars=100) if random.random() > 0.7 else None,
                'created_at': self._random_datetime(180),
            })
        return records

    def generate_recommendations(self, count: int = 500) -> List[Dict[str, Any]]:
        """Generate recommendation records."""
        records = []
        for i in range(count):
            records.append({
                'recommendation_id': i + 1,
                'customer_segment_id': self._get_random_id('customers'),
                'source_product_id': self._get_random_id('products'),
                'target_product_id': self._get_random_id('products'),
                'recommendation_type': random.choice(['SIMILAR', 'BOUGHT_TOGETHER', 'TRENDING', 'PERSONALIZED']),
                'score': round(random.uniform(0.1, 1.0), 3),
                'created_at': self._random_datetime(30),
            })
        self._cache_ids('recommendations', [r['recommendation_id'] for r in records])
        return records

    def generate_recommendation_clicks(self, count: int = 1000) -> List[Dict[str, Any]]:
        """Generate recommendation click records."""
        records = []
        for i in range(count):
            clicked_time = self._random_datetime(30)
            converted = random.random() > 0.7
            records.append({
                'click_id': i + 1,
                'recommendation_id': self._get_random_id('recommendations'),
                'customer_id': self._get_random_id('customers'),
                'session_id': f"sess_{self.fake.uuid4()}",
                'clicked_at': clicked_time,
                'converted': converted,
                'converted_at': clicked_time + timedelta(minutes=random.randint(1, 60)) if converted else None,
            })
        return records

    def generate_page_views(self, count: int = 2000) -> List[Dict[str, Any]]:
        """Generate page view records."""
        records = []
        for i in range(count):
            page_type = random.choice(['HOME', 'CATEGORY', 'PRODUCT', 'CART', 'CHECKOUT'])
            records.append({
                'view_id': i + 1,
                'customer_id': self._get_random_id('customers') if random.random() > 0.3 else None,
                'session_id': f"sess_{self.fake.uuid4()}",
                'page_url': f"/products/{random.randint(1, 1000)}",
                'page_type': page_type,
                'referrer_url': self.fake.url() if random.random() > 0.5 else None,
                'ip_address': self.fake.ipv4(),
                'user_agent': self.fake.user_agent()[:500],
                'device_type': random.choice(['DESKTOP', 'MOBILE', 'TABLET']),
                'time_on_page': random.randint(5, 600),
                'product_id': self._get_random_id('products') if page_type == 'PRODUCT' else None,
                'category_id': self._get_random_id('categories') if page_type == 'CATEGORY' else None,
                'viewed_at': self._random_datetime(30),
            })
        return records

    def generate_conversion_events(self, count: int = 500) -> List[Dict[str, Any]]:
        """Generate conversion event records."""
        records = []
        for i in range(count):
            records.append({
                'event_id': i + 1,
                'customer_id': self._get_random_id('customers'),
                'session_id': f"sess_{self.fake.uuid4()}",
                'event_type': random.choice(['ADD_TO_CART', 'CHECKOUT_START', 'PURCHASE', 'SIGNUP']),
                'product_id': self._get_random_id('products') if random.random() > 0.3 else None,
                'order_id': self._get_random_id('orders') if random.random() > 0.5 else None,
                'value': round(random.uniform(10, 500), 2) if random.random() > 0.5 else None,
                'attribution_source': random.choice(['google', 'facebook', 'email', 'direct', 'organic']),
                'attribution_medium': random.choice(['cpc', 'organic', 'referral', 'email', 'social']),
                'attribution_campaign': f"campaign_{random.randint(1, 100)}" if random.random() > 0.3 else None,
                'occurred_at': self._random_datetime(90),
            })
        return records

    def generate_sales_daily(self, count: int = 365) -> List[Dict[str, Any]]:
        """Generate daily sales records."""
        records = []
        base_date = datetime.now() - timedelta(days=365)
        for i in range(count):
            gross_sales = round(random.uniform(5000, 50000), 2)
            discount_total = round(random.uniform(100, 1000), 2)
            shipping_total = round(random.uniform(200, 2000), 2)
            tax_total = round(gross_sales * 0.08, 2)
            refund_total = round(random.uniform(0, 500), 2)
            net_sales = round(gross_sales - discount_total - refund_total, 2)
            records.append({
                'id': i + 1,
                'sales_date': (base_date + timedelta(days=i)).date(),
                'order_count': random.randint(50, 500),
                'gross_sales': gross_sales,
                'net_sales': net_sales,
                'discount_total': discount_total,
                'shipping_total': shipping_total,
                'tax_total': tax_total,
                'refund_total': refund_total,
                'item_count': random.randint(100, 1000),
                'new_customer_count': random.randint(10, 100),
                'returning_customer_count': random.randint(40, 400),
            })
        return records

    def generate_product_performance(self, count: int = 500) -> List[Dict[str, Any]]:
        """Generate product performance records.

        Unique constraint: (product_id, period_date)
        """
        records = []
        used_pairs = set()  # Track unique (product_id, period_date) pairs
        attempts = 0
        max_attempts = count * 10

        while len(records) < count and attempts < max_attempts:
            attempts += 1
            product_id = self._get_random_id('products')
            period_date = self._random_date(90, 0)

            # Check unique constraint
            key = (product_id, period_date)
            if key in used_pairs:
                continue
            used_pairs.add(key)

            views = random.randint(100, 10000)
            cart_adds = random.randint(10, 500)
            purchases = random.randint(5, 200)
            records.append({
                'id': len(records) + 1,
                'product_id': product_id,
                'period_date': period_date,
                'views': views,
                'cart_adds': cart_adds,
                'purchases': purchases,
                'units_sold': random.randint(purchases, purchases * 3),
                'revenue': round(random.uniform(100, 10000), 2),
                'conversion_rate': round(purchases / views * 100, 2) if views > 0 else 0,
                'avg_rating': round(random.uniform(3.0, 5.0), 2),
                'review_count': random.randint(0, 100),
                'returns': random.randint(0, max(1, purchases // 10)),
            })
        return records

    def generate_search_queries(self, count: int = 1000) -> List[Dict[str, Any]]:
        """Generate search query records."""
        records = []
        for i in range(count):
            records.append({
                'query_id': i + 1,
                'customer_id': self._get_random_id('customers') if random.random() > 0.3 else None,
                'session_id': f"sess_{self.fake.uuid4()}",
                'query_text': self.fake.word(),
                'result_count': random.randint(0, 500),
                'clicked_product_id': self._get_random_id('products') if random.random() > 0.5 else None,
                'converted': random.random() > 0.8,
                'searched_at': self._random_datetime(30),
            })
        return records

    def generate_abandoned_carts(self, count: int = 300) -> List[Dict[str, Any]]:
        """Generate abandoned cart records."""
        records = []
        for i in range(count):
            conf = self.conf_loader.get_next()
            reminder_count = random.randint(0, 3)
            records.append({
                'id': i + 1,
                'cart_id': self._get_random_id('shopping_carts'),
                'customer_id': self._get_random_id('customers') if random.random() > 0.3 else None,
                'email': conf.get('EMAIL') or self.fake.email(),
                'cart_value': round(random.uniform(25, 500), 2),
                'item_count': random.randint(1, 10),
                'abandoned_at': self._random_datetime(30),
                'reminder_sent_at': self._random_datetime(25) if reminder_count > 0 else None,
                'reminder_count': reminder_count,
                'recovered_at': self._random_datetime(20) if random.random() > 0.8 else None,
                'recovery_order_id': self._get_random_id('orders') if random.random() > 0.9 else None,
                'created_at': self._random_datetime(30),
            })
        return records

    def generate_customer_lifetime_value(self, count: int = 500) -> List[Dict[str, Any]]:
        """Generate customer lifetime value records.

        Unique constraint: customer_id
        """
        records = []
        used_customers = set()  # Track unique customer_ids
        attempts = 0
        max_attempts = count * 10

        while len(records) < count and attempts < max_attempts:
            attempts += 1
            customer_id = self._get_random_id('customers')

            # Check unique constraint
            if customer_id in used_customers:
                continue
            used_customers.add(customer_id)

            first_order = self._random_date(730, 365)
            last_order = self._random_date(30, 0)
            records.append({
                'id': len(records) + 1,
                'customer_id': customer_id,
                'total_revenue': round(random.uniform(100, 10000), 2),
                'total_orders': random.randint(1, 50),
                'avg_order_value': round(random.uniform(50, 300), 2),
                'predicted_ltv': round(random.uniform(500, 20000), 2),
                'clv_segment': random.choice(['LOW', 'MEDIUM', 'HIGH', 'VIP']),
                'purchase_frequency': round(random.uniform(0.1, 5.0), 2),
                'first_order_date': first_order,
                'last_order_date': last_order,
                'created_at': self._random_datetime(365),
            })
        return records

    # =========================================================================
    # Banking Domain Generators
    # =========================================================================

    def generate_account_types(self) -> List[Dict[str, Any]]:
        """Generate bank account type reference records."""
        types = [
            ('CHK', 'CHECKING', 'Checking Account', 'PERSONAL', 0, 0, 0.01),
            ('SAV', 'SAVINGS', 'Savings Account', 'PERSONAL', 100, 0, 0.5),
            ('MMA', 'MONEY_MARKET', 'Money Market Account', 'PERSONAL', 1000, 5, 1.5),
            ('CD', 'CD', 'Certificate of Deposit', 'INVESTMENT', 500, 0, 3.0),
            ('IRA', 'IRA', 'Individual Retirement Account', 'RETIREMENT', 0, 0, 2.5),
            ('BUS', 'BUSINESS', 'Business Account', 'BUSINESS', 500, 15, 0.1),
        ]
        records = []
        for i, (code, name, desc, cat, min_bal, fee, rate) in enumerate(types):
            records.append({
                'type_id': i + 1,
                'type_code': code,
                'type_name': name,
                'description': desc,
                'category': cat,
                'min_balance': min_bal,
                'monthly_fee': fee,
                'interest_rate': rate,
                'is_active': True,
                'created_at': self._random_datetime(365),
                'updated_at': self._random_datetime(30),
            })
        self._cache_ids('account_types', [r['type_id'] for r in records])
        return records

    def generate_transaction_types(self) -> List[Dict[str, Any]]:
        """Generate bank transaction type reference records."""
        types = [
            ('DEP', 'Deposit', 'CREDIT', 'Cash or check deposit'),
            ('WD', 'Withdrawal', 'DEBIT', 'Cash withdrawal'),
            ('TRF', 'Transfer', 'TRANSFER', 'Account transfer'),
            ('PMT', 'Payment', 'DEBIT', 'Bill payment'),
            ('FEE', 'Fee', 'DEBIT', 'Service fee'),
            ('INT', 'Interest', 'CREDIT', 'Interest earned'),
            ('CHK', 'Check', 'DEBIT', 'Check payment'),
            ('ACH', 'ACH Transfer', 'TRANSFER', 'ACH electronic transfer'),
            ('WIR', 'Wire Transfer', 'TRANSFER', 'Wire transfer'),
            ('REF', 'Refund', 'CREDIT', 'Transaction refund'),
        ]
        records = []
        for i, (code, name, category, desc) in enumerate(types):
            records.append({
                'type_id': i + 1,
                'type_code': code,
                'type_name': name,
                'category': category,
                'description': desc,
                'created_at': self._random_datetime(365),
                'updated_at': self._random_datetime(30),
            })
        self._cache_ids('transaction_types', [r['type_id'] for r in records])
        return records

    def _to_string_id(self, value: Any) -> str:
        """Convert a numeric value to string, removing any decimal suffix."""
        if value is None:
            return None
        # Handle float values from pandas (e.g., 123456789.0 -> "123456789")
        if isinstance(value, float):
            return str(int(value))
        return str(value)

    def generate_accounts(self, count: int) -> List[Dict[str, Any]]:
        """Generate bank account records.

        SINGLE-PASS: Also collects account_id and sensitive_account_ids params.
        """
        records = []
        used_account_numbers = set()
        for i in range(count):
            conf = self.conf_loader.get_next()
            balance = round(random.uniform(100, 100000), 2)
            # Convert numeric values from ConfidentialData to proper strings
            acct_num = self._to_string_id(conf.get('BANKACCT'))
            # Ensure unique account number
            if not acct_num or acct_num in used_account_numbers:
                acct_num = f"ACCT{i + 1:010d}"
            used_account_numbers.add(acct_num)
            routing = self._to_string_id(conf.get('ROUTING')) or self.fake.routing_number()
            record = {
                'account_id': i + 1,
                'account_number': acct_num,
                'routing_number': routing,
                'account_type_id': random.randint(1, 6),
                'account_name': f"Account {i + 1}",
                'status': random.choice(['ACTIVE', 'ACTIVE', 'ACTIVE', 'DORMANT']),
                'opened_date': self._random_date(365 * 5),
                'current_balance': balance,
                'available_balance': round(balance * 0.95, 2),
                'currency_code': 'USD',
                'interest_rate': round(random.uniform(0.01, 2.5), 4),
                'overdraft_protection': random.random() > 0.5,
                'is_active': random.random() > 0.05,
                'created_at': self._random_datetime(365 * 5),
            }
            records.append(record)

            # SINGLE-PASS: Collect actual values for params
            self.params.add('account_ids', {'account_id': record['account_id']})
            self.params.add('sensitive_account_ids', {'account_id': record['account_id']})

        self._cache_ids('accounts', [r['account_id'] for r in records])
        return records

    def generate_credit_cards(self, count: int) -> List[Dict[str, Any]]:
        """Generate credit card records using ConfidentialData."""
        records = []
        for i in range(count):
            conf = self.conf_loader.get_next()
            card_type = conf.get('CC') or self.fake.card_type()
            limit = round(random.uniform(1000, 50000), 2)
            balance = round(random.uniform(0, limit * 0.8), 2)
            # Convert numeric values from ConfidentialData to proper strings
            cc_num = self._to_string_id(conf.get('CCNO')) or self.fake.credit_card_number(card_type)
            cvv = self._to_string_id(conf.get('CCCSV')) or str(random.randint(100, 999))
            # Parse expiry safely
            expiry_str = str(conf.get('CCEXPIRE', '01/25'))
            try:
                expiry_month = int(expiry_str.split('/')[0])
            except (ValueError, IndexError):
                expiry_month = random.randint(1, 12)
            records.append({
                'card_id': i + 1,
                'account_id': self._get_random_id('accounts'),
                'card_number': cc_num,
                'card_type': card_type,
                'cardholder_name': conf.get('FULLNAME') or self.fake.name(),
                'expiry_month': expiry_month,
                'expiry_year': 2025 + random.randint(0, 5),
                'cvv': cvv,
                'credit_limit': limit,
                'available_credit': round(limit - balance, 2),
                'current_balance': balance,
                'apr': round(random.uniform(12, 25), 2),
                'status': random.choice(['ACTIVE', 'ACTIVE', 'ACTIVE', 'BLOCKED']),
                'is_active': True,
                'created_at': self._random_datetime(365 * 3),
            })
        self._cache_ids('credit_cards', [r['card_id'] for r in records])
        return records

    def generate_bank_transactions(self, count: int) -> List[Dict[str, Any]]:
        """Generate bank transaction records.

        SINGLE-PASS: Also collects transaction_params with actual account_ids and dates.
        """
        records = []
        for i in range(count):
            amount = round(random.uniform(-5000, 5000), 2)
            account_id = self._get_random_id('accounts')
            transaction_date = self._random_datetime(180)

            record = {
                'transaction_id': i + 1,
                'account_id': account_id,
                'transaction_type_id': random.randint(1, 10),
                'reference_number': f"TXN{random.randint(100000000, 999999999)}",
                'transaction_date': transaction_date,
                'posting_date': self._random_datetime(180),
                'amount': amount,
                'description': self.fake.transaction_type(),
                'channel': random.choice(['BRANCH', 'ATM', 'ONLINE', 'MOBILE', 'ACH']),
                'status': random.choice(['POSTED', 'POSTED', 'POSTED', 'PENDING']),
                'counterparty_name': self.fake.company() if random.random() > 0.5 else None,
                'created_at': self._random_datetime(180),
            }
            records.append(record)

            # SINGLE-PASS: Collect actual values for params
            end_date = transaction_date
            start_date = transaction_date - timedelta(days=random.randint(1, 30))
            self.params.add('transaction_params', {
                'start_date': start_date.strftime('%Y-%m-%d %H:%M:%S'),
                'end_date': end_date.strftime('%Y-%m-%d %H:%M:%S'),
                'account_id': account_id,
            })

        self._cache_ids('bank_transactions', [r['transaction_id'] for r in records])
        return records

    def generate_loan_types(self) -> List[Dict[str, Any]]:
        """Generate loan type reference records."""
        types = [
            ('MORT', 'Mortgage', 'SECURED', 50000, 1000000, 60, 360, 0.0350, True),
            ('AUTO', 'Auto Loan', 'SECURED', 5000, 100000, 12, 84, 0.0450, True),
            ('PERS', 'Personal Loan', 'UNSECURED', 1000, 50000, 6, 60, 0.0850, False),
            ('HOME', 'Home Equity', 'SECURED', 10000, 500000, 60, 240, 0.0400, True),
            ('STU', 'Student Loan', 'UNSECURED', 5000, 200000, 60, 240, 0.0550, False),
            ('BUS', 'Business Loan', 'SECURED', 10000, 1000000, 12, 120, 0.0650, True),
            ('CC', 'Credit Card', 'UNSECURED', 500, 50000, 0, 0, 0.1800, False),
            ('LOC', 'Line of Credit', 'UNSECURED', 5000, 100000, 0, 0, 0.0750, False),
        ]
        records = []
        used_codes = set()
        for i, (code, name, cat, min_amt, max_amt, min_term, max_term, rate, collateral) in enumerate(types):
            if code in used_codes:
                continue
            used_codes.add(code)
            records.append({
                'type_id': i + 1,
                'type_code': code,
                'type_name': name,
                'category': cat,
                'min_amount': min_amt,
                'max_amount': max_amt,
                'min_term_months': min_term,
                'max_term_months': max_term,
                'base_rate': rate,
                'requires_collateral': collateral,
                'created_at': self._random_datetime(365),
                'updated_at': self._random_datetime(30),
            })
        self._cache_ids('loan_types', [r['type_id'] for r in records])
        return records

    def generate_loan_officers(self, count: int = 50) -> List[Dict[str, Any]]:
        """Generate loan officer records."""
        records = []
        used_employee_ids = set()
        for i in range(count):
            emp_id = f"LO{i + 1:05d}"
            if emp_id in used_employee_ids:
                continue
            used_employee_ids.add(emp_id)
            records.append({
                'officer_id': i + 1,
                'employee_id': emp_id,
                'first_name': self.fake.first_name(),
                'last_name': self.fake.last_name(),
                'email': self.fake.email(),
                'phone': self.fake.phone_number()[:20],
                'nmls_id': f"NMLS{random.randint(100000, 999999)}",
                'branch': random.choice(['Main', 'Downtown', 'North', 'South', 'East', 'West']),
                'specialization': random.choice(['Mortgage', 'Auto', 'Personal', 'Business', 'Commercial']),
                'hire_date': self._random_datetime(365 * 10),
                'status': 'ACTIVE',
                'is_active': True,
                'created_at': self._random_datetime(365 * 5),
            })
        self._cache_ids('loan_officers', [r['officer_id'] for r in records])
        return records

    def generate_billing_codes(self, count: int = 100) -> List[Dict[str, Any]]:
        """Generate billing code records."""
        records = []
        used_pairs = set()
        code_types = ['CPT', 'HCPCS', 'ICD10', 'DRG', 'REVENUE']
        for i in range(count):
            code_type = random.choice(code_types)
            code = f"{code_type[:2]}{i + 1:05d}"
            pair = (code, code_type)
            if pair in used_pairs:
                continue
            used_pairs.add(pair)
            records.append({
                'code_id': len(records) + 1,
                'code_type': code_type,
                'code': code,
                'description': f"Billing code {code} - {self.fake.text(max_nb_chars=50)}",
                'short_description': f"Code {code}",
                'effective_date': self._random_datetime(365 * 2),
                'termination_date': None,
                'is_active': True,
                'created_at': self._random_datetime(365),
            })
        self._cache_ids('billing_codes', [r['code_id'] for r in records])
        return records

    def generate_bank_users(self, count: int = 500) -> List[Dict[str, Any]]:
        """Generate bank user records."""
        records = []
        used_usernames = set()
        for i in range(count):
            username = f"bankuser{i + 1:05d}"
            if username in used_usernames:
                continue
            used_usernames.add(username)
            records.append({
                'user_id': i + 1,
                'customer_id': self._get_random_id('customers'),
                'username': username,
                'password_hash': self.fake.sha256(),
                'email': self.fake.email(),
                'phone': self.fake.phone_number()[:20],
                'mfa_enabled': random.random() > 0.3,
                'mfa_method': random.choice(['SMS', 'EMAIL', 'APP', None]),
                'last_login': self._random_datetime(30) if random.random() > 0.2 else None,
                'failed_login_count': random.randint(0, 3),
                'locked_until': None,
                'password_changed_at': self._random_datetime(90),
                'must_change_password': random.random() > 0.9,
                'status': 'ACTIVE',
                'is_active': True,
                'created_at': self._random_datetime(365 * 3),
            })
        self._cache_ids('bank_users', [r['user_id'] for r in records])
        return records

    def generate_bank_user_sessions(self, count: int = 1000) -> List[Dict[str, Any]]:
        """Generate bank user session records."""
        records = []
        used_tokens = set()
        for i in range(count):
            token = f"sess_{self.fake.uuid4()}"
            if token in used_tokens:
                continue
            used_tokens.add(token)
            started = self._random_datetime(7)
            records.append({
                'session_id': len(records) + 1,
                'user_id': self._get_random_id('bank_users'),
                'session_token': token,
                'ip_address': self.fake.ipv4(),
                'user_agent': self.fake.user_agent()[:500],
                'device_fingerprint': self.fake.sha256()[:255],
                'started_at': started,
                'expires_at': started + timedelta(hours=random.randint(1, 24)),
                'last_activity': self._random_datetime(1) if random.random() > 0.3 else None,
                'is_active': random.random() > 0.3,
            })
        return records

    def generate_bank_transaction_categories(self, count: int = 100) -> List[Dict[str, Any]]:
        """Generate bank transaction category records."""
        records = []
        categories = ['Groceries', 'Dining', 'Entertainment', 'Utilities', 'Transportation',
                      'Healthcare', 'Shopping', 'Travel', 'Education', 'Income', 'Transfers',
                      'Bills', 'Subscriptions', 'Investments', 'Fees', 'Other']
        for i, cat_name in enumerate(categories):
            records.append({
                'category_id': i + 1,
                'customer_id': self._get_random_id('customers'),
                'category_name': cat_name,
                'parent_category_id': None,
                'icon': cat_name.lower()[:50],
                'color': f"#{random.randint(0, 0xFFFFFF):06x}",
                'budget_amount': round(random.uniform(100, 2000), 2) if random.random() > 0.5 else None,
                'created_at': self._random_datetime(365),
            })
        # Add some subcategories
        for i in range(len(categories), count):
            parent_id = random.randint(1, len(categories))
            records.append({
                'category_id': i + 1,
                'customer_id': self._get_random_id('customers'),
                'category_name': f"Subcategory {i + 1}",
                'parent_category_id': parent_id,
                'icon': f"subcat{i}",
                'color': f"#{random.randint(0, 0xFFFFFF):06x}",
                'budget_amount': round(random.uniform(50, 500), 2) if random.random() > 0.5 else None,
                'created_at': self._random_datetime(365),
            })
        self._cache_ids('bank_transaction_categories', [r['category_id'] for r in records])
        return records

    def generate_bank_transaction_tags(self, count: int = 500) -> List[Dict[str, Any]]:
        """Generate bank transaction tag records."""
        records = []
        for i in range(count):
            records.append({
                'tag_id': i + 1,
                'transaction_id': self._get_random_id('bank_transactions'),
                'category_id': self._get_random_id('bank_transaction_categories') if random.random() > 0.3 else None,
                'tag_name': random.choice(['Important', 'Review', 'Business', 'Personal', 'Tax', 'Reimbursable', None]),
                'notes': self.fake.text(max_nb_chars=100) if random.random() > 0.7 else None,
                'created_at': self._random_datetime(180),
            })
        return records

    def generate_checking_accounts(self, count: int = 500) -> List[Dict[str, Any]]:
        """Generate checking account records."""
        records = []
        used_account_ids = set()
        account_ids = self._id_cache.get('accounts', [])
        for i in range(min(count, len(account_ids))):
            account_id = account_ids[i]
            if account_id in used_account_ids:
                continue
            used_account_ids.add(account_id)
            records.append({
                'checking_id': len(records) + 1,
                'account_id': account_id,
                'check_number_sequence': random.randint(100, 5000),
                'overdraft_linked_account': None,
                'free_checks_monthly': random.randint(0, 20),
                'debit_card_id': None,
                'created_at': self._random_datetime(365 * 3),
            })
        self._cache_ids('checking_accounts', [r['checking_id'] for r in records])
        return records

    def generate_savings_accounts(self, count: int = 500) -> List[Dict[str, Any]]:
        """Generate savings account records."""
        records = []
        used_account_ids = set()
        account_ids = self._id_cache.get('accounts', [])
        # Use a different set of account IDs than checking
        start_idx = min(count, len(account_ids) // 3)
        for i in range(start_idx, min(start_idx + count, len(account_ids))):
            account_id = account_ids[i]
            if account_id in used_account_ids:
                continue
            used_account_ids.add(account_id)
            records.append({
                'savings_id': len(records) + 1,
                'account_id': account_id,
                'interest_rate': round(random.uniform(0.01, 2.5), 4),
                'compound_frequency': random.choice(['DAILY', 'MONTHLY', 'QUARTERLY', 'ANNUALLY']),
                'withdrawal_limit': random.randint(3, 6),
                'withdrawals_this_period': random.randint(0, 3),
                'last_interest_date': self._random_datetime(30),
                'accrued_interest': round(random.uniform(0, 100), 2),
                'created_at': self._random_datetime(365 * 3),
            })
        self._cache_ids('savings_accounts', [r['savings_id'] for r in records])
        return records

    def generate_money_market_accounts(self, count: int = 200) -> List[Dict[str, Any]]:
        """Generate money market account records."""
        records = []
        used_account_ids = set()
        account_ids = self._id_cache.get('accounts', [])
        # Use a different set of account IDs
        start_idx = min(count * 2, len(account_ids) // 2)
        for i in range(start_idx, min(start_idx + count, len(account_ids))):
            account_id = account_ids[i]
            if account_id in used_account_ids:
                continue
            used_account_ids.add(account_id)
            records.append({
                'mm_id': len(records) + 1,
                'account_id': account_id,
                'tier_balance': round(random.uniform(1000, 100000), 2),
                'tiered_rate': round(random.uniform(0.5, 3.0), 4),
                'check_writing_enabled': random.random() > 0.5,
                'min_check_amount': round(random.uniform(100, 500), 2) if random.random() > 0.5 else None,
                'created_at': self._random_datetime(365 * 3),
            })
        self._cache_ids('money_market_accounts', [r['mm_id'] for r in records])
        return records

    def generate_joint_accounts(self, count: int = 200) -> List[Dict[str, Any]]:
        """Generate joint account records."""
        records = []
        used_account_ids = set()
        account_ids = self._id_cache.get('accounts', [])
        for i in range(min(count, len(account_ids))):
            account_id = account_ids[i]
            if account_id in used_account_ids:
                continue
            used_account_ids.add(account_id)
            if random.random() > 0.7:  # Only 30% of accounts are joint
                records.append({
                    'joint_id': len(records) + 1,
                    'account_id': account_id,
                    'survivorship_type': random.choice(['JTWROS', 'TIC', 'COMMUNITY']),
                    'signature_requirement': random.choice(['ANY', 'ALL', 'MAJORITY']),
                    'signature_threshold': random.randint(1, 3) if random.random() > 0.5 else None,
                    'created_at': self._random_datetime(365 * 3),
                })
        self._cache_ids('joint_accounts', [r['joint_id'] for r in records])
        return records

    def generate_account_holders(self, count: int = 500) -> List[Dict[str, Any]]:
        """Generate account holder records."""
        records = []
        used_pairs = set()
        for i in range(count):
            account_id = self._get_random_id('accounts')
            customer_id = self._get_random_id('customers')
            pair = (account_id, customer_id)
            if pair in used_pairs:
                continue
            used_pairs.add(pair)
            records.append({
                'holder_id': len(records) + 1,
                'account_id': account_id,
                'customer_id': customer_id,
                'holder_type': random.choice(['PRIMARY', 'SECONDARY', 'AUTHORIZED']),
                'relationship_type': random.choice(['SELF', 'SPOUSE', 'CHILD', 'PARENT', 'BUSINESS']),
                'ownership_percentage': round(random.uniform(10, 100), 2) if random.random() > 0.5 else None,
                'signing_authority': random.random() > 0.3,
                'added_date': self._random_datetime(365 * 3),
                'removed_date': None,
                'is_active': True,
                'created_at': self._random_datetime(365 * 3),
            })
        return records

    def generate_account_limits(self, count: int = 500) -> List[Dict[str, Any]]:
        """Generate account limit records."""
        records = []
        used_pairs = set()
        limit_types = ['DAILY_WITHDRAWAL', 'DAILY_TRANSFER', 'SINGLE_TRANSACTION', 'ACH_DAILY', 'WIRE_DAILY']
        for i in range(count):
            account_id = self._get_random_id('accounts')
            limit_type = random.choice(limit_types)
            pair = (account_id, limit_type)
            if pair in used_pairs:
                continue
            used_pairs.add(pair)
            records.append({
                'limit_id': len(records) + 1,
                'account_id': account_id,
                'limit_type': limit_type,
                'limit_amount': round(random.uniform(500, 25000), 2),
                'current_usage': round(random.uniform(0, 5000), 2),
                'reset_period': random.choice(['DAILY', 'WEEKLY', 'MONTHLY']),
                'last_reset_date': self._random_datetime(7),
                'created_at': self._random_datetime(365),
            })
        return records

    def generate_account_statements(self, count: int = 1000) -> List[Dict[str, Any]]:
        """Generate account statement records."""
        records = []
        used_pairs = set()
        for i in range(count):
            account_id = self._get_random_id('accounts')
            # Generate statement date for each month
            stmt_date = self._random_date(365, 0)
            pair = (account_id, str(stmt_date))
            if pair in used_pairs:
                continue
            used_pairs.add(pair)
            opening = round(random.uniform(1000, 50000), 2)
            deposits = round(random.uniform(0, 10000), 2)
            withdrawals = round(random.uniform(0, 8000), 2)
            interest = round(random.uniform(0, 100), 2)
            fees = round(random.uniform(0, 50), 2)
            closing = round(opening + deposits - withdrawals + interest - fees, 2)
            period_start = stmt_date - timedelta(days=30)
            records.append({
                'statement_id': len(records) + 1,
                'account_id': account_id,
                'statement_date': stmt_date,
                'period_start': period_start,
                'period_end': stmt_date,
                'opening_balance': opening,
                'closing_balance': closing,
                'total_deposits': deposits,
                'total_withdrawals': withdrawals,
                'interest_earned': interest,
                'fees_charged': fees,
                'document_url': f"https://statements.example.com/{account_id}/{stmt_date.isoformat()}.pdf" if random.random() > 0.5 else None,
                'created_at': self._random_datetime(365),
            })
        return records

    def generate_account_alerts(self, count: int = 500) -> List[Dict[str, Any]]:
        """Generate account alert records."""
        records = []
        alert_types = ['LOW_BALANCE', 'LARGE_TRANSACTION', 'OVERDRAFT', 'DIRECT_DEPOSIT', 'PAYMENT_DUE']
        for i in range(count):
            records.append({
                'alert_id': i + 1,
                'account_id': self._get_random_id('accounts'),
                'alert_type': random.choice(alert_types),
                'threshold_amount': round(random.uniform(100, 5000), 2) if random.random() > 0.3 else None,
                'delivery_method': random.choice(['EMAIL', 'SMS', 'PUSH', 'ALL']),
                'delivery_address': self.fake.email() if random.random() > 0.5 else self.fake.phone_number()[:20],
                'is_enabled': random.random() > 0.2,
                'is_active': True,
                'created_at': self._random_datetime(365),
            })
        return records

    def generate_account_beneficiaries(self, count: int = 500) -> List[Dict[str, Any]]:
        """Generate account beneficiary records."""
        records = []
        for i in range(count):
            records.append({
                'beneficiary_id': i + 1,
                'account_id': self._get_random_id('accounts'),
                'beneficiary_name': self.fake.name(),
                'beneficiary_type': random.choice(['PRIMARY', 'CONTINGENT']),
                'percentage': round(random.uniform(10, 100), 2),
                'relationship': random.choice(['SPOUSE', 'CHILD', 'PARENT', 'SIBLING', 'OTHER']),
                'date_of_birth': self._random_datetime(365 * 80) if random.random() > 0.5 else None,
                'ssn_last_four': str(random.randint(1000, 9999)) if random.random() > 0.5 else None,
                'address': self.fake.address() if random.random() > 0.5 else None,
                'created_at': self._random_datetime(365),
            })
        return records

    def generate_debit_cards(self, count: int = 500) -> List[Dict[str, Any]]:
        """Generate debit card records."""
        records = []
        for i in range(count):
            conf = self.conf_loader.get_next()
            records.append({
                'card_id': i + 1,
                'account_id': self._get_random_id('accounts'),
                'card_number': self._to_string_id(conf.get('CCNO')) or f"{random.randint(4000000000000000, 4999999999999999)}",
                'card_type': random.choice(['VISA', 'MASTERCARD']),
                'cardholder_name': conf.get('FULLNAME') or self.fake.name(),
                'expiry_month': random.randint(1, 12),
                'expiry_year': 2025 + random.randint(0, 5),
                'pin_hash': self.fake.sha256(),
                'daily_limit': round(random.uniform(500, 5000), 2),
                'atm_limit': round(random.uniform(300, 1000), 2),
                'pos_limit': round(random.uniform(500, 5000), 2),
                'status': random.choice(['ACTIVE', 'ACTIVE', 'ACTIVE', 'BLOCKED', 'EXPIRED']),
                'issued_date': self._random_datetime(365 * 3),
                'last_four': str(random.randint(1000, 9999)),
                'is_active': True,
                'created_at': self._random_datetime(365 * 3),
            })
        self._cache_ids('debit_cards', [r['card_id'] for r in records])
        return records

    def generate_virtual_cards(self, count: int = 200) -> List[Dict[str, Any]]:
        """Generate virtual card records."""
        records = []
        for i in range(count):
            valid_from = self._random_datetime(30)
            records.append({
                'virtual_card_id': i + 1,
                'physical_card_id': self._get_random_id('credit_cards'),
                'card_number': f"{random.randint(4000000000000000, 4999999999999999)}",
                'expiry_month': random.randint(1, 12),
                'expiry_year': 2025 + random.randint(0, 2),
                'cvv': str(random.randint(100, 999)),
                'spending_limit': round(random.uniform(50, 1000), 2),
                'merchant_lock': random.choice(['Amazon', 'Netflix', 'Spotify', None]),
                'valid_from': valid_from,
                'valid_until': valid_from + timedelta(days=random.randint(7, 365)),
                'status': random.choice(['ACTIVE', 'ACTIVE', 'EXPIRED', 'CANCELLED']),
                'usage_count': random.randint(0, 50),
                'is_active': True,
                'created_at': self._random_datetime(365),
            })
        self._cache_ids('virtual_cards', [r['virtual_card_id'] for r in records])
        return records

    def generate_card_transactions(self, count: int = 2000) -> List[Dict[str, Any]]:
        """Generate card transaction records."""
        records = []
        for i in range(count):
            txn_date = self._random_datetime(180)
            amount = round(random.uniform(1, 5000), 2)
            is_foreign = random.random() > 0.9
            records.append({
                'card_txn_id': i + 1,
                'card_id': self._get_random_id('credit_cards'),
                'card_type': random.choice(['CREDIT', 'DEBIT']),
                'transaction_date': txn_date,
                'posting_date': txn_date + timedelta(days=random.randint(0, 3)),
                'merchant_name': self.fake.company(),
                'merchant_category_code': str(random.randint(1000, 9999)),
                'amount': amount,
                'currency_code': 'USD',
                'transaction_type': random.choice(['PURCHASE', 'REFUND', 'CASH_ADVANCE', 'PAYMENT']),
                'authorization_code': f"AUTH{random.randint(100000, 999999)}",
                'status': random.choice(['POSTED', 'POSTED', 'POSTED', 'PENDING']),
                'foreign_amount': round(amount * random.uniform(0.8, 1.5), 2) if is_foreign else None,
                'foreign_currency': random.choice(['EUR', 'GBP', 'JPY']) if is_foreign else None,
                'exchange_rate': round(random.uniform(0.7, 1.5), 6) if is_foreign else None,
                'created_at': txn_date,
            })
        self._cache_ids('card_transactions', [r['card_txn_id'] for r in records])
        return records

    def generate_card_statements(self, count: int = 500) -> List[Dict[str, Any]]:
        """Generate card statement records."""
        records = []
        for i in range(count):
            stmt_date = self._random_date(365, 0)
            prev_balance = round(random.uniform(0, 5000), 2)
            payments = round(random.uniform(0, prev_balance), 2)
            purchases = round(random.uniform(0, 3000), 2)
            cash_advances = round(random.uniform(0, 500), 2) if random.random() > 0.8 else 0
            fees = round(random.uniform(0, 100), 2) if random.random() > 0.7 else 0
            interest = round(random.uniform(0, 200), 2) if prev_balance > 0 else 0
            new_balance = round(prev_balance - payments + purchases + cash_advances + fees + interest, 2)
            records.append({
                'statement_id': i + 1,
                'card_id': self._get_random_id('credit_cards'),
                'statement_date': stmt_date,
                'period_start': stmt_date - timedelta(days=30),
                'period_end': stmt_date,
                'previous_balance': prev_balance,
                'payments': payments,
                'purchases': purchases,
                'cash_advances': cash_advances,
                'fees': fees,
                'interest': interest,
                'new_balance': new_balance,
                'minimum_payment': round(max(25, new_balance * 0.02), 2),
                'payment_due_date': stmt_date + timedelta(days=25),
                'credit_limit': round(random.uniform(5000, 50000), 2),
                'available_credit': round(random.uniform(1000, 40000), 2),
                'created_at': self._random_datetime(365),
            })
        return records

    def generate_card_rewards(self, count: int = 500) -> List[Dict[str, Any]]:
        """Generate card rewards records."""
        records = []
        for i in range(count):
            lifetime_earned = round(random.uniform(1000, 50000), 2)
            lifetime_redeemed = round(random.uniform(0, lifetime_earned * 0.7), 2)
            current_balance = round(lifetime_earned - lifetime_redeemed, 2)
            records.append({
                'reward_id': i + 1,
                'card_id': self._get_random_id('credit_cards'),
                'reward_type': random.choice(['POINTS', 'CASHBACK', 'MILES']),
                'current_balance': current_balance,
                'lifetime_earned': lifetime_earned,
                'lifetime_redeemed': lifetime_redeemed,
                'expiring_amount': round(random.uniform(0, 500), 2) if random.random() > 0.5 else None,
                'expiry_date': self._random_datetime(-90) if random.random() > 0.5 else None,
                'created_at': self._random_datetime(365),
            })
        self._cache_ids('card_rewards', [r['reward_id'] for r in records])
        return records

    def generate_card_reward_redemptions(self, count: int = 300) -> List[Dict[str, Any]]:
        """Generate card reward redemption records."""
        records = []
        for i in range(count):
            points = round(random.uniform(500, 10000), 2)
            records.append({
                'redemption_id': i + 1,
                'reward_id': self._get_random_id('card_rewards'),
                'redemption_type': random.choice(['STATEMENT_CREDIT', 'MERCHANDISE', 'TRAVEL', 'GIFT_CARD', 'TRANSFER']),
                'points_redeemed': points,
                'dollar_value': round(points / 100, 2),  # 1 cent per point
                'redemption_date': self._random_datetime(365),
                'status': random.choice(['COMPLETED', 'COMPLETED', 'PENDING', 'CANCELLED']),
                'details': self.fake.text(max_nb_chars=100) if random.random() > 0.5 else None,
                'created_at': self._random_datetime(365),
            })
        return records

    def generate_card_limits(self, count: int = 500) -> List[Dict[str, Any]]:
        """Generate card limit records."""
        records = []
        limit_types = ['DAILY_PURCHASE', 'SINGLE_TRANSACTION', 'ATM_DAILY', 'CASH_ADVANCE', 'ONLINE']
        for i in range(count):
            records.append({
                'limit_id': i + 1,
                'card_id': self._get_random_id('credit_cards'),
                'card_type': random.choice(['CREDIT', 'DEBIT']),
                'limit_type': random.choice(limit_types),
                'limit_amount': round(random.uniform(500, 10000), 2),
                'current_usage': round(random.uniform(0, 3000), 2),
                'period': random.choice(['DAILY', 'WEEKLY', 'MONTHLY']),
                'created_at': self._random_datetime(365),
            })
        return records

    def generate_card_controls(self, count: int = 500) -> List[Dict[str, Any]]:
        """Generate card control records."""
        records = []
        control_types = ['INTERNATIONAL', 'ONLINE', 'ATM', 'MERCHANT_CATEGORY', 'LOCATION']
        for i in range(count):
            records.append({
                'control_id': i + 1,
                'card_id': self._get_random_id('credit_cards'),
                'card_type': random.choice(['CREDIT', 'DEBIT']),
                'control_type': random.choice(control_types),
                'control_value': random.choice(['BLOCKED', 'ALLOWED', 'NOTIFY']),
                'is_enabled': random.random() > 0.3,
                'is_active': True,
                'created_at': self._random_datetime(365),
            })
        return records

    def generate_card_disputes(self, count: int = 200) -> List[Dict[str, Any]]:
        """Generate card dispute records."""
        records = []
        for i in range(count):
            filed_date = self._random_datetime(180)
            disputed_amount = round(random.uniform(10, 2000), 2)
            records.append({
                'dispute_id': i + 1,
                'card_txn_id': self._get_random_id('card_transactions'),
                'dispute_type': random.choice(['FRAUD', 'BILLING_ERROR', 'MERCHANDISE', 'AUTHORIZATION']),
                'reason_code': f"RC{random.randint(100, 999)}",
                'disputed_amount': disputed_amount,
                'provisional_credit': disputed_amount if random.random() > 0.5 else None,
                'status': random.choice(['OPEN', 'INVESTIGATING', 'RESOLVED', 'CLOSED']),
                'filed_date': filed_date,
                'deadline_date': filed_date + timedelta(days=45),
                'resolved_date': filed_date + timedelta(days=random.randint(5, 40)) if random.random() > 0.4 else None,
                'resolution': random.choice(['APPROVED', 'DENIED', 'PARTIAL', None]),
                'merchant_response': self.fake.text(max_nb_chars=200) if random.random() > 0.5 else None,
                'is_active': True,
                'created_at': filed_date,
            })
        return records

    def generate_loans(self, count: int = 500) -> List[Dict[str, Any]]:
        """Generate loan records."""
        records = []
        used_loan_numbers = set()
        for i in range(count):
            loan_num = f"LN{i + 1:08d}"
            if loan_num in used_loan_numbers:
                continue
            used_loan_numbers.add(loan_num)
            original_amount = round(random.uniform(5000, 500000), 2)
            term_months = random.choice([12, 24, 36, 48, 60, 120, 180, 240, 360])
            rate = round(random.uniform(0.03, 0.15), 4)
            monthly_payment = round((original_amount * (rate / 12)) / (1 - (1 + rate / 12) ** -term_months), 2)
            origination_date = self._random_date(365 * 5, 30)
            first_payment = origination_date + timedelta(days=30)
            maturity = origination_date + timedelta(days=term_months * 30)
            records.append({
                'loan_id': len(records) + 1,
                'loan_number': loan_num,
                'account_id': self._get_random_id('accounts'),
                'loan_type_id': self._get_random_id('loan_types'),
                'borrower_id': self._get_random_id('customers'),
                'original_amount': original_amount,
                'current_balance': round(original_amount * random.uniform(0.1, 0.95), 2),
                'interest_rate': rate,
                'rate_type': random.choice(['FIXED', 'VARIABLE']),
                'term_months': term_months,
                'monthly_payment': monthly_payment,
                'origination_date': origination_date,
                'first_payment_date': first_payment,
                'maturity_date': maturity,
                'next_payment_date': self._random_date(30, 0),
                'last_payment_date': self._random_date(60, 30) if random.random() > 0.2 else None,
                'status': random.choice(['CURRENT', 'CURRENT', 'CURRENT', 'DELINQUENT', 'PAID_OFF']),
                'days_past_due': random.randint(0, 90) if random.random() > 0.8 else 0,
                'origination_fee': round(original_amount * 0.01, 2),
                'is_active': True,
                'created_at': self._random_datetime(365 * 5),
            })
        self._cache_ids('loans', [r['loan_id'] for r in records])
        return records

    def generate_loan_applications(self, count: int = 500) -> List[Dict[str, Any]]:
        """Generate loan application records."""
        records = []
        used_app_numbers = set()
        for i in range(count):
            app_num = f"APP{i + 1:08d}"
            if app_num in used_app_numbers:
                continue
            used_app_numbers.add(app_num)
            submitted_date = self._random_datetime(365)
            requested_amount = round(random.uniform(5000, 500000), 2)
            status = random.choice(['SUBMITTED', 'UNDER_REVIEW', 'APPROVED', 'DENIED', 'WITHDRAWN'])
            records.append({
                'application_id': len(records) + 1,
                'application_number': app_num,
                'loan_type_id': self._get_random_id('loan_types'),
                'applicant_id': self._get_random_id('customers'),
                'co_applicant_id': self._get_random_id('customers') if random.random() > 0.7 else None,
                'requested_amount': requested_amount,
                'requested_term': random.choice([12, 24, 36, 48, 60, 120, 180, 240, 360]),
                'purpose': random.choice(['HOME_PURCHASE', 'REFINANCE', 'DEBT_CONSOLIDATION', 'HOME_IMPROVEMENT', 'VEHICLE', 'BUSINESS']),
                'employment_status': random.choice(['EMPLOYED', 'SELF_EMPLOYED', 'RETIRED', 'UNEMPLOYED']),
                'annual_income': round(random.uniform(30000, 500000), 2),
                'monthly_expenses': round(random.uniform(2000, 15000), 2),
                'credit_score': random.randint(500, 850),
                'debt_to_income': round(random.uniform(0.1, 0.5), 2),
                'status': status,
                'submitted_date': submitted_date,
                'decision_date': submitted_date + timedelta(days=random.randint(1, 14)) if status in ['APPROVED', 'DENIED'] else None,
                'approved_amount': round(requested_amount * 0.9, 2) if status == 'APPROVED' else None,
                'approved_rate': round(random.uniform(0.03, 0.12), 4) if status == 'APPROVED' else None,
                'decline_reason': 'Insufficient credit history' if status == 'DENIED' else None,
                'loan_officer_id': self._get_random_id('loan_officers'),
                'is_active': True,
                'created_at': submitted_date,
            })
        self._cache_ids('loan_applications', [r['application_id'] for r in records])
        return records

    def generate_loan_payments(self, count: int = 2000) -> List[Dict[str, Any]]:
        """Generate loan payment records."""
        records = []
        for i in range(count):
            payment_date = self._random_datetime(365)
            due_date = payment_date - timedelta(days=random.randint(-5, 15))
            scheduled = round(random.uniform(100, 5000), 2)
            actual = scheduled if random.random() > 0.1 else round(scheduled * random.uniform(0.5, 1.5), 2)
            records.append({
                'payment_id': i + 1,
                'loan_id': self._get_random_id('loans'),
                'payment_date': payment_date,
                'due_date': due_date,
                'scheduled_amount': scheduled,
                'actual_amount': actual,
                'principal_amount': round(actual * 0.7, 2),
                'interest_amount': round(actual * 0.25, 2),
                'escrow_amount': round(actual * 0.05, 2) if random.random() > 0.5 else None,
                'fees_amount': round(random.uniform(0, 50), 2) if random.random() > 0.8 else None,
                'payment_method': random.choice(['ACH', 'CHECK', 'ONLINE', 'WIRE']),
                'confirmation_number': f"PMT{random.randint(100000000, 999999999)}",
                'status': random.choice(['COMPLETED', 'COMPLETED', 'COMPLETED', 'PENDING', 'RETURNED']),
                'balance_after': round(random.uniform(1000, 400000), 2),
                'created_at': payment_date,
            })
        return records

    def generate_loan_schedules(self, count: int = 2000) -> List[Dict[str, Any]]:
        """Generate loan schedule records (amortization)."""
        records = []
        used_pairs = set()
        loan_ids = self._id_cache.get('loans', [])
        for loan_id in loan_ids[:min(50, len(loan_ids))]:  # Generate schedules for 50 loans
            num_payments = random.randint(12, 60)
            balance = round(random.uniform(10000, 300000), 2)
            monthly_payment = round(balance / num_payments * 1.1, 2)
            for payment_num in range(1, num_payments + 1):
                pair = (loan_id, payment_num)
                if pair in used_pairs or len(records) >= count:
                    continue
                used_pairs.add(pair)
                principal = round(monthly_payment * 0.7, 2)
                interest = round(monthly_payment * 0.25, 2)
                balance = max(0, round(balance - principal, 2))
                records.append({
                    'schedule_id': len(records) + 1,
                    'loan_id': loan_id,
                    'payment_number': payment_num,
                    'due_date': self._random_date(365, 0) + timedelta(days=30 * payment_num),
                    'payment_amount': monthly_payment,
                    'principal_amount': principal,
                    'interest_amount': interest,
                    'escrow_amount': round(monthly_payment * 0.05, 2) if random.random() > 0.5 else None,
                    'balance_after': balance,
                    'is_paid': payment_num < random.randint(1, num_payments),
                    'paid_date': self._random_datetime(365) if random.random() > 0.3 else None,
                    'created_at': self._random_datetime(365),
                })
        return records

    def generate_loan_status_history(self, count: int = 500) -> List[Dict[str, Any]]:
        """Generate loan status history records."""
        records = []
        statuses = ['SUBMITTED', 'UNDER_REVIEW', 'APPROVED', 'FUNDED', 'CURRENT', 'DELINQUENT', 'PAID_OFF']
        for i in range(count):
            prev_idx = random.randint(0, len(statuses) - 2)
            records.append({
                'history_id': i + 1,
                'loan_id': self._get_random_id('loans'),
                'previous_status': statuses[prev_idx],
                'new_status': statuses[prev_idx + 1],
                'changed_date': self._random_datetime(365),
                'changed_by': self._get_random_id('users') if random.random() > 0.5 else None,
                'notes': self.fake.text(max_nb_chars=100) if random.random() > 0.5 else None,
            })
        return records

    def generate_loan_fees(self, count: int = 300) -> List[Dict[str, Any]]:
        """Generate loan fee records."""
        records = []
        fee_types = ['ORIGINATION', 'LATE_PAYMENT', 'NSF', 'PREPAYMENT', 'PROCESSING', 'APPRAISAL']
        for i in range(count):
            assessed_date = self._random_datetime(365)
            records.append({
                'fee_id': i + 1,
                'loan_id': self._get_random_id('loans'),
                'fee_type': random.choice(fee_types),
                'fee_amount': round(random.uniform(25, 500), 2),
                'assessed_date': assessed_date,
                'due_date': assessed_date + timedelta(days=30),
                'paid_date': assessed_date + timedelta(days=random.randint(1, 30)) if random.random() > 0.3 else None,
                'waived': random.random() > 0.9,
                'waived_reason': 'Customer courtesy' if random.random() > 0.9 else None,
                'created_at': assessed_date,
            })
        return records

    def generate_loan_documents(self, count: int = 500) -> List[Dict[str, Any]]:
        """Generate loan document records."""
        records = []
        doc_types = ['APPLICATION', 'INCOME_VERIFICATION', 'CREDIT_REPORT', 'APPRAISAL', 'TITLE', 'INSURANCE', 'CLOSING']
        for i in range(count):
            records.append({
                'document_id': i + 1,
                'loan_id': self._get_random_id('loans') if random.random() > 0.3 else None,
                'application_id': self._get_random_id('loan_applications') if random.random() > 0.5 else None,
                'document_type': random.choice(doc_types),
                'document_name': f"{random.choice(doc_types).lower()}_document_{i + 1}.pdf",
                'file_path': f"/documents/loans/{random.randint(1000, 9999)}/{i + 1}.pdf",
                'file_size': random.randint(10000, 10000000),
                'uploaded_date': self._random_datetime(365),
                'uploaded_by': self._get_random_id('users') if random.random() > 0.5 else None,
                'verified': random.random() > 0.3,
                'verified_by': self._get_random_id('users') if random.random() > 0.5 else None,
                'verified_date': self._random_datetime(365) if random.random() > 0.5 else None,
                'created_at': self._random_datetime(365),
            })
        return records

    def generate_loan_refinancing(self, count: int = 100) -> List[Dict[str, Any]]:
        """Generate loan refinancing records."""
        records = []
        loan_ids = self._id_cache.get('loans', [])
        for i in range(min(count, len(loan_ids) // 2)):
            original_loan = loan_ids[i * 2]
            new_loan = loan_ids[i * 2 + 1] if i * 2 + 1 < len(loan_ids) else loan_ids[0]
            original_balance = round(random.uniform(50000, 300000), 2)
            records.append({
                'refinance_id': i + 1,
                'original_loan_id': original_loan,
                'new_loan_id': new_loan,
                'refinance_date': self._random_datetime(365),
                'original_balance': original_balance,
                'new_amount': round(original_balance * random.uniform(1.0, 1.2), 2),
                'original_rate': round(random.uniform(0.04, 0.08), 4),
                'new_rate': round(random.uniform(0.03, 0.06), 4),
                'cash_out_amount': round(random.uniform(0, 50000), 2) if random.random() > 0.5 else None,
                'closing_costs': round(random.uniform(2000, 10000), 2),
                'is_active': True,
                'created_at': self._random_datetime(365),
            })
        return records

    def generate_collateral(self, count: int = 300) -> List[Dict[str, Any]]:
        """Generate collateral records for loans."""
        records = []
        collateral_types = ['REAL_ESTATE', 'VEHICLE', 'EQUIPMENT', 'SECURITIES', 'SAVINGS']
        for i in range(count):
            records.append({
                'collateral_id': i + 1,
                'loan_id': self._get_random_id('loans'),
                'collateral_type': random.choice(collateral_types),
                'description': self.fake.text(max_nb_chars=100),
                'estimated_value': round(random.uniform(10000, 500000), 2),
                'valuation_date': self._random_datetime(365),
                'lien_position': random.randint(1, 3),
                'insurance_required': random.random() > 0.3,
                'insurance_verified': random.random() > 0.5,
                'property_address': self.fake.address() if random.random() > 0.5 else None,
                'vin': f"VIN{random.randint(10000000000000000, 99999999999999999)}"[:20] if random.random() > 0.7 else None,
                'title_number': f"TITLE{random.randint(100000, 999999)}" if random.random() > 0.5 else None,
                'is_active': True,
                'created_at': self._random_datetime(365),
            })
        return records

    def generate_guarantors(self, count: int = 200) -> List[Dict[str, Any]]:
        """Generate guarantor records for loans."""
        records = []
        for i in range(count):
            records.append({
                'guarantor_id': i + 1,
                'loan_id': self._get_random_id('loans'),
                'person_id': self._get_random_id('customers'),
                'relationship': random.choice(['SPOUSE', 'PARENT', 'CHILD', 'BUSINESS_PARTNER', 'OTHER']),
                'guarantee_type': random.choice(['FULL', 'LIMITED', 'UNLIMITED']),
                'guarantee_amount': round(random.uniform(10000, 200000), 2) if random.random() > 0.5 else None,
                'guarantee_percentage': round(random.uniform(10, 100), 2) if random.random() > 0.5 else None,
                'signed_date': self._random_datetime(365),
                'document_id': None,
                'is_active': True,
                'created_at': self._random_datetime(365),
            })
        return records

    def generate_transfers(self, count: int = 1000) -> List[Dict[str, Any]]:
        """Generate transfer records."""
        records = []
        used_ref_numbers = set()
        for i in range(count):
            ref_num = f"TRF{random.randint(100000000, 999999999)}"
            if ref_num in used_ref_numbers:
                continue
            used_ref_numbers.add(ref_num)
            scheduled_date = self._random_datetime(30)
            records.append({
                'transfer_id': len(records) + 1,
                'from_account_id': self._get_random_id('accounts'),
                'to_account_id': self._get_random_id('accounts') if random.random() > 0.3 else None,
                'external_account': f"{random.randint(1000000000, 9999999999)}" if random.random() > 0.5 else None,
                'external_routing': f"{random.randint(100000000, 999999999)}" if random.random() > 0.5 else None,
                'external_bank_name': self.fake.company() if random.random() > 0.5 else None,
                'amount': round(random.uniform(10, 50000), 2),
                'currency_code': 'USD',
                'transfer_type': random.choice(['INTERNAL', 'EXTERNAL', 'WIRE', 'ACH']),
                'scheduled_date': scheduled_date,
                'executed_date': scheduled_date + timedelta(hours=random.randint(0, 48)) if random.random() > 0.2 else None,
                'status': random.choice(['COMPLETED', 'COMPLETED', 'PENDING', 'FAILED', 'CANCELLED']),
                'reference_number': ref_num,
                'memo': self.fake.text(max_nb_chars=100) if random.random() > 0.5 else None,
                'initiated_by': self._get_random_id('bank_users') if random.random() > 0.5 else None,
                'is_active': True,
                'created_at': self._random_datetime(365),
            })
        self._cache_ids('transfers', [r['transfer_id'] for r in records])
        return records

    def generate_ach_transfers(self, count: int = 500) -> List[Dict[str, Any]]:
        """Generate ACH transfer records."""
        records = []
        sec_codes = ['PPD', 'CCD', 'WEB', 'TEL', 'CTX']
        for i in range(count):
            records.append({
                'ach_id': i + 1,
                'transfer_id': self._get_random_id('transfers'),
                'sec_code': random.choice(sec_codes),
                'company_name': self.fake.company() if random.random() > 0.5 else None,
                'company_id': f"CMP{random.randint(10000, 99999)}" if random.random() > 0.5 else None,
                'individual_name': self.fake.name() if random.random() > 0.5 else None,
                'individual_id': f"IND{random.randint(10000, 99999)}" if random.random() > 0.5 else None,
                'trace_number': f"TRC{random.randint(100000000000000, 999999999999999)}"[:20],
                'settlement_date': self._random_datetime(30) if random.random() > 0.3 else None,
                'return_code': random.choice(['R01', 'R02', 'R03', None, None, None]),
                'return_reason': 'Insufficient funds' if random.random() > 0.9 else None,
                'is_active': True,
                'created_at': self._random_datetime(365),
            })
        return records

    def generate_wire_transfers(self, count: int = 200) -> List[Dict[str, Any]]:
        """Generate wire transfer records."""
        records = []
        for i in range(count):
            records.append({
                'wire_id': i + 1,
                'transfer_id': self._get_random_id('transfers'),
                'wire_type': random.choice(['DOMESTIC', 'INTERNATIONAL']),
                'beneficiary_name': self.fake.name(),
                'beneficiary_address': self.fake.address(),
                'beneficiary_bank_name': self.fake.company() + ' Bank',
                'beneficiary_bank_address': self.fake.address(),
                'swift_code': f"SWIFT{random.randint(1000, 9999)}XX" if random.random() > 0.5 else None,
                'iban': f"GB{random.randint(10, 99)}ABCD{random.randint(10000000000000, 99999999999999)}"[:34] if random.random() > 0.5 else None,
                'intermediary_bank': self.fake.company() if random.random() > 0.3 else None,
                'intermediary_swift': f"INT{random.randint(1000, 9999)}XX" if random.random() > 0.3 else None,
                'purpose': random.choice(['PAYMENT', 'INVESTMENT', 'REAL_ESTATE', 'BUSINESS', 'PERSONAL']),
                'fee_amount': round(random.uniform(15, 50), 2),
                'exchange_rate': round(random.uniform(0.8, 1.5), 6) if random.random() > 0.5 else None,
                'is_active': True,
                'created_at': self._random_datetime(365),
            })
        return records

    def generate_scheduled_payments(self, count: int = 500) -> List[Dict[str, Any]]:
        """Generate scheduled payment records."""
        records = []
        for i in range(count):
            scheduled_date = self._random_datetime(-30)  # Future date
            records.append({
                'payment_id': i + 1,
                'account_id': self._get_random_id('accounts'),
                'payee_id': None,
                'payee_name': self.fake.company(),
                'amount': round(random.uniform(10, 5000), 2),
                'scheduled_date': scheduled_date,
                'payment_method': random.choice(['ACH', 'CHECK', 'WIRE']),
                'memo': self.fake.text(max_nb_chars=100) if random.random() > 0.5 else None,
                'status': random.choice(['SCHEDULED', 'SCHEDULED', 'PROCESSING', 'COMPLETED', 'CANCELLED']),
                'executed_date': scheduled_date + timedelta(days=1) if random.random() > 0.5 else None,
                'confirmation_number': f"CONF{random.randint(100000000, 999999999)}" if random.random() > 0.5 else None,
                'is_active': True,
                'created_at': self._random_datetime(365),
            })
        return records

    def generate_standing_orders(self, count: int = 300) -> List[Dict[str, Any]]:
        """Generate standing order records."""
        records = []
        for i in range(count):
            start_date = self._random_datetime(365)
            records.append({
                'order_id': i + 1,
                'from_account_id': self._get_random_id('accounts'),
                'to_account_id': self._get_random_id('accounts') if random.random() > 0.5 else None,
                'payee_id': None,
                'amount': round(random.uniform(50, 2000), 2),
                'frequency': random.choice(['WEEKLY', 'BIWEEKLY', 'MONTHLY', 'QUARTERLY', 'ANNUALLY']),
                'start_date': start_date,
                'end_date': start_date + timedelta(days=random.randint(90, 730)) if random.random() > 0.5 else None,
                'next_execution_date': self._random_datetime(-30),
                'last_execution_date': self._random_datetime(30) if random.random() > 0.3 else None,
                'execution_count': random.randint(0, 24),
                'status': random.choice(['ACTIVE', 'ACTIVE', 'PAUSED', 'CANCELLED', 'COMPLETED']),
                'description': self.fake.text(max_nb_chars=100) if random.random() > 0.5 else None,
                'is_active': True,
                'created_at': start_date,
            })
        return records

    def generate_compliance_cases(self, count: int = 200) -> List[Dict[str, Any]]:
        """Generate compliance case records."""
        records = []
        used_case_numbers = set()
        for i in range(count):
            case_num = f"COMP{i + 1:06d}"
            if case_num in used_case_numbers:
                continue
            used_case_numbers.add(case_num)
            opened_date = self._random_datetime(365)
            records.append({
                'case_id': len(records) + 1,
                'case_number': case_num,
                'case_type': random.choice(['AML', 'KYC', 'FRAUD', 'SAR', 'CTR', 'OFAC']),
                'priority': random.choice(['LOW', 'MEDIUM', 'HIGH', 'CRITICAL']),
                'customer_id': self._get_random_id('customers') if random.random() > 0.3 else None,
                'account_id': self._get_random_id('accounts') if random.random() > 0.3 else None,
                'description': self.fake.text(max_nb_chars=200),
                'opened_date': opened_date,
                'due_date': opened_date + timedelta(days=random.randint(7, 30)),
                'closed_date': opened_date + timedelta(days=random.randint(1, 60)) if random.random() > 0.5 else None,
                'assigned_to': self._get_random_id('users') if random.random() > 0.3 else None,
                'status': random.choice(['OPEN', 'INVESTIGATING', 'PENDING_REVIEW', 'CLOSED', 'ESCALATED']),
                'resolution': self.fake.text(max_nb_chars=100) if random.random() > 0.5 else None,
                'escalated': random.random() > 0.8,
                'is_active': True,
                'created_at': opened_date,
            })
        return records

    def generate_aml_checks(self, count: int = 500) -> List[Dict[str, Any]]:
        """Generate AML check records."""
        records = []
        for i in range(count):
            check_date = self._random_datetime(365)
            result = random.choice(['PASS', 'PASS', 'PASS', 'REVIEW', 'FAIL'])
            records.append({
                'check_id': i + 1,
                'customer_id': self._get_random_id('customers'),
                'check_type': random.choice(['ONBOARDING', 'PERIODIC', 'TRANSACTION', 'ENHANCED']),
                'check_date': check_date,
                'result': result,
                'risk_level': random.choice(['LOW', 'MEDIUM', 'HIGH']) if result != 'PASS' else 'LOW',
                'match_details': self.fake.text(max_nb_chars=200) if result != 'PASS' else None,
                'reviewed_by': self._get_random_id('users') if result != 'PASS' else None,
                'reviewed_date': check_date + timedelta(days=random.randint(1, 7)) if result != 'PASS' else None,
                'notes': self.fake.text(max_nb_chars=100) if random.random() > 0.5 else None,
                'created_at': check_date,
            })
        return records

    def generate_suspicious_activity_reports(self, count: int = 100) -> List[Dict[str, Any]]:
        """Generate suspicious activity report records."""
        records = []
        used_ref_numbers = set()
        for i in range(count):
            ref_num = f"SAR{i + 1:08d}"
            if ref_num in used_ref_numbers:
                continue
            used_ref_numbers.add(ref_num)
            filed_date = self._random_datetime(365)
            activity_start = filed_date - timedelta(days=random.randint(30, 180))
            records.append({
                'sar_id': len(records) + 1,
                'reference_number': ref_num,
                'customer_id': self._get_random_id('customers') if random.random() > 0.3 else None,
                'account_id': self._get_random_id('accounts') if random.random() > 0.3 else None,
                'activity_type': random.choice(['STRUCTURING', 'MONEY_LAUNDERING', 'FRAUD', 'TERRORIST_FINANCING', 'OTHER']),
                'activity_start_date': activity_start,
                'activity_end_date': activity_start + timedelta(days=random.randint(1, 90)),
                'amount_involved': round(random.uniform(5000, 500000), 2) if random.random() > 0.3 else None,
                'description': self.fake.text(max_nb_chars=500),
                'filed_date': filed_date,
                'filer_id': self._get_random_id('users') if random.random() > 0.3 else None,
                'submission_date': filed_date + timedelta(days=random.randint(1, 7)) if random.random() > 0.5 else None,
                'confirmation_number': f"FINCEN{random.randint(10000000, 99999999)}" if random.random() > 0.5 else None,
                'status': random.choice(['DRAFT', 'SUBMITTED', 'ACKNOWLEDGED', 'CLOSED']),
                'is_active': True,
                'created_at': filed_date,
            })
        return records

    def generate_kyc_documents(self, count: int = 500) -> List[Dict[str, Any]]:
        """Generate KYC document records."""
        records = []
        for i in range(count):
            issue_date = self._random_date(365 * 5, 30)
            records.append({
                'kyc_id': i + 1,
                'customer_id': self._get_random_id('customers'),
                'document_type': random.choice(['PASSPORT', 'DRIVERS_LICENSE', 'STATE_ID', 'SSN_CARD', 'UTILITY_BILL', 'BANK_STATEMENT']),
                'document_number': f"DOC{random.randint(100000000, 999999999)}",
                'issuing_country': random.choice(['USA', 'CAN', 'GBR', 'DEU']),
                'issuing_state': self.fake.state_abbr() if random.random() > 0.5 else None,
                'issue_date': issue_date,
                'expiry_date': issue_date + timedelta(days=random.randint(365, 365 * 10)),
                'verified': random.random() > 0.2,
                'verified_date': self._random_datetime(365) if random.random() > 0.3 else None,
                'verified_by': self._get_random_id('users') if random.random() > 0.3 else None,
                'verification_method': random.choice(['MANUAL', 'AUTOMATED', 'THIRD_PARTY']),
                'document_image_url': f"https://kyc.example.com/docs/{i + 1}.jpg" if random.random() > 0.5 else None,
                'risk_score': random.randint(1, 100) if random.random() > 0.5 else None,
                'is_active': True,
                'created_at': self._random_datetime(365),
            })
        return records

    def generate_sanctions_screening(self, count: int = 500) -> List[Dict[str, Any]]:
        """Generate sanctions screening records."""
        records = []
        for i in range(count):
            screening_date = self._random_datetime(365)
            result = random.choice(['CLEAR', 'CLEAR', 'CLEAR', 'POTENTIAL_MATCH', 'MATCH'])
            records.append({
                'screening_id': i + 1,
                'customer_id': self._get_random_id('customers') if random.random() > 0.3 else None,
                'transaction_id': self._get_random_id('bank_transactions') if random.random() > 0.5 else None,
                'screening_date': screening_date,
                'screening_type': random.choice(['CUSTOMER', 'TRANSACTION', 'BENEFICIARY', 'PERIODIC']),
                'result': result,
                'match_score': random.randint(50, 100) if result != 'CLEAR' else None,
                'matched_name': self.fake.name() if result != 'CLEAR' else None,
                'matched_list': random.choice(['OFAC_SDN', 'UN_SANCTIONS', 'EU_SANCTIONS']) if result != 'CLEAR' else None,
                'cleared': result == 'CLEAR' or random.random() > 0.5,
                'cleared_by': self._get_random_id('users') if result != 'CLEAR' else None,
                'cleared_date': screening_date + timedelta(days=random.randint(1, 7)) if result != 'CLEAR' else None,
                'created_at': screening_date,
            })
        return records

    def generate_bank_login_history(self, count: int = 2000) -> List[Dict[str, Any]]:
        """Generate bank login history records."""
        records = []
        for i in range(count):
            success = random.random() > 0.1
            records.append({
                'history_id': i + 1,
                'user_id': self._get_random_id('bank_users'),
                'login_time': self._random_datetime(90),
                'ip_address': self.fake.ipv4(),
                'user_agent': self.fake.user_agent()[:500],
                'device_type': random.choice(['DESKTOP', 'MOBILE', 'TABLET']),
                'location': f"{self.fake.city()}, {self.fake.state_abbr()}" if random.random() > 0.5 else None,
                'success': success,
                'failure_reason': random.choice(['INVALID_PASSWORD', 'ACCOUNT_LOCKED', 'MFA_FAILED', None]) if not success else None,
                'mfa_used': random.random() > 0.5,
            })
        return records

    def generate_security_questions(self, count: int = 500) -> List[Dict[str, Any]]:
        """Generate security question records."""
        records = []
        questions = [
            "What is your mother's maiden name?",
            "What was the name of your first pet?",
            "What city were you born in?",
            "What is your favorite movie?",
            "What was your childhood nickname?",
        ]
        for i in range(count):
            records.append({
                'question_id': i + 1,
                'user_id': self._get_random_id('bank_users'),
                'question': random.choice(questions),
                'answer_hash': self.fake.sha256(),
                'is_active': True,
                'created_at': self._random_datetime(365),
            })
        return records

    def generate_trusted_devices(self, count: int = 500) -> List[Dict[str, Any]]:
        """Generate trusted device records."""
        records = []
        for i in range(count):
            records.append({
                'device_id': i + 1,
                'user_id': self._get_random_id('bank_users'),
                'device_name': random.choice(['iPhone', 'Samsung Galaxy', 'MacBook', 'Windows PC', 'iPad']),
                'device_fingerprint': self.fake.sha256()[:255],
                'device_type': random.choice(['MOBILE', 'DESKTOP', 'TABLET']),
                'operating_system': random.choice(['iOS', 'Android', 'Windows', 'macOS', 'Linux']),
                'browser': random.choice(['Chrome', 'Safari', 'Firefox', 'Edge', None]),
                'last_used': self._random_datetime(30) if random.random() > 0.3 else None,
                'trusted_until': self._random_datetime(-365) if random.random() > 0.3 else None,
                'is_revoked': random.random() > 0.9,
                'is_active': True,
                'created_at': self._random_datetime(365),
            })
        return records

    def generate_transaction_disputes(self, count: int = 200) -> List[Dict[str, Any]]:
        """Generate transaction dispute records."""
        records = []
        for i in range(count):
            filed_date = self._random_datetime(180)
            disputed_amount = round(random.uniform(25, 5000), 2)
            records.append({
                'dispute_id': i + 1,
                'transaction_id': self._get_random_id('bank_transactions'),
                'dispute_type': random.choice(['UNAUTHORIZED', 'DUPLICATE', 'INCORRECT_AMOUNT', 'NEVER_RECEIVED']),
                'dispute_reason': self.fake.text(max_nb_chars=200),
                'disputed_amount': disputed_amount,
                'status': random.choice(['OPEN', 'INVESTIGATING', 'RESOLVED', 'DENIED']),
                'filed_date': filed_date,
                'resolved_date': filed_date + timedelta(days=random.randint(5, 45)) if random.random() > 0.4 else None,
                'resolution': random.choice(['APPROVED', 'DENIED', 'PARTIAL', None]),
                'credit_issued': disputed_amount if random.random() > 0.5 else None,
                'investigator_notes': self.fake.text(max_nb_chars=200) if random.random() > 0.5 else None,
                'is_active': True,
                'created_at': filed_date,
            })
        return records

    def generate_transaction_fees(self, count: int = 500) -> List[Dict[str, Any]]:
        """Generate transaction fee records."""
        records = []
        fee_types = ['ATM_SURCHARGE', 'FOREIGN_TRANSACTION', 'OVERDRAFT', 'NSF', 'WIRE', 'ACCOUNT_MAINTENANCE']
        for i in range(count):
            records.append({
                'fee_id': i + 1,
                'transaction_id': self._get_random_id('bank_transactions'),
                'fee_type': random.choice(fee_types),
                'fee_amount': round(random.uniform(1, 50), 2),
                'waived': random.random() > 0.9,
                'waived_reason': 'Customer courtesy' if random.random() > 0.95 else None,
                'created_at': self._random_datetime(365),
            })
        return records

    def generate_atm_transactions(self, count: int = 500) -> List[Dict[str, Any]]:
        """Generate ATM transaction records."""
        records = []
        for i in range(count):
            records.append({
                'atm_txn_id': i + 1,
                'transaction_id': self._get_random_id('bank_transactions'),
                'atm_id': f"ATM{random.randint(10000, 99999)}",
                'atm_location': f"{self.fake.street_address()}, {self.fake.city()}, {self.fake.state_abbr()}",
                'atm_owner': random.choice(['BANK_OWNED', 'NETWORK', 'THIRD_PARTY']),
                'transaction_type': random.choice(['WITHDRAWAL', 'DEPOSIT', 'BALANCE_INQUIRY', 'TRANSFER']),
                'surcharge_amount': round(random.uniform(0, 5), 2) if random.random() > 0.5 else None,
                'surcharge_rebated': random.random() > 0.7,
                'card_used': random.choice(['DEBIT', 'CREDIT']),
                'created_at': self._random_datetime(365),
            })
        return records

    def generate_pos_transactions(self, count: int = 500) -> List[Dict[str, Any]]:
        """Generate POS transaction records."""
        records = []
        for i in range(count):
            records.append({
                'pos_txn_id': i + 1,
                'transaction_id': self._get_random_id('bank_transactions'),
                'merchant_id': f"MID{random.randint(100000, 999999)}",
                'merchant_name': self.fake.company(),
                'merchant_category': random.choice(['RETAIL', 'GROCERY', 'RESTAURANT', 'GAS_STATION', 'ONLINE']),
                'merchant_city': self.fake.city(),
                'merchant_state': self.fake.state_abbr(),
                'merchant_country': 'USA',
                'terminal_id': f"TID{random.randint(10000, 99999)}",
                'entry_mode': random.choice(['CHIP', 'SWIPE', 'CONTACTLESS', 'MANUAL']),
                'authorization_code': f"AUTH{random.randint(100000, 999999)}",
                'cashback_amount': round(random.uniform(0, 100), 2) if random.random() > 0.8 else None,
                'created_at': self._random_datetime(365),
            })
        return records

    def generate_check_deposits(self, count: int = 500) -> List[Dict[str, Any]]:
        """Generate check deposit records."""
        records = []
        for i in range(count):
            check_amount = round(random.uniform(50, 10000), 2)
            records.append({
                'deposit_id': i + 1,
                'transaction_id': self._get_random_id('bank_transactions'),
                'check_number': str(random.randint(1000, 9999)) if random.random() > 0.3 else None,
                'check_amount': check_amount,
                'payer_name': self.fake.name() if random.random() > 0.3 else None,
                'payer_routing': str(random.randint(100000000, 999999999)) if random.random() > 0.5 else None,
                'payer_account': str(random.randint(10000000, 9999999999)) if random.random() > 0.5 else None,
                'deposit_method': random.choice(['BRANCH', 'ATM', 'MOBILE', 'MAIL']),
                'front_image_url': f"https://checks.example.com/{i}/front.jpg" if random.random() > 0.5 else None,
                'back_image_url': f"https://checks.example.com/{i}/back.jpg" if random.random() > 0.5 else None,
                'hold_amount': round(check_amount * 0.5, 2) if check_amount > 5000 else None,
                'hold_release_date': self._random_datetime(-7) if check_amount > 5000 else None,
                'verification_status': random.choice(['VERIFIED', 'PENDING', 'FAILED']),
                'created_at': self._random_datetime(365),
            })
        return records

    def generate_recurring_transactions(self, count: int = 300) -> List[Dict[str, Any]]:
        """Generate recurring transaction records."""
        records = []
        for i in range(count):
            records.append({
                'recurring_id': i + 1,
                'account_id': self._get_random_id('accounts'),
                'merchant_pattern': random.choice(['Netflix', 'Spotify', 'Amazon Prime', 'Gym Membership', 'Insurance', 'Utilities']),
                'average_amount': round(random.uniform(10, 500), 2),
                'frequency_days': random.choice([7, 14, 30, 90, 365]),
                'next_expected_date': self._random_datetime(-30),
                'last_transaction_id': self._get_random_id('bank_transactions') if random.random() > 0.3 else None,
                'is_confirmed': random.random() > 0.3,
                'created_at': self._random_datetime(365),
            })
        return records

    def generate_certificates_of_deposit(self, count: int = 200) -> List[Dict[str, Any]]:
        """Generate certificate of deposit records."""
        records = []
        for i in range(count):
            principal = round(random.uniform(1000, 250000), 2)
            term_months = random.choice([3, 6, 12, 24, 36, 60])
            start_date = self._random_date(365 * 3, 0)
            records.append({
                'cd_id': i + 1,
                'account_id': self._get_random_id('accounts'),
                'principal_amount': principal,
                'interest_rate': round(random.uniform(0.5, 5.0), 4),
                'term_months': term_months,
                'start_date': start_date,
                'maturity_date': start_date + timedelta(days=term_months * 30),
                'auto_renew': random.random() > 0.5,
                'renewal_term_months': term_months if random.random() > 0.5 else None,
                'early_withdrawal_penalty': round(random.uniform(0.5, 3.0), 4),
                'accrued_interest': round(principal * 0.02 * random.random(), 2),
                'status': random.choice(['ACTIVE', 'ACTIVE', 'MATURED', 'CLOSED']),
                'is_active': True,
                'created_at': self._random_datetime(365 * 3),
            })
        return records

    # =========================================================================
    # Healthcare Domain Generators
    # =========================================================================

    def generate_patients(self, count: int) -> List[Dict[str, Any]]:
        """Generate patient records using ConfidentialData.

        SINGLE-PASS: Also collects patient_id and sensitive_patient_ids params.
        """
        records = []
        for i in range(count):
            conf = self.conf_loader.get_next()
            record = {
                'patient_id': i + 1,
                'mrn': f"MRN-{i + 1:06d}",
                'ssn': conf.get('SSN'),
                'first_name': conf.get('FIRSTNAME') or self.fake.first_name(),
                'last_name': conf.get('LASTNAME') or self.fake.last_name(),
                'date_of_birth': conf.get('BIRTHDAY') if conf.get('BIRTHDAY') else self._random_date(365 * 80, 365),
                'gender': random.choice(['M', 'F']),
                'address_line1': conf.get('ADDR') or self.fake.street_address(),
                'city': conf.get('CITY') or self.fake.city(),
                'state': conf.get('ST') or self.fake.state_abbr(),
                'zip_code': str(conf.get('ZIP') or self.fake.zipcode()),
                'phone_home': conf.get('PHONE') or self.fake.phone_number()[:20],
                'email': conf.get('EMAIL') or self.fake.email(),
                'medicare_id': conf.get('MEDICARE-MBI'),
                'status': 'ACTIVE',
                'is_active': True,
                'created_at': self._random_datetime(365 * 5),
            }
            records.append(record)

            # SINGLE-PASS: Collect actual values for params
            self.params.add('patient_ids', {'patient_id': record['patient_id']})
            self.params.add('sensitive_patient_ids', {'patient_id': record['patient_id']})

        self._cache_ids('patients', [r['patient_id'] for r in records])
        return records

    def generate_providers(self, count: int = 200) -> List[Dict[str, Any]]:
        """Generate healthcare provider records."""
        records = []
        for i in range(count):
            records.append({
                'provider_id': i + 1,
                'npi': self.fake.npi(),
                'first_name': self.fake.first_name(),
                'last_name': self.fake.last_name(),
                'credentials': random.choice(['MD', 'DO', 'NP', 'PA', 'RN']),
                'specialty': self.fake.specialty(),
                'department': random.choice(['Primary Care', 'Specialty', 'Emergency', 'Surgery']),
                'email': self.fake.email(),
                'phone': self.fake.phone_number()[:20],
                'accepting_patients': random.random() > 0.1,
                'status': 'ACTIVE',
                'is_active': True,
                'created_at': self._random_datetime(365 * 10),
            })
        self._cache_ids('providers', [r['provider_id'] for r in records])
        return records

    def generate_medical_records(self, count: int) -> List[Dict[str, Any]]:
        """Generate medical record/encounter records."""
        records = []
        for i in range(count):
            admission = self._random_datetime(365)
            records.append({
                'record_id': i + 1,
                'patient_id': self._get_random_id('patients'),
                'encounter_number': f"ENC-{i + 1:06d}",
                'encounter_type': random.choice(['OFFICE', 'INPATIENT', 'EMERGENCY', 'TELEHEALTH']),
                'admission_date': admission,
                'discharge_date': admission + timedelta(hours=random.randint(1, 72)),
                'provider_id': self._get_random_id('providers'),
                'facility': f"Facility {random.randint(1, 10)}",
                'department': random.choice(['Primary Care', 'Cardiology', 'Orthopedics', 'Emergency']),
                'chief_complaint': self.fake.diagnosis(),
                'assessment': self.fake.diagnosis(),
                'plan': self.fake.treatment(),
                'status': random.choice(['COMPLETED', 'COMPLETED', 'SIGNED', 'IN_PROGRESS']),
                'is_active': True,
                'created_at': admission,
            })
        self._cache_ids('medical_records', [r['record_id'] for r in records])
        return records

    def generate_diagnoses(self, count: int) -> List[Dict[str, Any]]:
        """Generate diagnosis records."""
        records = []
        for i in range(count):
            records.append({
                'diagnosis_id': i + 1,
                'record_id': self._get_random_id('medical_records'),
                'patient_id': self._get_random_id('patients'),
                'diagnosis_code': self.fake.icd10_code(),
                'diagnosis_description': self.fake.diagnosis(),
                'diagnosis_type': random.choice(['PRIMARY', 'SECONDARY', 'ADMITTING']),
                'onset_date': self._random_date(365 * 5),
                'status': random.choice(['ACTIVE', 'RESOLVED']),
                'severity': random.choice(['MILD', 'MODERATE', 'SEVERE']),
                'diagnosed_by': self._get_random_id('providers'),
                'created_at': self._random_datetime(365),
            })
        return records

    def generate_rooms(self, count: int = 100) -> List[Dict[str, Any]]:
        """Generate room records for healthcare facilities."""
        room_types = ['EXAM', 'PROCEDURE', 'SURGERY', 'CONSULT', 'TREATMENT', 'OFFICE', 'LAB']
        records = []
        for i in range(count):
            room_type = random.choice(room_types)
            records.append({
                'room_id': i + 1,
                'room_number': f"{random.choice(['A', 'B', 'C', 'D'])}{random.randint(100, 399)}",
                'room_name': f"{room_type.title()} Room {i + 1}",
                'location': random.choice(['Main Building', 'East Wing', 'West Wing', 'Outpatient Center']),
                'room_type': room_type,
                'capacity': random.randint(1, 10) if room_type != 'EXAM' else 2,
                'equipment': random.choice(['Standard', 'Advanced Imaging', 'Surgical Suite', 'Basic']),
                'is_available': random.random() > 0.1,
                'created_at': self._random_datetime(365 * 2),
            })
        self._cache_ids('rooms', [r['room_id'] for r in records])
        return records

    def generate_appointment_types(self) -> List[Dict[str, Any]]:
        """Generate appointment type reference records with unique type_code."""
        types = [
            ('NEW', 'New Patient Visit', 60, 'Primary Care', False),
            ('FUP', 'Follow-Up Visit', 30, 'Primary Care', False),
            ('ANN', 'Annual Physical', 45, 'Primary Care', False),
            ('URG', 'Urgent Visit', 20, 'Urgent Care', False),
            ('WCC', 'Well Child Check', 30, 'Pediatrics', False),
            ('PRE', 'Pre-Op Evaluation', 45, 'Surgery', False),
            ('POST', 'Post-Op Follow-Up', 30, 'Surgery', False),
            ('CONS', 'Specialist Consultation', 60, 'Specialty', False),
            ('PROC', 'Procedure', 90, 'Specialty', False),
            ('TELE', 'Telehealth Visit', 30, 'Primary Care', True),
            ('MHC', 'Mental Health Consult', 60, 'Psychiatry', False),
            ('INJ', 'Injection Visit', 15, 'Primary Care', False),
            ('LAB', 'Lab Work Only', 15, 'Lab', False),
            ('IMG', 'Imaging Appointment', 45, 'Radiology', False),
            ('VIRT', 'Virtual Follow-Up', 20, 'Primary Care', True),
        ]
        records = []
        used_codes = set()
        for i, (code, name, duration, category, is_telehealth) in enumerate(types):
            if code in used_codes:
                continue
            used_codes.add(code)
            records.append({
                'type_id': i + 1,
                'type_code': code,
                'type_name': name,
                'description': f"{name} appointment type",
                'duration_minutes': duration,
                'category': category,
                'color': f"#{random.randint(0, 0xFFFFFF):06x}",
                'is_telehealth': is_telehealth,
                'created_at': self._random_datetime(365 * 2),
            })
        self._cache_ids('appointment_types', [r['type_id'] for r in records])
        return records

    def generate_patient_portal_users(self, count: int) -> List[Dict[str, Any]]:
        """Generate patient portal user records with unique patient_id and username."""
        records = []
        used_patient_ids = set()
        used_usernames = set()
        patient_ids = self._id_cache.get('patients', [])

        for i in range(min(count, len(patient_ids))):
            # Ensure unique patient_id
            patient_id = patient_ids[i] if i < len(patient_ids) else i + 1
            if patient_id in used_patient_ids:
                continue
            used_patient_ids.add(patient_id)

            # Ensure unique username
            base_username = f"patient_{patient_id}"
            username = base_username
            suffix = 1
            while username in used_usernames:
                username = f"{base_username}_{suffix}"
                suffix += 1
            used_usernames.add(username)

            records.append({
                'portal_user_id': len(records) + 1,
                'patient_id': patient_id,
                'username': username,
                'password_hash': self.fake.sha256(),
                'email_verified': random.random() > 0.2,
                'phone_verified': random.random() > 0.4,
                'mfa_enabled': random.random() > 0.7,
                'last_login': self._random_datetime(30) if random.random() > 0.3 else None,
                'status': random.choice(['ACTIVE', 'ACTIVE', 'ACTIVE', 'INACTIVE', 'LOCKED']),
                'is_active': random.random() > 0.1,
                'created_at': self._random_datetime(365 * 2),
            })
        self._cache_ids('patient_portal_users', [r['portal_user_id'] for r in records])
        return records

    def generate_patient_preferences(self, count: int) -> List[Dict[str, Any]]:
        """Generate patient preference records with unique (patient_id, preference_type)."""
        preference_types = [
            'COMMUNICATION_METHOD', 'APPOINTMENT_REMINDER', 'LANGUAGE', 'PHARMACY',
            'LAB_LOCATION', 'PORTAL_NOTIFICATIONS', 'STATEMENT_DELIVERY', 'CONTACT_TIME'
        ]
        records = []
        used_pairs = set()

        for i in range(count):
            patient_id = self._get_random_id('patients')
            pref_type = random.choice(preference_types)
            pair = (patient_id, pref_type)

            if pair in used_pairs:
                continue
            used_pairs.add(pair)

            pref_value = {
                'COMMUNICATION_METHOD': random.choice(['EMAIL', 'PHONE', 'TEXT', 'MAIL']),
                'APPOINTMENT_REMINDER': random.choice(['24H', '48H', '1WEEK']),
                'LANGUAGE': random.choice(['ENGLISH', 'SPANISH', 'FRENCH', 'MANDARIN']),
                'PHARMACY': self.fake.company(),
                'LAB_LOCATION': random.choice(['MAIN', 'EAST', 'WEST', 'NORTH']),
                'PORTAL_NOTIFICATIONS': random.choice(['ALL', 'URGENT', 'NONE']),
                'STATEMENT_DELIVERY': random.choice(['EMAIL', 'MAIL', 'BOTH']),
                'CONTACT_TIME': random.choice(['MORNING', 'AFTERNOON', 'EVENING', 'ANYTIME']),
            }.get(pref_type, 'DEFAULT')

            records.append({
                'preference_id': len(records) + 1,
                'patient_id': patient_id,
                'preference_type': pref_type,
                'preference_value': pref_value,
                'created_at': self._random_datetime(365),
            })
        return records

    def generate_patient_allergies(self, count: int) -> List[Dict[str, Any]]:
        """Generate patient allergy records."""
        allergen_types = ['MEDICATION', 'FOOD', 'ENVIRONMENTAL', 'OTHER']
        records = []
        for i in range(count):
            allergen_type = random.choice(allergen_types)
            records.append({
                'allergy_id': i + 1,
                'patient_id': self._get_random_id('patients'),
                'allergen_type': allergen_type,
                'allergen_name': self.fake.allergy(),
                'allergen_code': f"ALG{random.randint(1000, 9999)}" if random.random() > 0.5 else None,
                'reaction': random.choice(['Rash', 'Hives', 'Anaphylaxis', 'Swelling', 'Breathing difficulty', 'Nausea']),
                'severity': random.choice(['MILD', 'MODERATE', 'SEVERE']),
                'onset_date': self._random_date(365 * 10) if random.random() > 0.5 else None,
                'verified': random.random() > 0.3,
                'verified_by': self._get_random_id('providers') if random.random() > 0.4 else None,
                'status': random.choice(['ACTIVE', 'ACTIVE', 'INACTIVE', 'RESOLVED']),
                'is_active': True,
                'created_at': self._random_datetime(365 * 3),
            })
        return records

    def generate_patient_medications(self, count: int) -> List[Dict[str, Any]]:
        """Generate patient medication records."""
        drug_names = [
            'Metformin', 'Lisinopril', 'Atorvastatin', 'Metoprolol', 'Amlodipine',
            'Omeprazole', 'Losartan', 'Gabapentin', 'Hydrochlorothiazide', 'Sertraline',
            'Levothyroxine', 'Furosemide', 'Pantoprazole', 'Prednisone', 'Tramadol'
        ]
        routes = ['ORAL', 'TOPICAL', 'INJECTION', 'INHALATION', 'SUBLINGUAL']
        frequencies = ['DAILY', 'BID', 'TID', 'QID', 'PRN', 'WEEKLY', 'MONTHLY']
        records = []
        for i in range(count):
            drug = random.choice(drug_names)
            records.append({
                'medication_id': i + 1,
                'patient_id': self._get_random_id('patients'),
                'drug_name': drug,
                'drug_code': f"NDC{random.randint(10000000, 99999999)}",
                'dosage': f"{random.choice([5, 10, 20, 25, 50, 100, 250, 500])}mg",
                'frequency': random.choice(frequencies),
                'route': random.choice(routes),
                'prescriber_id': self._get_random_id('providers'),
                'start_date': self._random_date(365 * 2),
                'end_date': self._random_date(30, -365) if random.random() > 0.7 else None,
                'indication': self.fake.diagnosis(),
                'status': random.choice(['ACTIVE', 'ACTIVE', 'DISCONTINUED', 'COMPLETED']),
                'is_prn': random.random() > 0.8,
                'refills_remaining': random.randint(0, 5),
                'pharmacy': self.fake.company(),
                'is_active': True,
                'created_at': self._random_datetime(365 * 2),
            })
        return records

    def generate_patient_insurance(self, count: int) -> List[Dict[str, Any]]:
        """Generate patient insurance records."""
        insurance_types = ['PRIMARY', 'SECONDARY', 'TERTIARY']
        payers = [
            ('BCBS', 'Blue Cross Blue Shield'), ('AETNA', 'Aetna'), ('CIGNA', 'Cigna'),
            ('UHC', 'UnitedHealthcare'), ('HUMANA', 'Humana'), ('MEDICARE', 'Medicare'),
            ('MEDICAID', 'Medicaid'), ('KAISER', 'Kaiser Permanente')
        ]
        records = []
        for i in range(count):
            payer_id, payer_name = random.choice(payers)
            records.append({
                'insurance_id': i + 1,
                'patient_id': self._get_random_id('patients'),
                'insurance_type': random.choice(insurance_types),
                'payer_id': payer_id,
                'payer_name': payer_name,
                'plan_name': f"{payer_name} {random.choice(['PPO', 'HMO', 'EPO', 'POS'])}",
                'policy_number': f"POL{random.randint(100000000, 999999999)}",
                'group_number': f"GRP{random.randint(10000, 99999)}" if random.random() > 0.3 else None,
                'subscriber_id': f"SUB{random.randint(100000000, 999999999)}",
                'subscriber_name': f"{self.fake.first_name()} {self.fake.last_name()}",
                'subscriber_relationship': random.choice(['SELF', 'SPOUSE', 'CHILD', 'OTHER']),
                'effective_date': self._random_date(365 * 2),
                'termination_date': self._random_date(30, -365) if random.random() > 0.8 else None,
                'copay_amount': round(random.uniform(10, 50), 2),
                'deductible': round(random.uniform(500, 5000), 2),
                'deductible_met': round(random.uniform(0, 3000), 2),
                'out_of_pocket_max': round(random.uniform(3000, 10000), 2),
                'out_of_pocket_met': round(random.uniform(0, 5000), 2),
                'authorization_required': random.random() > 0.5,
                'is_active': True,
                'created_at': self._random_datetime(365 * 2),
            })
        self._cache_ids('patient_insurance', [r['insurance_id'] for r in records])
        return records

    def generate_patient_contacts(self, count: int) -> List[Dict[str, Any]]:
        """Generate patient contact records."""
        contact_types = ['EMERGENCY', 'GUARDIAN', 'NEXT_OF_KIN', 'POWER_OF_ATTORNEY']
        relation_types = ['SPOUSE', 'PARENT', 'CHILD', 'SIBLING', 'FRIEND', 'OTHER']
        records = []
        for i in range(count):
            records.append({
                'contact_id': i + 1,
                'patient_id': self._get_random_id('patients'),
                'contact_type': random.choice(contact_types),
                'relation_type': random.choice(relation_types),
                'first_name': self.fake.first_name(),
                'last_name': self.fake.last_name(),
                'phone': self.fake.phone_number()[:20],
                'email': self.fake.email() if random.random() > 0.3 else None,
                'address': self.fake.address().replace('\n', ', ') if random.random() > 0.5 else None,
                'is_primary': random.random() > 0.7,
                'created_at': self._random_datetime(365 * 2),
            })
        return records

    def generate_emergency_contacts(self, count: int) -> List[Dict[str, Any]]:
        """Generate emergency contact records."""
        relationships = ['SPOUSE', 'PARENT', 'CHILD', 'SIBLING', 'FRIEND', 'OTHER']
        records = []
        for i in range(count):
            records.append({
                'contact_id': i + 1,
                'patient_id': self._get_random_id('patients'),
                'contact_name': f"{self.fake.first_name()} {self.fake.last_name()}",
                'relationship': random.choice(relationships),
                'phone_primary': self.fake.phone_number()[:20],
                'phone_secondary': self.fake.phone_number()[:20] if random.random() > 0.5 else None,
                'is_legal_guardian': random.random() > 0.9,
                'priority': random.randint(1, 3),
                'created_at': self._random_datetime(365 * 2),
            })
        return records

    def generate_family_history(self, count: int) -> List[Dict[str, Any]]:
        """Generate family history records."""
        relationships = ['MOTHER', 'FATHER', 'SIBLING', 'GRANDPARENT', 'AUNT', 'UNCLE']
        conditions = [
            'Diabetes', 'Hypertension', 'Heart Disease', 'Cancer', 'Stroke',
            'Alzheimer''s', 'Arthritis', 'Asthma', 'Depression', 'Obesity'
        ]
        records = []
        for i in range(count):
            records.append({
                'history_id': i + 1,
                'patient_id': self._get_random_id('patients'),
                'relationship': random.choice(relationships),
                'condition': random.choice(conditions),
                'condition_code': self.fake.icd10_code() if random.random() > 0.5 else None,
                'onset_age': random.randint(30, 80) if random.random() > 0.3 else None,
                'deceased': random.random() > 0.7,
                'cause_of_death': random.choice(conditions) if random.random() > 0.7 else None,
                'notes': self.fake.sentence() if random.random() > 0.7 else None,
                'created_at': self._random_datetime(365 * 2),
            })
        return records

    def generate_condition_history(self, count: int) -> List[Dict[str, Any]]:
        """Generate condition/problem history records."""
        records = []
        for i in range(count):
            onset = self._random_date(365 * 10)
            resolved = random.random() > 0.6
            records.append({
                'condition_id': i + 1,
                'patient_id': self._get_random_id('patients'),
                'condition_code': self.fake.icd10_code(),
                'condition_name': self.fake.diagnosis(),
                'onset_date': onset,
                'resolved_date': self._random_date(365, 30) if resolved else None,
                'status': 'RESOLVED' if resolved else random.choice(['ACTIVE', 'CHRONIC', 'IMPROVING']),
                'severity': random.choice(['MILD', 'MODERATE', 'SEVERE']),
                'verified': random.random() > 0.2,
                'source': random.choice(['SELF_REPORTED', 'PROVIDER', 'IMPORTED', 'LAB']),
                'created_at': self._random_datetime(365 * 2),
            })
        return records

    def generate_patient_consents(self, count: int) -> List[Dict[str, Any]]:
        """Generate patient consent records."""
        consent_types = [
            'TREATMENT', 'HIPAA', 'RESEARCH', 'PHOTOGRAPHY', 'ELECTRONIC_COMMUNICATION',
            'PROCEDURE', 'ANESTHESIA', 'BLOOD_TRANSFUSION', 'TELEHEALTH'
        ]
        records = []
        for i in range(count):
            granted = random.random() > 0.1
            records.append({
                'consent_id': i + 1,
                'patient_id': self._get_random_id('patients'),
                'consent_type': random.choice(consent_types),
                'description': f"Consent for {random.choice(consent_types).lower().replace('_', ' ')}",
                'effective_date': self._random_date(365 * 2),
                'expiration_date': self._random_date(30, -365 * 2) if random.random() > 0.5 else None,
                'granted': granted,
                'signed_by': f"{self.fake.first_name()} {self.fake.last_name()}",
                'witness': f"{self.fake.first_name()} {self.fake.last_name()}" if random.random() > 0.5 else None,
                'document_url': f"/documents/consent_{i+1}.pdf" if random.random() > 0.3 else None,
                'revoked': not granted and random.random() > 0.8,
                'revoked_date': self._random_date(30) if random.random() > 0.9 else None,
                'is_active': True,
                'created_at': self._random_datetime(365 * 2),
            })
        return records

    def generate_patient_documents(self, count: int) -> List[Dict[str, Any]]:
        """Generate patient document records."""
        doc_types = ['LAB_RESULT', 'RADIOLOGY_REPORT', 'CONSENT', 'REFERRAL', 'INSURANCE', 'ID', 'MEDICAL_RECORD']
        categories = ['CLINICAL', 'ADMINISTRATIVE', 'LEGAL', 'INSURANCE']
        records = []
        for i in range(count):
            doc_type = random.choice(doc_types)
            records.append({
                'document_id': i + 1,
                'patient_id': self._get_random_id('patients'),
                'document_type': doc_type,
                'document_name': f"{doc_type.lower().replace('_', ' ').title()} - {self.fake.date()}",
                'description': f"Patient {doc_type.lower().replace('_', ' ')} document",
                'file_path': f"/documents/{doc_type.lower()}/{self.fake.uuid4()}.pdf",
                'file_size': random.randint(10000, 5000000),
                'mime_type': random.choice(['application/pdf', 'image/jpeg', 'image/png']),
                'uploaded_date': self._random_datetime(365),
                'uploaded_by': self._get_random_id('users') if random.random() > 0.3 else None,
                'encounter_id': self._get_random_id('medical_records') if random.random() > 0.5 else None,
                'category': random.choice(categories),
                'created_at': self._random_datetime(365),
            })
        return records

    def generate_patient_immunizations(self, count: int) -> List[Dict[str, Any]]:
        """Generate patient immunization records."""
        vaccines = [
            ('FLU', 'Influenza'), ('COVID', 'COVID-19'), ('TDAP', 'Tetanus/Diphtheria/Pertussis'),
            ('MMR', 'Measles/Mumps/Rubella'), ('HEP-A', 'Hepatitis A'), ('HEP-B', 'Hepatitis B'),
            ('SHINGLES', 'Shingles'), ('PNEUMO', 'Pneumococcal'), ('HPV', 'Human Papillomavirus')
        ]
        records = []
        for i in range(count):
            vaccine_code, vaccine_name = random.choice(vaccines)
            records.append({
                'immunization_id': i + 1,
                'patient_id': self._get_random_id('patients'),
                'vaccine_name': vaccine_name,
                'vaccine_code': vaccine_code,
                'manufacturer': random.choice(['Pfizer', 'Moderna', 'Johnson & Johnson', 'Merck', 'GSK']),
                'lot_number': f"LOT{random.randint(100000, 999999)}",
                'expiration_date': self._random_date(30, -365),
                'administration_date': self._random_date(365 * 5),
                'site': random.choice(['LEFT_ARM', 'RIGHT_ARM', 'LEFT_THIGH', 'RIGHT_THIGH']),
                'route': random.choice(['IM', 'SC', 'ID', 'ORAL']),
                'dose_number': random.randint(1, 3),
                'administrator_id': self._get_random_id('providers') if random.random() > 0.3 else None,
                'facility': random.choice(['Main Clinic', 'Pharmacy', 'Urgent Care', 'Hospital']),
                'reaction': random.choice(['NONE', 'MILD', 'MODERATE']) if random.random() > 0.8 else None,
                'created_at': self._random_datetime(365 * 2),
            })
        return records

    def generate_patient_communication_log(self, count: int) -> List[Dict[str, Any]]:
        """Generate patient communication log records."""
        comm_types = ['PHONE', 'EMAIL', 'SMS', 'LETTER', 'PORTAL_MESSAGE']
        directions = ['INBOUND', 'OUTBOUND']
        records = []
        for i in range(count):
            records.append({
                'log_id': i + 1,
                'patient_id': self._get_random_id('patients'),
                'communication_type': random.choice(comm_types),
                'direction': random.choice(directions),
                'subject': random.choice(['Appointment Reminder', 'Lab Results', 'Prescription Ready', 'Follow-up', 'Billing Question']),
                'content': self.fake.paragraph(),
                'sent_at': self._random_datetime(90),
                'sent_by': self._get_random_id('users') if random.random() > 0.3 else None,
                'status': random.choice(['SENT', 'DELIVERED', 'FAILED', 'READ']),
                'response_received': random.random() > 0.6,
            })
        return records

    def generate_appointments(self, count: int) -> List[Dict[str, Any]]:
        """Generate appointment records."""
        statuses = ['SCHEDULED', 'CONFIRMED', 'CHECKED_IN', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED', 'NO_SHOW']
        records = []
        for i in range(count):
            scheduled = self._random_datetime(60, -30)
            status = random.choice(statuses)
            records.append({
                'appointment_id': i + 1,
                'patient_id': self._get_random_id('patients'),
                'provider_id': self._get_random_id('providers'),
                'appointment_type_id': self._get_random_id('appointment_types'),
                'scheduled_date': scheduled.date(),
                'scheduled_time': scheduled,
                'duration_minutes': random.choice([15, 20, 30, 45, 60, 90]),
                'room_id': self._get_random_id('rooms') if random.random() > 0.3 else None,
                'status': status,
                'reason': self.fake.sentence()[:200],
                'notes': self.fake.paragraph() if random.random() > 0.5 else None,
                'check_in_time': scheduled - timedelta(minutes=random.randint(5, 30)) if status in ['CHECKED_IN', 'IN_PROGRESS', 'COMPLETED'] else None,
                'start_time': scheduled if status in ['IN_PROGRESS', 'COMPLETED'] else None,
                'end_time': scheduled + timedelta(minutes=random.randint(15, 60)) if status == 'COMPLETED' else None,
                'is_telehealth': random.random() > 0.8,
                'telehealth_url': f"https://telehealth.example.com/{self.fake.uuid4()}" if random.random() > 0.8 else None,
                'confirmation_sent': random.random() > 0.2,
                'reminder_sent': random.random() > 0.3,
                'is_active': True,
                'created_at': self._random_datetime(365),
            })
        self._cache_ids('appointments', [r['appointment_id'] for r in records])
        return records

    def generate_appointment_reminders(self, count: int) -> List[Dict[str, Any]]:
        """Generate appointment reminder records."""
        reminder_types = ['EMAIL', 'SMS', 'PHONE', 'PORTAL']
        records = []
        for i in range(count):
            scheduled = self._random_datetime(30)
            sent = random.random() > 0.3
            records.append({
                'reminder_id': i + 1,
                'appointment_id': self._get_random_id('appointments'),
                'reminder_type': random.choice(reminder_types),
                'scheduled_date': scheduled,
                'sent_date': scheduled if sent else None,
                'status': 'SENT' if sent else random.choice(['PENDING', 'FAILED', 'CANCELLED']),
                'response': random.choice(['CONFIRMED', 'CANCELLED', 'NO_RESPONSE', None]) if sent else None,
                'created_at': self._random_datetime(60),
            })
        return records

    def generate_cancellations(self, count: int) -> List[Dict[str, Any]]:
        """Generate appointment cancellation records."""
        reasons = [
            'Patient requested', 'Provider unavailable', 'Insurance issue',
            'Weather', 'Emergency', 'Transportation', 'Illness', 'Schedule conflict'
        ]
        records = []
        for i in range(count):
            cancelled_date = self._random_datetime(60)
            records.append({
                'cancellation_id': i + 1,
                'appointment_id': self._get_random_id('appointments'),
                'cancelled_date': cancelled_date,
                'cancelled_by': random.choice(['PATIENT', 'PROVIDER', 'STAFF', 'SYSTEM']),
                'reason': random.choice(reasons),
                'notice_hours': random.randint(0, 72),
                'rescheduled': random.random() > 0.5,
                'reschedule_appointment_id': self._get_random_id('appointments') if random.random() > 0.7 else None,
                'created_at': cancelled_date,
            })
        return records

    def generate_no_shows(self, count: int) -> List[Dict[str, Any]]:
        """Generate no-show records."""
        records = []
        for i in range(count):
            records.append({
                'no_show_id': i + 1,
                'appointment_id': self._get_random_id('appointments'),
                'patient_id': self._get_random_id('patients'),
                'no_show_date': self._random_datetime(90),
                'reason': random.choice(['Unknown', 'Forgot', 'Transportation', 'Illness', 'Emergency', None]),
                'contacted': random.random() > 0.4,
                'rescheduled': random.random() > 0.6,
                'fee_charged': round(random.uniform(25, 75), 2) if random.random() > 0.7 else None,
                'created_at': self._random_datetime(90),
            })
        return records

    def generate_waiting_lists(self, count: int) -> List[Dict[str, Any]]:
        """Generate waiting list records."""
        records = []
        for i in range(count):
            added = self._random_datetime(30)
            records.append({
                'waitlist_id': i + 1,
                'patient_id': self._get_random_id('patients'),
                'provider_id': self._get_random_id('providers') if random.random() > 0.3 else None,
                'appointment_type_id': self._get_random_id('appointment_types'),
                'preferred_dates': random.choice(['Weekdays', 'Weekends', 'Mondays', 'Any']),
                'preferred_times': random.choice(['Morning', 'Afternoon', 'Evening', 'Any']),
                'reason': self.fake.sentence()[:200],
                'priority': random.randint(1, 5),
                'added_date': added,
                'contacted_date': added + timedelta(days=random.randint(1, 7)) if random.random() > 0.5 else None,
                'status': random.choice(['WAITING', 'CONTACTED', 'SCHEDULED', 'CANCELLED', 'EXPIRED']),
                'created_at': added,
            })
        return records

    def generate_vitals(self, count: int) -> List[Dict[str, Any]]:
        """Generate vital signs header records."""
        records = []
        for i in range(count):
            recorded = self._random_datetime(365)
            records.append({
                'vital_id': i + 1,
                'record_id': self._get_random_id('medical_records') if random.random() > 0.3 else None,
                'patient_id': self._get_random_id('patients'),
                'recorded_date': recorded,
                'recorded_by': self._get_random_id('providers') if random.random() > 0.2 else None,
                'location': random.choice(['Exam Room 1', 'Exam Room 2', 'Triage', 'Emergency', 'Clinic']),
                'created_at': recorded,
            })
        self._cache_ids('vitals', [r['vital_id'] for r in records])
        return records

    def generate_vital_readings(self, count: int) -> List[Dict[str, Any]]:
        """Generate vital sign reading records. Note: 'value' is a reserved keyword."""
        vital_types = [
            ('BP_SYSTOLIC', '120', 'mmHg'),
            ('BP_DIASTOLIC', '80', 'mmHg'),
            ('TEMPERATURE', '98.6', 'F'),
            ('PULSE', '72', 'bpm'),
            ('RESPIRATORY_RATE', '16', '/min'),
            ('O2_SATURATION', '98', '%'),
            ('HEIGHT', '70', 'in'),
            ('WEIGHT', '180', 'lbs'),
        ]
        records = []
        for i in range(count):
            vital_type, base_value, unit = random.choice(vital_types)
            # Generate realistic variations
            if vital_type == 'BP_SYSTOLIC':
                value = str(random.randint(90, 180))
            elif vital_type == 'BP_DIASTOLIC':
                value = str(random.randint(60, 110))
            elif vital_type == 'TEMPERATURE':
                value = str(round(random.uniform(97.0, 103.0), 1))
            elif vital_type == 'PULSE':
                value = str(random.randint(50, 120))
            elif vital_type == 'RESPIRATORY_RATE':
                value = str(random.randint(12, 24))
            elif vital_type == 'O2_SATURATION':
                value = str(random.randint(88, 100))
            elif vital_type == 'HEIGHT':
                value = str(random.randint(60, 78))
            elif vital_type == 'WEIGHT':
                value = str(random.randint(100, 300))
            else:
                value = base_value

            records.append({
                'reading_id': i + 1,
                'vital_id': self._get_random_id('vitals'),
                'vital_type': vital_type,
                'value': value,  # Reserved keyword - will be bracketed as [value]
                'unit': unit,
                'position': random.choice(['SITTING', 'STANDING', 'SUPINE', None]),
                'notes': self.fake.sentence() if random.random() > 0.8 else None,
                'created_at': self._random_datetime(365),
            })
        return records

    def generate_procedures(self, count: int) -> List[Dict[str, Any]]:
        """Generate procedure records."""
        records = []
        for i in range(count):
            proc_date = self._random_datetime(365)
            records.append({
                'procedure_id': i + 1,
                'record_id': self._get_random_id('medical_records'),
                'patient_id': self._get_random_id('patients'),
                'procedure_code': self.fake.cpt_code(),
                'procedure_description': self.fake.procedure(),
                'procedure_date': proc_date,
                'performing_provider_id': self._get_random_id('providers'),
                'facility': random.choice(['Main Hospital', 'Surgical Center', 'Clinic', 'Outpatient']),
                'modifiers': random.choice(['25', '59', '76', '77', None]),
                'quantity': random.randint(1, 3),
                'notes': self.fake.sentence() if random.random() > 0.5 else None,
                'status': random.choice(['SCHEDULED', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED']),
                'outcome': random.choice(['SUCCESS', 'PARTIAL', 'COMPLICATIONS', None]) if random.random() > 0.3 else None,
                'created_at': proc_date,
            })
        return records

    def generate_prescriptions(self, count: int) -> List[Dict[str, Any]]:
        """Generate prescription records with unique rx_number."""
        drug_names = [
            'Metformin 500mg', 'Lisinopril 10mg', 'Atorvastatin 20mg', 'Metoprolol 25mg',
            'Amlodipine 5mg', 'Omeprazole 20mg', 'Losartan 50mg', 'Gabapentin 300mg',
            'Sertraline 50mg', 'Levothyroxine 50mcg', 'Furosemide 40mg', 'Prednisone 10mg'
        ]
        dosage_forms = ['TABLET', 'CAPSULE', 'LIQUID', 'INJECTION', 'PATCH', 'INHALER']
        used_rx_numbers = set()
        records = []
        for i in range(count):
            # Generate unique rx_number
            rx_number = f"RX{i + 1:08d}"
            if rx_number in used_rx_numbers:
                continue
            used_rx_numbers.add(rx_number)

            written = self._random_datetime(180)
            records.append({
                'prescription_id': i + 1,
                'patient_id': self._get_random_id('patients'),
                'record_id': self._get_random_id('medical_records') if random.random() > 0.3 else None,
                'rx_number': rx_number,
                'prescriber_id': self._get_random_id('providers'),
                'drug_name': random.choice(drug_names),
                'drug_code': f"NDC{random.randint(10000000, 99999999)}",
                'strength': random.choice(['5mg', '10mg', '20mg', '25mg', '50mg', '100mg']),
                'dosage_form': random.choice(dosage_forms),
                'quantity': random.choice([30, 60, 90, 120]),
                'days_supply': random.choice([30, 60, 90]),
                'sig': random.choice(['Take 1 tablet by mouth daily', 'Take 1 tablet twice daily', 'Take as directed']),
                'refills_authorized': random.randint(0, 5),
                'refills_remaining': random.randint(0, 5),
                'daw_code': random.choice(['0', '1', '2', None]),
                'written_date': written,
                'effective_date': written,
                'expiration_date': written + timedelta(days=365),
                'status': random.choice(['ACTIVE', 'FILLED', 'CANCELLED', 'EXPIRED']),
                'pharmacy_id': f"PHARM{random.randint(1000, 9999)}" if random.random() > 0.3 else None,
                'pharmacy_name': random.choice(['CVS Pharmacy', 'Walgreens', 'Rite Aid', 'Walmart Pharmacy']),
                'is_active': True,
                'created_at': written,
            })
        self._cache_ids('prescriptions', [r['prescription_id'] for r in records])
        return records

    def generate_prescription_fills(self, count: int) -> List[Dict[str, Any]]:
        """Generate prescription fill records."""
        records = []
        for i in range(count):
            fill_date = self._random_datetime(180)
            records.append({
                'fill_id': i + 1,
                'prescription_id': self._get_random_id('prescriptions'),
                'fill_number': random.randint(1, 6),
                'fill_date': fill_date,
                'quantity_dispensed': random.choice([30, 60, 90]),
                'days_supply': random.choice([30, 60, 90]),
                'pharmacy_id': f"PHARM{random.randint(1000, 9999)}",
                'pharmacy_name': random.choice(['CVS Pharmacy', 'Walgreens', 'Rite Aid', 'Walmart Pharmacy']),
                'pharmacist': f"{self.fake.first_name()} {self.fake.last_name()}, RPh",
                'dispensed_drug_code': f"NDC{random.randint(10000000, 99999999)}",
                'dispensed_drug_name': random.choice(['Generic', 'Brand']),
                'copay': round(random.uniform(0, 50), 2),
                'created_at': fill_date,
            })
        return records

    def generate_lab_orders(self, count: int) -> List[Dict[str, Any]]:
        """Generate lab order records with unique order_number."""
        used_order_numbers = set()
        records = []
        for i in range(count):
            # Generate unique order_number
            order_number = f"LAB{i + 1:08d}"
            if order_number in used_order_numbers:
                continue
            used_order_numbers.add(order_number)

            order_date = self._random_datetime(90)
            status = random.choice(['ORDERED', 'COLLECTED', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED'])
            records.append({
                'order_id': i + 1,
                'patient_id': self._get_random_id('patients'),
                'record_id': self._get_random_id('medical_records') if random.random() > 0.3 else None,
                'order_number': order_number,
                'ordering_provider_id': self._get_random_id('providers'),
                'order_date': order_date,
                'priority': random.choice(['ROUTINE', 'STAT', 'URGENT']),
                'fasting_required': random.random() > 0.7,
                'clinical_notes': self.fake.sentence() if random.random() > 0.5 else None,
                'status': status,
                'collection_date': order_date + timedelta(hours=random.randint(1, 48)) if status != 'ORDERED' else None,
                'received_date': order_date + timedelta(hours=random.randint(2, 72)) if status in ['IN_PROGRESS', 'COMPLETED'] else None,
                'completed_date': order_date + timedelta(hours=random.randint(24, 96)) if status == 'COMPLETED' else None,
                'is_active': True,
                'created_at': order_date,
            })
        self._cache_ids('lab_orders', [r['order_id'] for r in records])
        return records

    def generate_lab_results(self, count: int) -> List[Dict[str, Any]]:
        """Generate lab result records."""
        tests = [
            ('GLU', 'Glucose', '70-100', 'mg/dL'),
            ('HBA1C', 'Hemoglobin A1C', '4.0-5.6', '%'),
            ('WBC', 'White Blood Cells', '4.5-11.0', 'K/uL'),
            ('RBC', 'Red Blood Cells', '4.5-5.5', 'M/uL'),
            ('HGB', 'Hemoglobin', '12.0-17.5', 'g/dL'),
            ('CHOL', 'Total Cholesterol', '<200', 'mg/dL'),
            ('TSH', 'Thyroid Stimulating Hormone', '0.4-4.0', 'mIU/L'),
            ('CREAT', 'Creatinine', '0.7-1.3', 'mg/dL'),
        ]
        records = []
        for i in range(count):
            test_code, test_name, ref_range, unit = random.choice(tests)
            value = str(round(random.uniform(50, 200), 1))
            abnormal = random.random() > 0.8
            records.append({
                'result_id': i + 1,
                'order_id': self._get_random_id('lab_orders'),
                'test_code': test_code,
                'test_name': test_name,
                'result_value': value,
                'result_unit': unit,
                'reference_range': ref_range,
                'abnormal_flag': random.choice(['H', 'L', 'A']) if abnormal else None,
                'result_status': random.choice(['FINAL', 'PRELIMINARY', 'CORRECTED']),
                'performed_date': self._random_datetime(60),
                'performed_by': f"{self.fake.first_name()} {self.fake.last_name()}, MT",
                'notes': self.fake.sentence() if random.random() > 0.8 else None,
                'created_at': self._random_datetime(60),
            })
        return records

    def generate_radiology_orders(self, count: int) -> List[Dict[str, Any]]:
        """Generate radiology order records with unique order_number."""
        modalities = ['XRAY', 'CT', 'MRI', 'US', 'NM', 'PET', 'MAMMO', 'FLUORO']
        body_parts = ['CHEST', 'ABDOMEN', 'HEAD', 'SPINE', 'EXTREMITY', 'PELVIS', 'NECK']
        used_order_numbers = set()
        records = []
        for i in range(count):
            # Generate unique order_number
            order_number = f"RAD{i + 1:08d}"
            if order_number in used_order_numbers:
                continue
            used_order_numbers.add(order_number)

            order_date = self._random_datetime(90)
            status = random.choice(['ORDERED', 'SCHEDULED', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED'])
            records.append({
                'order_id': i + 1,
                'patient_id': self._get_random_id('patients'),
                'record_id': self._get_random_id('medical_records') if random.random() > 0.3 else None,
                'order_number': order_number,
                'ordering_provider_id': self._get_random_id('providers'),
                'order_date': order_date,
                'modality': random.choice(modalities),
                'body_part': random.choice(body_parts),
                'laterality': random.choice(['LEFT', 'RIGHT', 'BILATERAL', None]),
                'contrast': random.random() > 0.6,
                'priority': random.choice(['ROUTINE', 'STAT', 'URGENT']),
                'clinical_indication': self.fake.diagnosis(),
                'status': status,
                'scheduled_date': order_date + timedelta(days=random.randint(1, 7)) if status != 'ORDERED' else None,
                'performed_date': order_date + timedelta(days=random.randint(1, 14)) if status == 'COMPLETED' else None,
                'is_active': True,
                'created_at': order_date,
            })
        self._cache_ids('radiology_orders', [r['order_id'] for r in records])
        return records

    def generate_radiology_results(self, count: int) -> List[Dict[str, Any]]:
        """Generate radiology result records with unique accession_number."""
        used_accession_numbers = set()
        records = []
        for i in range(count):
            # Generate unique accession_number
            accession_number = f"ACC{i + 1:08d}"
            if accession_number in used_accession_numbers:
                continue
            used_accession_numbers.add(accession_number)

            study_date = self._random_datetime(60)
            critical = random.random() > 0.95
            records.append({
                'result_id': i + 1,
                'order_id': self._get_random_id('radiology_orders'),
                'accession_number': accession_number,
                'study_date': study_date,
                'reading_physician_id': self._get_random_id('providers'),
                'technique': self.fake.paragraph()[:500],
                'findings': self.fake.paragraph(),
                'impression': self.fake.sentence(),
                'comparison': f"Prior study dated {self._random_date(365 * 2)}" if random.random() > 0.5 else None,
                'status': random.choice(['FINAL', 'PRELIMINARY', 'ADDENDUM']),
                'critical_finding': critical,
                'critical_communicated': critical and random.random() > 0.1,
                'communicated_to': f"Dr. {self.fake.last_name()}" if critical else None,
                'communicated_date': study_date + timedelta(hours=random.randint(1, 4)) if critical else None,
                'created_at': study_date,
            })
        return records

    def generate_pathology_reports(self, count: int) -> List[Dict[str, Any]]:
        """Generate pathology report records with unique accession_number."""
        specimen_types = ['TISSUE', 'FLUID', 'BLOOD', 'URINE', 'BONE_MARROW', 'SKIN', 'LYMPH_NODE']
        used_accession_numbers = set()
        records = []
        for i in range(count):
            # Generate unique accession_number
            accession_number = f"PATH{i + 1:08d}"
            if accession_number in used_accession_numbers:
                continue
            used_accession_numbers.add(accession_number)

            collection_date = self._random_datetime(60)
            records.append({
                'report_id': i + 1,
                'patient_id': self._get_random_id('patients'),
                'record_id': self._get_random_id('medical_records') if random.random() > 0.3 else None,
                'accession_number': accession_number,
                'specimen_type': random.choice(specimen_types),
                'specimen_site': random.choice(['Left breast', 'Right lung', 'Colon', 'Liver', 'Skin', 'Lymph node']),
                'collection_date': collection_date,
                'received_date': collection_date + timedelta(hours=random.randint(1, 24)),
                'pathologist_id': self._get_random_id('providers'),
                'gross_description': self.fake.paragraph() if random.random() > 0.3 else None,
                'microscopic_description': self.fake.paragraph() if random.random() > 0.3 else None,
                'diagnosis': self.fake.diagnosis(),
                'additional_tests': random.choice(['IHC performed', 'Special stains', 'Flow cytometry', None]),
                'status': random.choice(['FINAL', 'PRELIMINARY', 'ADDENDUM']),
                'signed_date': collection_date + timedelta(days=random.randint(1, 7)) if random.random() > 0.2 else None,
                'is_active': True,
                'created_at': collection_date,
            })
        return records

    def generate_clinical_notes(self, count: int) -> List[Dict[str, Any]]:
        """Generate clinical note records."""
        note_types = ['PROGRESS', 'CONSULT', 'H&P', 'PROCEDURE', 'DISCHARGE', 'TELEPHONE', 'NURSING']
        records = []
        for i in range(count):
            note_date = self._random_datetime(180)
            signed = random.random() > 0.2
            records.append({
                'note_id': i + 1,
                'record_id': self._get_random_id('medical_records') if random.random() > 0.3 else None,
                'patient_id': self._get_random_id('patients'),
                'note_type': random.choice(note_types),
                'author_id': self._get_random_id('providers'),
                'note_date': note_date,
                'note_text': self.fake.paragraph(nb_sentences=5),
                'status': 'SIGNED' if signed else random.choice(['DRAFT', 'PENDING', 'AMENDED']),
                'signed_date': note_date + timedelta(hours=random.randint(1, 24)) if signed else None,
                'cosigner_id': self._get_random_id('providers') if random.random() > 0.8 else None,
                'cosigned_date': note_date + timedelta(days=random.randint(1, 3)) if random.random() > 0.9 else None,
                'addendum': self.fake.sentence() if random.random() > 0.9 else None,
                'addendum_date': note_date + timedelta(days=random.randint(1, 7)) if random.random() > 0.9 else None,
                'is_active': True,
                'created_at': note_date,
            })
        return records

    def generate_progress_notes(self, count: int) -> List[Dict[str, Any]]:
        """Generate progress note records. Note: 'plan' is a reserved keyword."""
        records = []
        for i in range(count):
            note_date = self._random_datetime(180)
            signed = random.random() > 0.2
            records.append({
                'note_id': i + 1,
                'patient_id': self._get_random_id('patients'),
                'record_id': self._get_random_id('medical_records') if random.random() > 0.3 else None,
                'author_id': self._get_random_id('providers'),
                'note_date': note_date,
                'subjective': self.fake.paragraph() if random.random() > 0.2 else None,
                'objective': self.fake.paragraph() if random.random() > 0.2 else None,
                'assessment': self.fake.diagnosis(),
                'plan': self.fake.treatment(),  # Reserved keyword - will be bracketed as [plan]
                'status': 'SIGNED' if signed else random.choice(['DRAFT', 'PENDING']),
                'signed_date': note_date + timedelta(hours=random.randint(1, 24)) if signed else None,
                'is_active': True,
                'created_at': note_date,
            })
        return records

    def generate_treatment_plans(self, count: int) -> List[Dict[str, Any]]:
        """Generate treatment plan records."""
        records = []
        for i in range(count):
            start_date = self._random_datetime(180)
            status = random.choice(['ACTIVE', 'COMPLETED', 'DISCONTINUED', 'ON_HOLD'])
            records.append({
                'plan_id': i + 1,
                'patient_id': self._get_random_id('patients'),
                'record_id': self._get_random_id('medical_records') if random.random() > 0.3 else None,
                'plan_name': f"Treatment Plan for {self.fake.diagnosis()}",
                'primary_diagnosis': self.fake.diagnosis(),
                'goals': self.fake.paragraph(),
                'interventions': self.fake.paragraph(),
                'start_date': start_date,
                'target_end_date': start_date + timedelta(days=random.randint(30, 365)),
                'actual_end_date': start_date + timedelta(days=random.randint(30, 365)) if status in ['COMPLETED', 'DISCONTINUED'] else None,
                'status': status,
                'created_by': self._get_random_id('providers'),
                'reviewed_date': self._random_datetime(30) if random.random() > 0.5 else None,
                'reviewed_by': self._get_random_id('providers') if random.random() > 0.5 else None,
                'is_active': status == 'ACTIVE',
                'created_at': start_date,
            })
        return records

    def generate_care_teams(self, count: int) -> List[Dict[str, Any]]:
        """Generate care team records."""
        records = []
        for i in range(count):
            start_date = self._random_datetime(365)
            active = random.random() > 0.2
            records.append({
                'team_id': i + 1,
                'patient_id': self._get_random_id('patients'),
                'team_name': f"Care Team {i + 1}",
                'primary_provider_id': self._get_random_id('providers'),
                'start_date': start_date,
                'end_date': start_date + timedelta(days=random.randint(90, 365)) if not active else None,
                'status': 'ACTIVE' if active else 'INACTIVE',
                'notes': self.fake.sentence() if random.random() > 0.5 else None,
                'is_active': active,
                'created_at': start_date,
            })
        self._cache_ids('care_teams', [r['team_id'] for r in records])
        return records

    def generate_care_team_members(self, count: int) -> List[Dict[str, Any]]:
        """Generate care team member records."""
        roles = ['Primary Physician', 'Specialist', 'Nurse', 'Care Coordinator', 'Social Worker', 'Pharmacist']
        records = []
        for i in range(count):
            start_date = self._random_datetime(365)
            records.append({
                'member_id': i + 1,
                'team_id': self._get_random_id('care_teams'),
                'provider_id': self._get_random_id('providers'),
                'role': random.choice(roles),
                'start_date': start_date,
                'end_date': start_date + timedelta(days=random.randint(90, 365)) if random.random() > 0.7 else None,
                'is_primary': random.random() > 0.8,
                'created_at': start_date,
            })
        return records

    def generate_referrals(self, count: int) -> List[Dict[str, Any]]:
        """Generate referral records."""
        priorities = ['ROUTINE', 'URGENT', 'STAT']
        statuses = ['PENDING', 'SENT', 'RECEIVED', 'SCHEDULED', 'COMPLETED', 'CANCELLED']
        records = []
        for i in range(count):
            referral_date = self._random_datetime(90)
            status = random.choice(statuses)
            records.append({
                'referral_id': i + 1,
                'patient_id': self._get_random_id('patients'),
                'record_id': self._get_random_id('medical_records') if random.random() > 0.3 else None,
                'referring_provider_id': self._get_random_id('providers'),
                'referred_to_provider_id': self._get_random_id('providers') if random.random() > 0.3 else None,
                'referred_to_facility': random.choice(['City Hospital', 'Specialty Center', 'University Medical Center', None]),
                'specialty': self.fake.specialty(),
                'referral_date': referral_date,
                'expiration_date': referral_date + timedelta(days=random.choice([30, 60, 90])),
                'priority': random.choice(priorities),
                'reason': self.fake.sentence(),
                'diagnosis_codes': self.fake.icd10_code(),
                'authorization_number': f"AUTH{random.randint(100000, 999999)}" if random.random() > 0.5 else None,
                'status': status,
                'appointment_date': referral_date + timedelta(days=random.randint(7, 30)) if status in ['SCHEDULED', 'COMPLETED'] else None,
                'notes': self.fake.sentence() if random.random() > 0.5 else None,
                'is_active': True,
                'created_at': referral_date,
            })
        return records

    def generate_claims(self, count: int) -> List[Dict[str, Any]]:
        """Generate claim records with unique claim_number."""
        claim_types = ['PROFESSIONAL', 'INSTITUTIONAL', 'DENTAL', 'PHARMACY']
        statuses = ['SUBMITTED', 'PENDING', 'ADJUDICATED', 'PAID', 'DENIED', 'APPEALED']
        used_claim_numbers = set()
        records = []
        for i in range(count):
            # Generate unique claim_number
            claim_number = f"CLM{i + 1:08d}"
            if claim_number in used_claim_numbers:
                continue
            used_claim_numbers.add(claim_number)

            service_date = self._random_datetime(180)
            total_charge = round(random.uniform(100, 5000), 2)
            status = random.choice(statuses)
            records.append({
                'claim_id': i + 1,
                'claim_number': claim_number,
                'patient_id': self._get_random_id('patients'),
                'record_id': self._get_random_id('medical_records') if random.random() > 0.3 else None,
                'insurance_id': self._get_random_id('patient_insurance'),
                'claim_type': random.choice(claim_types),
                'service_date': service_date,
                'submission_date': service_date + timedelta(days=random.randint(1, 7)) if status != 'PENDING' else None,
                'total_charge': total_charge,
                'total_allowed': round(total_charge * random.uniform(0.5, 0.9), 2) if status in ['ADJUDICATED', 'PAID'] else None,
                'total_paid': round(total_charge * random.uniform(0.3, 0.8), 2) if status == 'PAID' else None,
                'patient_responsibility': round(total_charge * random.uniform(0.1, 0.3), 2) if status in ['ADJUDICATED', 'PAID'] else None,
                'status': status,
                'payer_claim_number': f"PCN{random.randint(100000000, 999999999)}" if status in ['ADJUDICATED', 'PAID'] else None,
                'billing_provider_id': self._get_random_id('providers'),
                'rendering_provider_id': self._get_random_id('providers'),
                'facility_code': random.choice(['11', '21', '22', '23']),
                'place_of_service': random.choice(['11', '21', '22', '23']),
                'is_active': True,
                'created_at': service_date,
            })
        self._cache_ids('claims', [r['claim_id'] for r in records])
        return records

    def generate_claim_items(self, count: int) -> List[Dict[str, Any]]:
        """Generate claim line item records."""
        records = []
        for i in range(count):
            service_date = self._random_datetime(180)
            charge = round(random.uniform(50, 1000), 2)
            records.append({
                'item_id': i + 1,
                'claim_id': self._get_random_id('claims'),
                'line_number': (i % 5) + 1,
                'service_date': service_date,
                'procedure_code': self.fake.cpt_code(),
                'modifiers': random.choice(['25', '59', '76', None]),
                'diagnosis_codes': self.fake.icd10_code(),
                'quantity': random.randint(1, 3),
                'charge_amount': charge,
                'allowed_amount': round(charge * random.uniform(0.5, 0.9), 2) if random.random() > 0.3 else None,
                'paid_amount': round(charge * random.uniform(0.3, 0.8), 2) if random.random() > 0.4 else None,
                'adjustment_amount': round(charge * random.uniform(0.1, 0.3), 2) if random.random() > 0.5 else None,
                'adjustment_reason': random.choice(['CO-45', 'PR-1', 'CO-97', None]),
                'patient_amount': round(charge * random.uniform(0.1, 0.2), 2) if random.random() > 0.5 else None,
                'status': random.choice(['PENDING', 'PAID', 'DENIED', 'ADJUSTED']),
                'created_at': service_date,
            })
        return records

    def generate_claim_status_history(self, count: int) -> List[Dict[str, Any]]:
        """Generate claim status history records."""
        statuses = ['SUBMITTED', 'PENDING', 'IN_REVIEW', 'ADJUDICATED', 'PAID', 'DENIED', 'APPEALED']
        records = []
        for i in range(count):
            status_date = self._random_datetime(180)
            records.append({
                'history_id': i + 1,
                'claim_id': self._get_random_id('claims'),
                'status': random.choice(statuses),
                'status_date': status_date,
                'reason': random.choice(['Processing complete', 'Awaiting information', 'Under review', None]),
                'notes': self.fake.sentence() if random.random() > 0.5 else None,
                'user_id': self._get_random_id('users') if random.random() > 0.5 else None,
            })
        return records

    def generate_insurance_payments(self, count: int) -> List[Dict[str, Any]]:
        """Generate insurance payment records."""
        records = []
        for i in range(count):
            payment_date = self._random_datetime(180)
            payment_amount = round(random.uniform(100, 3000), 2)
            records.append({
                'payment_id': i + 1,
                'claim_id': self._get_random_id('claims'),
                'payer_id': random.choice(['BCBS', 'AETNA', 'CIGNA', 'UHC', 'HUMANA']),
                'check_number': f"CHK{random.randint(100000, 999999)}" if random.random() > 0.3 else None,
                'check_date': payment_date - timedelta(days=random.randint(1, 5)) if random.random() > 0.3 else None,
                'payment_date': payment_date,
                'payment_amount': payment_amount,
                'adjustment_amount': round(payment_amount * random.uniform(0.05, 0.2), 2) if random.random() > 0.5 else None,
                'era_file': f"/era/835_{self.fake.uuid4()}.edi" if random.random() > 0.5 else None,
                'processed_date': payment_date + timedelta(days=random.randint(1, 3)),
                'created_at': payment_date,
            })
        return records

    def generate_health_invoices(self, count: int) -> List[Dict[str, Any]]:
        """Generate health invoice records with unique invoice_number."""
        used_invoice_numbers = set()
        records = []
        for i in range(count):
            # Generate unique invoice_number
            invoice_number = f"INV{i + 1:08d}"
            if invoice_number in used_invoice_numbers:
                continue
            used_invoice_numbers.add(invoice_number)

            invoice_date = self._random_datetime(90)
            total_charges = round(random.uniform(100, 2000), 2)
            insurance_paid = round(total_charges * random.uniform(0.5, 0.8), 2) if random.random() > 0.3 else 0
            adjustments = round(total_charges * random.uniform(0.05, 0.15), 2) if random.random() > 0.5 else 0
            patient_paid = round(random.uniform(0, total_charges - insurance_paid - adjustments), 2) if random.random() > 0.4 else 0
            balance = round(total_charges - insurance_paid - adjustments - patient_paid, 2)
            records.append({
                'invoice_id': i + 1,
                'patient_id': self._get_random_id('patients'),
                'invoice_number': invoice_number,
                'invoice_date': invoice_date,
                'due_date': invoice_date + timedelta(days=30),
                'total_charges': total_charges,
                'insurance_paid': insurance_paid,
                'adjustments': adjustments,
                'patient_paid': patient_paid,
                'balance_due': balance,
                'status': 'PAID' if balance <= 0 else random.choice(['OPEN', 'PAST_DUE', 'IN_COLLECTIONS']),
                'is_active': True,
                'created_at': invoice_date,
            })
        self._cache_ids('health_invoices', [r['invoice_id'] for r in records])
        return records

    def generate_health_statements(self, count: int) -> List[Dict[str, Any]]:
        """Generate health statement records."""
        records = []
        for i in range(count):
            statement_date = self._random_date(90)
            previous_balance = round(random.uniform(0, 500), 2)
            new_charges = round(random.uniform(100, 1000), 2)
            payments = round(random.uniform(0, previous_balance + new_charges * 0.5), 2)
            adjustments = round(random.uniform(0, 100), 2)
            current_balance = round(previous_balance + new_charges - payments - adjustments, 2)
            records.append({
                'statement_id': i + 1,
                'patient_id': self._get_random_id('patients'),
                'statement_date': statement_date,
                'period_start': statement_date - timedelta(days=30),
                'period_end': statement_date,
                'previous_balance': previous_balance,
                'new_charges': new_charges,
                'payments_received': payments,
                'adjustments': adjustments,
                'current_balance': current_balance,
                'amount_due': round(current_balance, 2) if current_balance > 0 else 0,
                'due_date': statement_date + timedelta(days=30),
                'sent_date': statement_date + timedelta(days=random.randint(1, 5)),
                'delivery_method': random.choice(['EMAIL', 'MAIL', 'PORTAL']),
                'created_at': self._random_datetime(90),
            })
        self._cache_ids('health_statements', [r['statement_id'] for r in records])
        return records

    def generate_health_payment_plans(self, count: int) -> List[Dict[str, Any]]:
        """Generate health payment plan records."""
        records = []
        for i in range(count):
            start_date = self._random_datetime(180)
            total_balance = round(random.uniform(500, 5000), 2)
            num_payments = random.choice([3, 6, 12, 18, 24])
            monthly_amount = round(total_balance / num_payments, 2)
            remaining = round(total_balance * random.uniform(0.3, 1.0), 2)
            records.append({
                'plan_id': i + 1,
                'patient_id': self._get_random_id('patients'),
                'total_balance': total_balance,
                'monthly_amount': monthly_amount,
                'number_of_payments': num_payments,
                'start_date': start_date,
                'end_date': start_date + timedelta(days=30 * num_payments),
                'remaining_balance': remaining,
                'status': 'COMPLETED' if remaining == 0 else random.choice(['ACTIVE', 'DELINQUENT', 'CANCELLED']),
                'payment_day': random.randint(1, 28),
                'is_active': remaining > 0,
                'created_at': start_date,
            })
        return records

    def generate_patient_payments_health(self, count: int) -> List[Dict[str, Any]]:
        """Generate patient payment records for healthcare."""
        payment_methods = ['CASH', 'CHECK', 'CREDIT_CARD', 'DEBIT_CARD', 'HSA', 'FSA']
        records = []
        for i in range(count):
            payment_date = self._random_datetime(180)
            records.append({
                'payment_id': i + 1,
                'patient_id': self._get_random_id('patients'),
                'claim_id': self._get_random_id('claims') if random.random() > 0.5 else None,
                'statement_id': self._get_random_id('health_statements') if random.random() > 0.5 else None,
                'payment_date': payment_date,
                'payment_amount': round(random.uniform(25, 500), 2),
                'payment_method': random.choice(payment_methods),
                'reference_number': f"REF{random.randint(100000, 999999)}",
                'applied_to': random.choice(['COPAY', 'DEDUCTIBLE', 'COINSURANCE', 'BALANCE']),
                'processed_by': self._get_random_id('users') if random.random() > 0.5 else None,
                'notes': self.fake.sentence() if random.random() > 0.7 else None,
                'created_at': payment_date,
            })
        return records

    def generate_charge_master(self, count: int) -> List[Dict[str, Any]]:
        """Generate charge master records."""
        departments = ['LAB', 'RADIOLOGY', 'PHARMACY', 'SURGERY', 'EMERGENCY', 'OUTPATIENT']
        records = []
        for i in range(count):
            standard_charge = round(random.uniform(50, 5000), 2)
            records.append({
                'charge_id': i + 1,
                'code_id': self._get_random_id('billing_codes') if 'billing_codes' in self._id_cache else (i % 100) + 1,
                'description': self.fake.procedure(),
                'department': random.choice(departments),
                'revenue_code': str(random.randint(100, 999)),
                'standard_charge': standard_charge,
                'cash_price': round(standard_charge * random.uniform(0.4, 0.6), 2),
                'minimum_negotiated': round(standard_charge * random.uniform(0.3, 0.5), 2),
                'maximum_negotiated': round(standard_charge * random.uniform(0.7, 0.95), 2),
                'effective_date': self._random_date(365),
                'end_date': self._random_date(30, -365) if random.random() > 0.8 else None,
                'is_active': True,
                'created_at': self._random_datetime(365),
            })
        return records

    def generate_clinical_trials(self, count: int = 50) -> List[Dict[str, Any]]:
        """Generate clinical trial records with unique trial_number."""
        phases = ['PHASE_1', 'PHASE_2', 'PHASE_3', 'PHASE_4']
        statuses = ['RECRUITING', 'ACTIVE', 'COMPLETED', 'SUSPENDED', 'TERMINATED']
        used_trial_numbers = set()
        records = []
        for i in range(count):
            # Generate unique trial_number
            trial_number = f"NCT{i + 1:08d}"
            if trial_number in used_trial_numbers:
                continue
            used_trial_numbers.add(trial_number)

            start_date = self._random_date(365 * 3)
            records.append({
                'trial_id': i + 1,
                'trial_number': trial_number,
                'trial_name': f"Study of {random.choice(['Drug', 'Device', 'Treatment'])} for {self.fake.diagnosis()}",
                'sponsor': random.choice(['Pfizer', 'Merck', 'Johnson & Johnson', 'Novartis', 'Roche', 'NIH']),
                'phase': random.choice(phases),
                'status': random.choice(statuses),
                'start_date': start_date,
                'end_date': start_date + timedelta(days=random.randint(365, 365 * 5)) if random.random() > 0.5 else None,
                'description': self.fake.paragraph(),
                'eligibility_criteria': self.fake.paragraph(),
                'principal_investigator_id': self._get_random_id('providers'),
                'target_enrollment': random.randint(50, 500),
                'current_enrollment': random.randint(0, 300),
                'is_active': True,
                'created_at': self._random_datetime(365 * 2),
            })
        self._cache_ids('clinical_trials', [r['trial_id'] for r in records])
        return records

    def generate_trial_participants(self, count: int) -> List[Dict[str, Any]]:
        """Generate trial participant records."""
        statuses = ['SCREENING', 'ENROLLED', 'ACTIVE', 'COMPLETED', 'WITHDRAWN', 'SCREEN_FAIL']
        records = []
        for i in range(count):
            enrollment_date = self._random_datetime(365)
            status = random.choice(statuses)
            records.append({
                'participant_id': i + 1,
                'trial_id': self._get_random_id('clinical_trials'),
                'patient_id': self._get_random_id('patients'),
                'enrollment_date': enrollment_date,
                'randomization_date': enrollment_date + timedelta(days=random.randint(1, 14)) if status in ['ENROLLED', 'ACTIVE', 'COMPLETED'] else None,
                'arm': random.choice(['TREATMENT', 'PLACEBO', 'CONTROL', None]),
                'status': status,
                'withdrawal_date': enrollment_date + timedelta(days=random.randint(30, 180)) if status == 'WITHDRAWN' else None,
                'withdrawal_reason': random.choice(['Adverse event', 'Lost to follow-up', 'Patient request', 'Protocol violation']) if status == 'WITHDRAWN' else None,
                'consent_date': enrollment_date - timedelta(days=random.randint(1, 7)),
                'consent_version': f"v{random.randint(1, 3)}.0",
                'is_active': status in ['SCREENING', 'ENROLLED', 'ACTIVE'],
                'created_at': enrollment_date,
            })
        return records

    def generate_outcome_tracking(self, count: int) -> List[Dict[str, Any]]:
        """Generate outcome tracking records."""
        outcome_types = ['PAIN_SCORE', 'QUALITY_OF_LIFE', 'FUNCTIONAL_STATUS', 'SYMPTOM_SEVERITY', 'PATIENT_SATISFACTION']
        score_types = ['NUMERIC', 'VAS', 'LIKERT', 'PERCENTAGE']
        records = []
        for i in range(count):
            outcome_date = self._random_datetime(180)
            records.append({
                'outcome_id': i + 1,
                'patient_id': self._get_random_id('patients'),
                'record_id': self._get_random_id('medical_records') if random.random() > 0.3 else None,
                'outcome_type': random.choice(outcome_types),
                'outcome_date': outcome_date,
                'score': round(random.uniform(0, 100), 2),
                'score_type': random.choice(score_types),
                'baseline_score': round(random.uniform(0, 100), 2) if random.random() > 0.5 else None,
                'target_score': round(random.uniform(50, 100), 2) if random.random() > 0.5 else None,
                'notes': self.fake.sentence() if random.random() > 0.5 else None,
                'measured_by': self._get_random_id('providers') if random.random() > 0.3 else None,
                'created_at': outcome_date,
            })
        return records

    def generate_telehealth_sessions(self, count: int) -> List[Dict[str, Any]]:
        """Generate telehealth session records."""
        platforms = ['Zoom', 'Doxy.me', 'Teladoc', 'Amwell', 'Microsoft Teams']
        records = []
        for i in range(count):
            session_start = self._random_datetime(90)
            duration = random.randint(10, 60)
            records.append({
                'session_id': i + 1,
                'appointment_id': self._get_random_id('appointments'),
                'platform': random.choice(platforms),
                'session_url': f"https://telehealth.example.com/session/{self.fake.uuid4()}",
                'patient_joined': session_start - timedelta(minutes=random.randint(1, 5)) if random.random() > 0.1 else None,
                'provider_joined': session_start if random.random() > 0.05 else None,
                'session_start': session_start,
                'session_end': session_start + timedelta(minutes=duration),
                'duration_minutes': duration,
                'technical_issues': random.random() > 0.9,
                'issue_notes': 'Audio/video quality issues' if random.random() > 0.95 else None,
                'recording_url': f"/recordings/{self.fake.uuid4()}.mp4" if random.random() > 0.8 else None,
                'is_active': True,
                'created_at': session_start,
            })
        return records

    def generate_provider_schedules(self, count: int) -> List[Dict[str, Any]]:
        """Generate provider schedule records."""
        records = []
        for i in range(count):
            effective_date = self._random_date(365)
            records.append({
                'schedule_id': i + 1,
                'provider_id': self._get_random_id('providers'),
                'day_of_week': random.randint(0, 6),
                'start_time': datetime.strptime(random.choice(['08:00', '09:00', '10:00']), '%H:%M'),
                'end_time': datetime.strptime(random.choice(['16:00', '17:00', '18:00']), '%H:%M'),
                'location': random.choice(['Main Office', 'Satellite Clinic', 'Hospital']),
                'room_id': self._get_random_id('rooms') if random.random() > 0.5 else None,
                'effective_date': effective_date,
                'end_date': effective_date + timedelta(days=random.randint(90, 365)) if random.random() > 0.7 else None,
                'appointment_types': random.choice(['NEW,FUP', 'ALL', 'PROC', None]),
                'is_active': True,
                'created_at': self._random_datetime(365),
            })
        return records

    def generate_quality_measures(self, count: int) -> List[Dict[str, Any]]:
        """Generate quality measure records."""
        measure_codes = ['CMS122', 'CMS127', 'CMS130', 'CMS138', 'CMS139', 'CMS165', 'CMS166']
        measure_names = [
            'Diabetes: Hemoglobin A1c Poor Control',
            'Pneumococcal Vaccination Status',
            'Colorectal Cancer Screening',
            'Preventive Care: Tobacco Use',
            'Falls: Screening for Future Fall Risk',
            'Controlling High Blood Pressure',
            'Use of Imaging Studies for Low Back Pain'
        ]
        records = []
        for i in range(count):
            idx = i % len(measure_codes)
            records.append({
                'measure_id': i + 1,
                'patient_id': self._get_random_id('patients'),
                'measure_code': measure_codes[idx],
                'measure_name': measure_names[idx],
                'measure_period': f"{random.randint(2022, 2024)}",
                'numerator': random.random() > 0.3,
                'denominator': True,
                'exclusion': random.random() > 0.9,
                'exception': random.random() > 0.95,
                'performance_met': random.random() > 0.4,
                'calculated_date': self._random_datetime(90),
                'provider_id': self._get_random_id('providers') if random.random() > 0.3 else None,
                'created_at': self._random_datetime(365),
            })
        return records

    def generate_social_history(self, count: int) -> List[Dict[str, Any]]:
        """Generate social history records."""
        smoking_statuses = ['NEVER', 'FORMER', 'CURRENT', 'UNKNOWN']
        alcohol_use = ['NONE', 'OCCASIONAL', 'MODERATE', 'HEAVY', 'UNKNOWN']
        records = []
        for i in range(count):
            smoking = random.choice(smoking_statuses)
            records.append({
                'history_id': i + 1,
                'patient_id': self._get_random_id('patients'),
                'smoking_status': smoking,
                'tobacco_use': 'YES' if smoking == 'CURRENT' else 'NO',
                'packs_per_day': round(random.uniform(0.5, 2), 1) if smoking == 'CURRENT' else None,
                'years_smoked': random.randint(5, 40) if smoking in ['CURRENT', 'FORMER'] else None,
                'quit_date': self._random_date(365 * 10) if smoking == 'FORMER' else None,
                'alcohol_use': random.choice(alcohol_use),
                'drinks_per_week': random.randint(0, 20) if random.random() > 0.3 else None,
                'drug_use': random.choice(['NONE', 'MARIJUANA', 'OTHER', None]),
                'occupation': self.fake.job(),
                'education_level': random.choice(['HIGH_SCHOOL', 'COLLEGE', 'GRADUATE', 'OTHER']),
                'living_situation': random.choice(['ALONE', 'WITH_FAMILY', 'ASSISTED', 'OTHER']),
                'exercise_frequency': random.choice(['DAILY', 'WEEKLY', 'MONTHLY', 'NEVER']),
                'diet': random.choice(['REGULAR', 'VEGETARIAN', 'DIABETIC', 'LOW_SODIUM']),
                'sexual_activity': random.choice(['ACTIVE', 'INACTIVE', 'NOT_APPLICABLE', None]),
                'is_active': True,
                'created_at': self._random_datetime(365),
            })
        return records

    def generate_surgical_history(self, count: int) -> List[Dict[str, Any]]:
        """Generate surgical history records."""
        procedures = [
            'Appendectomy', 'Cholecystectomy', 'Hernia Repair', 'Cesarean Section',
            'Knee Replacement', 'Hip Replacement', 'Coronary Bypass', 'Hysterectomy',
            'Tonsillectomy', 'Cataract Surgery'
        ]
        records = []
        for i in range(count):
            records.append({
                'history_id': i + 1,
                'patient_id': self._get_random_id('patients'),
                'procedure_name': random.choice(procedures),
                'procedure_code': self.fake.cpt_code() if random.random() > 0.5 else None,
                'procedure_date': self._random_date(365 * 20) if random.random() > 0.3 else None,
                'surgeon': f"Dr. {self.fake.last_name()}" if random.random() > 0.5 else None,
                'facility': random.choice(['City Hospital', 'Surgery Center', 'University Medical', None]),
                'notes': self.fake.sentence() if random.random() > 0.5 else None,
                'complications': random.choice(['None', 'Infection', 'Bleeding', 'Other', None]),
                'source': random.choice(['SELF_REPORTED', 'MEDICAL_RECORD', 'IMPORTED']),
                'created_at': self._random_datetime(365),
            })
        return records

    def generate_write_offs(self, count: int) -> List[Dict[str, Any]]:
        """Generate write-off records."""
        reason_codes = ['BAD_DEBT', 'CHARITY', 'CONTRACTUAL', 'ADMINISTRATIVE', 'TIMELY_FILING']
        records = []
        for i in range(count):
            writeoff_date = self._random_datetime(365)
            records.append({
                'writeoff_id': i + 1,
                'patient_id': self._get_random_id('patients') if random.random() > 0.3 else None,
                'claim_id': self._get_random_id('claims') if random.random() > 0.5 else None,
                'writeoff_date': writeoff_date,
                'amount': round(random.uniform(50, 1000), 2),
                'reason_code': random.choice(reason_codes),
                'reason_description': f"Write-off due to {random.choice(['patient hardship', 'insurance denial', 'timely filing', 'contractual adjustment'])}",
                'approved_by': self._get_random_id('users') if random.random() > 0.5 else None,
                'notes': self.fake.sentence() if random.random() > 0.5 else None,
                'is_active': True,
                'created_at': writeoff_date,
            })
        return records

    def generate_collections(self, count: int) -> List[Dict[str, Any]]:
        """Generate collections records."""
        statuses = ['ACTIVE', 'PAID', 'SETTLED', 'CLOSED', 'DISPUTED']
        records = []
        for i in range(count):
            original_balance = round(random.uniform(200, 5000), 2)
            current_balance = round(original_balance * random.uniform(0, 1), 2)
            status = random.choice(statuses)
            records.append({
                'collection_id': i + 1,
                'patient_id': self._get_random_id('patients'),
                'account_number': f"COLL{i + 1:08d}",
                'original_balance': original_balance,
                'current_balance': current_balance,
                'placed_date': self._random_date(365),
                'agency_name': random.choice(['Collections Plus', 'Debt Recovery Inc', 'Financial Services']),
                'agency_account': f"AGY{random.randint(100, 999)}",
                'status': status,
                'last_payment_date': self._random_date(90) if current_balance < original_balance else None,
                'payments_received': round(original_balance - current_balance, 2),
                'settlement_amount': round(original_balance * random.uniform(0.4, 0.8), 2) if status == 'SETTLED' else None,
                'closed_date': self._random_date(30) if status in ['PAID', 'SETTLED', 'CLOSED'] else None,
                'created_by': self._get_random_id('users'),
                'updated_by': self._get_random_id('users') if random.random() > 0.5 else None,
                'is_active': status == 'ACTIVE',
                'created_at': self._random_datetime(365),
            })
        return records

    def generate_regulatory_reports(self, count: int = 50) -> List[Dict[str, Any]]:
        """Generate regulatory report records."""
        report_types = ['CMS_QUALITY', 'PQRS', 'MIPS', 'HEDIS', 'STATE_IMMUNIZATION']
        statuses = ['DRAFT', 'SUBMITTED', 'ACCEPTED', 'REJECTED', 'PENDING']
        records = []
        for i in range(count):
            due_date = self._random_date(90, -90)
            records.append({
                'report_id': i + 1,
                'report_type': random.choice(report_types),
                'reporting_period_start': due_date - timedelta(days=365),
                'reporting_period_end': due_date - timedelta(days=1),
                'due_date': due_date,
                'submission_date': due_date - timedelta(days=random.randint(1, 30)) if random.random() > 0.3 else None,
                'confirmation_number': f"CONF{random.randint(100000, 999999)}" if random.random() > 0.5 else None,
                'status': random.choice(statuses),
                'prepared_by': self._get_random_id('users') if random.random() > 0.5 else None,
                'reviewed_by': self._get_random_id('users') if random.random() > 0.5 else None,
                'file_path': f"/reports/{self.fake.uuid4()}.pdf" if random.random() > 0.5 else None,
                'created_at': self._random_datetime(365),
            })
        return records

    # =========================================================================
    # Additional Params Generation (not tied to specific seed tables)
    # =========================================================================

    def generate_date_range_params(self, count: int = None):
        """Generate date range parameters for search queries.

        These are generated based on realistic date ranges, not tied to specific records.
        """
        count = count or self.config.query_generation.param_rows_per_query
        for _ in range(count):
            end_date = datetime.now() - timedelta(days=random.randint(0, 30))
            start_date = end_date - timedelta(days=random.randint(7, 90))
            self.params.add('date_ranges', {
                'start_date': start_date.strftime('%Y-%m-%d'),
                'end_date': end_date.strftime('%Y-%m-%d'),
            })

    def generate_ddl_test_table_params(self, db_type: str = 'postgresql', count: int = 100):
        """Generate params for DDL test tables.

        CRITICAL: DDL operations only on ddl_test_NNN tables, never on data tables.
        Output file: ddl_params.csv with columns: table_name, column_name, column_type

        Args:
            db_type: Database type for vendor-specific type mapping
            count: Number of params to generate
        """
        # Get vendor-specific column types using SQLAlchemy dialect
        column_types = get_cached_ddl_types(db_type)

        for i in range(count):
            table_num = (i % 20) + 1  # Cycle through 20 test tables
            # Use 'ddl_params' to match JMX CSV data set config
            self.params.add('ddl_params', {
                'table_name': f"ddl_test_{table_num:03d}",
                'column_name': f"test_field_{i:03d}",
                'column_type': random.choice(column_types),
            })

    def generate_temp_user_params(self, count: int = 50):
        """Generate params for temp users (created/dropped during load).

        CRITICAL: Only temp users (load_user_NNN) are created/dropped during test.
        Config users (test_user_1, etc.) are permanent and never dropped.
        Output file: new_users.csv with columns: new_username, new_password
        """
        for i in range(count):
            # Use 'new_users' to match JMX CSV data set config
            # Column names: new_username, new_password to match JMX variables
            self.params.add('new_users', {
                'new_username': f"load_user_{i + 1:03d}",
                'new_password': f"LoadTest@{i + 1:03d}",
            })

    def generate_grant_params(self, count: int = 100):
        """Generate GRANT/REVOKE params using actual data tables and config users.

        Output file: grant_params.csv with columns: grant_table, grant_user
        """
        # Use actual data tables for GRANT operations
        tables = list(self._id_cache.keys())[:10] if self._id_cache else [
            'customers', 'orders', 'products', 'accounts', 'patients'
        ]
        # Config users are permanent - grants to them are fine
        config_users = [u.username for u in self.config.test_users]

        for _ in range(count):
            # Use 'grant_params' to match JMX CSV data set config
            # Column names: grant_table, grant_user to match JMX variables
            self.params.add('grant_params', {
                'grant_table': random.choice(tables),
                'grant_user': random.choice(config_users),
            })

    def generate_user_credentials_params(self):
        """Generate user credentials for config users (permanent users)."""
        for user in self.config.test_users:
            self.params.add('user_credentials', {
                'username': user.username,
                'password': user.password,
                'role': user.role,
            })

    # =========================================================================
    # SQL Generation
    # =========================================================================

    # SQL Server reserved keywords that need escaping
    MSSQL_RESERVED_KEYWORDS = {
        'plan', 'user', 'key', 'order', 'group', 'index', 'table', 'column',
        'view', 'select', 'insert', 'update', 'delete', 'from', 'where',
        'join', 'on', 'as', 'and', 'or', 'not', 'null', 'true', 'false',
        'check', 'constraint', 'primary', 'foreign', 'references', 'default',
        'identity', 'value', 'values', 'set', 'into', 'create', 'alter', 'drop',
        'grant', 'revoke', 'deny', 'exec', 'execute', 'procedure', 'function',
        'trigger', 'database', 'schema', 'transaction', 'commit', 'rollback',
        'begin', 'end', 'if', 'else', 'case', 'when', 'then', 'exists', 'in',
        'between', 'like', 'is', 'by', 'asc', 'desc', 'top', 'distinct',
        'having', 'union', 'all', 'any', 'some', 'outer', 'inner', 'left',
        'right', 'full', 'cross', 'natural', 'using', 'current', 'date', 'time',
        'timestamp', 'session', 'system', 'role', 'authorization', 'level'
    }

    def _quote_column(self, col_name: str, db_type: str) -> str:
        """Quote column name if it's a reserved keyword.

        Args:
            col_name: Column name
            db_type: Database type

        Returns:
            Quoted column name if needed
        """
        if db_type == 'mssql' and col_name.lower() in self.MSSQL_RESERVED_KEYWORDS:
            return f"[{col_name}]"
        elif db_type in ('postgresql', 'oracle') and col_name.lower() in self.MSSQL_RESERVED_KEYWORDS:
            return f'"{col_name}"'
        return col_name

    def generate_insert_sql(self, table_name: str, records: List[Dict[str, Any]], db_type: str = 'postgresql') -> str:
        """Generate INSERT SQL statements for records.

        Args:
            table_name: Name of the table
            records: List of record dictionaries
            db_type: Database type

        Returns:
            SQL string with INSERT statements
        """
        if not records:
            return f"-- No records for {table_name}\n"

        statements = []
        statements.append(f"-- Insert data for {table_name}")
        statements.append(f"-- {len(records)} records\n")

        columns = list(records[0].keys())
        # Quote reserved keywords
        quoted_columns = [self._quote_column(col, db_type) for col in columns]
        col_list = ", ".join(quoted_columns)

        # For SQL Server, enable IDENTITY_INSERT if table has identity column
        # Common identity column patterns: *_id as first column, or just 'id'
        has_identity = db_type == 'mssql' and columns and (columns[0].endswith('_id') or columns[0] == 'id')
        if has_identity:
            statements.append(f"SET IDENTITY_INSERT {table_name} ON;")

        for record in records:
            values = [self._format_value(record[col], db_type) for col in columns]
            val_list = ", ".join(values)
            statements.append(f"INSERT INTO {table_name} ({col_list}) VALUES ({val_list});")

        if has_identity:
            statements.append(f"SET IDENTITY_INSERT {table_name} OFF;")

        statements.append("")
        return "\n".join(statements)

    def generate_all_seed_data(self, db_type: str, output_dir: str) -> Dict[str, str]:
        """Generate seed data AND parameter CSV files in a SINGLE PASS.

        CRITICAL: This implements single-pass generation where params contain
        ACTUAL values from the seed data. Params are collected as each table
        is generated, ensuring JMeter references data that exists in the DB.

        Args:
            db_type: Database type
            output_dir: Output directory path

        Returns:
            Dictionary of file paths to content
        """
        output_path = Path(output_dir)
        seed_path = output_path / "seed"
        seed_path.mkdir(parents=True, exist_ok=True)
        batched_path = seed_path / "seed_data_batched"
        batched_path.mkdir(parents=True, exist_ok=True)
        params_path = output_path / "params"
        params_path.mkdir(parents=True, exist_ok=True)

        files = {}
        all_sql = []
        batch_num = 1

        # Ensure confidential data is loaded
        self.conf_loader.load()

        print(f"Generating seed data + params for {db_type} (SINGLE-PASS)...")

        # =====================================================================
        # CLEANUP: Delete existing data before inserting (reverse dependency order)
        # Must include ALL tables being seeded
        # =====================================================================
        cleanup_tables = [
            # Banking Domain - Transaction detail tables
            'recurring_transactions', 'check_deposits', 'pos_transactions', 'atm_transactions',
            'transaction_fees', 'transaction_disputes',
            # Banking Domain - Compliance tables
            'sanctions_screening', 'kyc_documents', 'suspicious_activity_reports', 'aml_checks',
            'compliance_cases',
            # Banking Domain - Transfer tables
            'standing_orders', 'scheduled_payments', 'wire_transfers', 'ach_transfers', 'transfers',
            # Banking Domain - Loan tables
            'guarantors', 'collateral', 'loan_refinancing', 'loan_documents', 'loan_fees',
            'loan_status_history', 'loan_schedules', 'loan_payments', 'loan_applications', 'loans',
            # Banking Domain - Card tables
            'card_disputes', 'card_controls', 'card_limits', 'card_reward_redemptions', 'card_rewards',
            'card_statements', 'card_transactions', 'virtual_cards', 'debit_cards',
            # Banking Domain - Account relationship tables
            'account_beneficiaries', 'account_alerts', 'account_statements', 'account_limits',
            'account_holders',
            # Banking Domain - Account sub-types
            'certificates_of_deposit', 'joint_accounts', 'money_market_accounts', 'savings_accounts',
            'checking_accounts',
            # Banking Domain - Transaction categories and tags
            'bank_transaction_tags', 'bank_transaction_categories',
            # Banking Domain - User and session tables
            'bank_login_history', 'trusted_devices', 'security_questions', 'bank_user_sessions',
            'bank_users',
            # Banking Domain - Reference tables
            'billing_codes', 'loan_officers', 'loan_types',
            # Healthcare Domain - Provider and quality tables
            'regulatory_reports', 'quality_measures', 'provider_schedules',
            # Healthcare Domain - Clinical trials tables
            'outcome_tracking', 'trial_participants', 'clinical_trials',
            # Healthcare Domain - Billing and claims tables
            'collections', 'write_offs', 'charge_master', 'patient_payments_health',
            'health_payment_plans', 'health_statements', 'health_invoices',
            'insurance_payments', 'claim_status_history', 'claim_items', 'claims',
            # Healthcare Domain - Care team and referrals
            'referrals', 'care_team_members', 'care_teams',
            # Healthcare Domain - Notes and treatment plans
            'treatment_plans', 'progress_notes', 'clinical_notes',
            # Healthcare Domain - Radiology and pathology
            'pathology_reports', 'radiology_results', 'radiology_orders',
            # Healthcare Domain - Lab tables
            'lab_results', 'lab_orders',
            # Healthcare Domain - Prescriptions and procedures
            'prescription_fills', 'prescriptions', 'procedures',
            # Healthcare Domain - Vitals tables
            'vital_readings', 'vitals',
            # Healthcare Domain - Appointment tables
            'telehealth_sessions', 'waiting_lists', 'no_shows', 'cancellations',
            'appointment_reminders', 'appointments',
            # Healthcare Domain - Patient child tables
            'surgical_history', 'social_history', 'patient_communication_log',
            'patient_immunizations', 'patient_documents', 'patient_consents',
            'condition_history', 'family_history', 'emergency_contacts', 'patient_contacts',
            'patient_medications', 'patient_allergies', 'patient_preferences',
            'patient_portal_users', 'patient_insurance',
            # Healthcare Domain - Reference tables
            'appointment_types', 'rooms',
            # E-Commerce analytics/tracking tables
            'customer_lifetime_value', 'abandoned_carts', 'search_queries', 'product_performance',
            'sales_daily', 'conversion_events', 'page_views', 'recommendation_clicks', 'recommendations',
            # E-Commerce marketing tables
            'wishlist_items', 'wishlists', 'coupon_usage', 'coupons', 'promotions', 'campaigns',
            # E-Commerce payment tables
            'wallets', 'payment_plan_installments', 'payment_plans', 'gift_card_transactions', 'gift_cards',
            'invoice_items', 'invoices', 'refunds', 'transactions', 'payment_methods',
            # E-Commerce order child tables
            'fulfillment_items', 'order_fulfillment', 'saved_for_later', 'cart_items', 'shopping_carts',
            'order_discounts', 'order_notes', 'return_items', 'returns', 'shipment_items', 'shipments',
            'order_status_history', 'order_items',
            # E-Commerce product child tables
            'product_bundle_items', 'product_bundles', 'product_variant_attributes', 'product_variants',
            'product_attribute_values', 'product_attributes', 'inventory', 'product_reviews', 'product_images',
            # E-Commerce customer child tables
            'customer_tag_assignments', 'customer_tags', 'customer_notes', 'customer_segment_members',
            'customer_segments', 'customer_preferences', 'customer_addresses',
            # Audit/log tables
            'notifications', 'error_logs', 'system_events', 'access_logs', 'data_changes', 'audit_logs',
            'login_attempts', 'password_history', 'api_keys', 'sessions',
            # Junction/assignment tables
            'role_permissions', 'user_roles',
            # Transaction/child tables (core)
            'diagnoses', 'medical_records', 'bank_transactions', 'credit_cards', 'orders',
            # Entity tables
            'patients', 'accounts', 'products', 'customers', 'addresses',
            # Reference/lookup tables
            'order_tags', 'providers', 'brands', 'users', 'cities', 'states',
            'categories', 'account_types', 'transaction_types', 'permissions', 'roles', 'countries',
            'system_config', 'feature_flags',
        ]

        if db_type == 'mssql':
            all_sql.append("-- Disable all FK constraints")
            all_sql.append("EXEC sp_MSforeachtable 'ALTER TABLE ? NOCHECK CONSTRAINT ALL';")
            all_sql.append("GO")
            all_sql.append("")
            all_sql.append("-- Delete existing data in reverse dependency order")
            for table in cleanup_tables:
                all_sql.append(f"DELETE FROM {table};")
            all_sql.append("GO")
            all_sql.append("")
            all_sql.append("-- Re-enable all FK constraints")
            all_sql.append("EXEC sp_MSforeachtable 'ALTER TABLE ? WITH CHECK CHECK CONSTRAINT ALL';")
            all_sql.append("GO")
            all_sql.append("")
        elif db_type == 'postgresql':
            all_sql.append("-- Truncate tables in reverse dependency order")
            all_sql.append(f"TRUNCATE TABLE {', '.join(cleanup_tables)} CASCADE;")
            all_sql.append("")

        # =====================================================================
        # SINGLE-PASS GENERATION: Seed data + Params collected together
        # =====================================================================

        # Generate in dependency order
        # 1. Reference tables (no dependencies)
        all_sql.append(self.generate_insert_sql('countries', self.generate_countries(), db_type))
        all_sql.append(self.generate_insert_sql('roles', self.generate_roles(), db_type))
        all_sql.append(self.generate_insert_sql('permissions', self.generate_permissions(), db_type))
        all_sql.append(self.generate_insert_sql('categories', self.generate_categories(), db_type))
        all_sql.append(self.generate_insert_sql('account_types', self.generate_account_types(), db_type))
        all_sql.append(self.generate_insert_sql('transaction_types', self.generate_transaction_types(), db_type))
        all_sql.append(self.generate_insert_sql('system_config', self.generate_system_config(), db_type))
        all_sql.append(self.generate_insert_sql('feature_flags', self.generate_feature_flags(), db_type))

        # 2. Address hierarchy (depends on countries)
        all_sql.append(self.generate_insert_sql('states', self.generate_states(), db_type))
        all_sql.append(self.generate_insert_sql('cities', self.generate_cities(), db_type))

        # 3. Primary tables
        all_sql.append(self.generate_insert_sql('users', self.generate_users(min(self.records_per_table, 1000)), db_type))
        all_sql.append(self.generate_insert_sql('brands', self.generate_brands(50), db_type))
        all_sql.append(self.generate_insert_sql('providers', self.generate_providers(200), db_type))

        # 4. Tables depending on users
        all_sql.append(self.generate_insert_sql('addresses', self.generate_addresses(500), db_type))
        all_sql.append(self.generate_insert_sql('user_roles', self.generate_user_roles(500), db_type))
        all_sql.append(self.generate_insert_sql('role_permissions', self.generate_role_permissions(), db_type))
        all_sql.append(self.generate_insert_sql('sessions', self.generate_sessions(500), db_type))
        all_sql.append(self.generate_insert_sql('api_keys', self.generate_api_keys(100), db_type))
        all_sql.append(self.generate_insert_sql('password_history', self.generate_password_history(500), db_type))
        all_sql.append(self.generate_insert_sql('login_attempts', self.generate_login_attempts(1000), db_type))
        all_sql.append(self.generate_insert_sql('notifications', self.generate_notifications(500), db_type))

        # 5. Audit/log tables (depend on users)
        all_sql.append(self.generate_insert_sql('audit_logs', self.generate_audit_logs(1000), db_type))
        all_sql.append(self.generate_insert_sql('data_changes', self.generate_data_changes(500), db_type))
        all_sql.append(self.generate_insert_sql('access_logs', self.generate_access_logs(1000), db_type))
        all_sql.append(self.generate_insert_sql('system_events', self.generate_system_events(500), db_type))
        all_sql.append(self.generate_insert_sql('error_logs', self.generate_error_logs(500), db_type))

        # 6. Main entity tables - params are collected during generation
        count = min(self.records_per_table, 5000)
        all_sql.append(self.generate_insert_sql('customers', self.generate_customers(count), db_type))
        all_sql.append(self.generate_insert_sql('products', self.generate_products(count), db_type))
        all_sql.append(self.generate_insert_sql('accounts', self.generate_accounts(count), db_type))
        all_sql.append(self.generate_insert_sql('patients', self.generate_patients(count), db_type))

        # 7. E-Commerce reference tables
        all_sql.append(self.generate_insert_sql('customer_segments', self.generate_customer_segments(), db_type))
        all_sql.append(self.generate_insert_sql('customer_tags', self.generate_customer_tags(), db_type))
        all_sql.append(self.generate_insert_sql('product_attributes', self.generate_product_attributes(), db_type))
        all_sql.append(self.generate_insert_sql('product_bundles', self.generate_product_bundles(50), db_type))
        all_sql.append(self.generate_insert_sql('order_tags', self.generate_order_tags(), db_type))
        all_sql.append(self.generate_insert_sql('coupons', self.generate_coupons(100), db_type))
        all_sql.append(self.generate_insert_sql('promotions', self.generate_promotions(30), db_type))

        # 8. E-Commerce customer child tables
        all_sql.append(self.generate_insert_sql('customer_addresses', self.generate_customer_addresses(2000), db_type))
        all_sql.append(self.generate_insert_sql('customer_preferences', self.generate_customer_preferences(1000), db_type))
        all_sql.append(self.generate_insert_sql('customer_segment_members', self.generate_customer_segment_members(500), db_type))
        all_sql.append(self.generate_insert_sql('customer_notes', self.generate_customer_notes(500), db_type))
        all_sql.append(self.generate_insert_sql('customer_tag_assignments', self.generate_customer_tag_assignments(500), db_type))

        # 9. E-Commerce product child tables
        all_sql.append(self.generate_insert_sql('product_images', self.generate_product_images(2000), db_type))
        all_sql.append(self.generate_insert_sql('product_reviews', self.generate_product_reviews(1000), db_type))
        all_sql.append(self.generate_insert_sql('inventory', self.generate_inventory(1000), db_type))
        all_sql.append(self.generate_insert_sql('product_attribute_values', self.generate_product_attribute_values(500), db_type))
        all_sql.append(self.generate_insert_sql('product_variants', self.generate_product_variants(500), db_type))
        all_sql.append(self.generate_insert_sql('product_variant_attributes', self.generate_product_variant_attributes(500), db_type))
        all_sql.append(self.generate_insert_sql('product_bundle_items', self.generate_product_bundle_items(150), db_type))

        # 10. Transaction tables - params are collected during generation
        all_sql.append(self.generate_insert_sql('orders', self.generate_orders(count), db_type))
        all_sql.append(self.generate_insert_sql('credit_cards', self.generate_credit_cards(count), db_type))
        all_sql.append(self.generate_insert_sql('bank_transactions', self.generate_bank_transactions(count), db_type))
        all_sql.append(self.generate_insert_sql('medical_records', self.generate_medical_records(count), db_type))
        all_sql.append(self.generate_insert_sql('diagnoses', self.generate_diagnoses(count), db_type))

        # =====================================================================
        # Healthcare Domain Tables
        # =====================================================================
        print("  Generating Healthcare domain tables...")

        # Healthcare reference tables
        all_sql.append(self.generate_insert_sql('rooms', self.generate_rooms(100), db_type))
        all_sql.append(self.generate_insert_sql('appointment_types', self.generate_appointment_types(), db_type))

        # Patient-related tables
        all_sql.append(self.generate_insert_sql('patient_insurance', self.generate_patient_insurance(count), db_type))
        all_sql.append(self.generate_insert_sql('patient_portal_users', self.generate_patient_portal_users(500), db_type))
        all_sql.append(self.generate_insert_sql('patient_preferences', self.generate_patient_preferences(1000), db_type))
        all_sql.append(self.generate_insert_sql('patient_allergies', self.generate_patient_allergies(500), db_type))
        all_sql.append(self.generate_insert_sql('patient_medications', self.generate_patient_medications(1000), db_type))
        all_sql.append(self.generate_insert_sql('patient_contacts', self.generate_patient_contacts(500), db_type))
        all_sql.append(self.generate_insert_sql('emergency_contacts', self.generate_emergency_contacts(500), db_type))
        all_sql.append(self.generate_insert_sql('family_history', self.generate_family_history(500), db_type))
        all_sql.append(self.generate_insert_sql('condition_history', self.generate_condition_history(500), db_type))
        all_sql.append(self.generate_insert_sql('patient_consents', self.generate_patient_consents(500), db_type))
        all_sql.append(self.generate_insert_sql('patient_documents', self.generate_patient_documents(500), db_type))
        all_sql.append(self.generate_insert_sql('patient_immunizations', self.generate_patient_immunizations(500), db_type))
        all_sql.append(self.generate_insert_sql('patient_communication_log', self.generate_patient_communication_log(500), db_type))
        all_sql.append(self.generate_insert_sql('social_history', self.generate_social_history(500), db_type))
        all_sql.append(self.generate_insert_sql('surgical_history', self.generate_surgical_history(500), db_type))

        # Appointment tables
        all_sql.append(self.generate_insert_sql('appointments', self.generate_appointments(count), db_type))
        all_sql.append(self.generate_insert_sql('appointment_reminders', self.generate_appointment_reminders(500), db_type))
        all_sql.append(self.generate_insert_sql('cancellations', self.generate_cancellations(300), db_type))
        all_sql.append(self.generate_insert_sql('no_shows', self.generate_no_shows(200), db_type))
        all_sql.append(self.generate_insert_sql('waiting_lists', self.generate_waiting_lists(200), db_type))
        all_sql.append(self.generate_insert_sql('telehealth_sessions', self.generate_telehealth_sessions(300), db_type))

        # Vitals tables
        all_sql.append(self.generate_insert_sql('vitals', self.generate_vitals(count), db_type))
        all_sql.append(self.generate_insert_sql('vital_readings', self.generate_vital_readings(count * 3), db_type))

        # Procedures and prescriptions
        all_sql.append(self.generate_insert_sql('procedures', self.generate_procedures(count), db_type))
        all_sql.append(self.generate_insert_sql('prescriptions', self.generate_prescriptions(count), db_type))
        all_sql.append(self.generate_insert_sql('prescription_fills', self.generate_prescription_fills(count), db_type))

        # Lab tables
        all_sql.append(self.generate_insert_sql('lab_orders', self.generate_lab_orders(500), db_type))
        all_sql.append(self.generate_insert_sql('lab_results', self.generate_lab_results(1000), db_type))

        # Radiology and pathology tables
        all_sql.append(self.generate_insert_sql('radiology_orders', self.generate_radiology_orders(300), db_type))
        all_sql.append(self.generate_insert_sql('radiology_results', self.generate_radiology_results(300), db_type))
        all_sql.append(self.generate_insert_sql('pathology_reports', self.generate_pathology_reports(200), db_type))

        # Notes and treatment plans
        all_sql.append(self.generate_insert_sql('clinical_notes', self.generate_clinical_notes(500), db_type))
        all_sql.append(self.generate_insert_sql('progress_notes', self.generate_progress_notes(500), db_type))
        all_sql.append(self.generate_insert_sql('treatment_plans', self.generate_treatment_plans(300), db_type))

        # Care team and referrals
        all_sql.append(self.generate_insert_sql('care_teams', self.generate_care_teams(200), db_type))
        all_sql.append(self.generate_insert_sql('care_team_members', self.generate_care_team_members(500), db_type))
        all_sql.append(self.generate_insert_sql('referrals', self.generate_referrals(300), db_type))

        # Claims and billing tables
        all_sql.append(self.generate_insert_sql('claims', self.generate_claims(500), db_type))
        all_sql.append(self.generate_insert_sql('claim_items', self.generate_claim_items(1500), db_type))
        all_sql.append(self.generate_insert_sql('claim_status_history', self.generate_claim_status_history(1000), db_type))
        all_sql.append(self.generate_insert_sql('insurance_payments', self.generate_insurance_payments(400), db_type))
        all_sql.append(self.generate_insert_sql('health_invoices', self.generate_health_invoices(500), db_type))
        all_sql.append(self.generate_insert_sql('health_statements', self.generate_health_statements(500), db_type))
        all_sql.append(self.generate_insert_sql('health_payment_plans', self.generate_health_payment_plans(200), db_type))
        all_sql.append(self.generate_insert_sql('patient_payments_health', self.generate_patient_payments_health(500), db_type))
        all_sql.append(self.generate_insert_sql('charge_master', self.generate_charge_master(200), db_type))
        all_sql.append(self.generate_insert_sql('write_offs', self.generate_write_offs(200), db_type))
        all_sql.append(self.generate_insert_sql('collections', self.generate_collections(100), db_type))

        # Clinical trials
        all_sql.append(self.generate_insert_sql('clinical_trials', self.generate_clinical_trials(50), db_type))
        all_sql.append(self.generate_insert_sql('trial_participants', self.generate_trial_participants(200), db_type))
        all_sql.append(self.generate_insert_sql('outcome_tracking', self.generate_outcome_tracking(500), db_type))

        # Provider and quality
        all_sql.append(self.generate_insert_sql('provider_schedules', self.generate_provider_schedules(300), db_type))
        all_sql.append(self.generate_insert_sql('quality_measures', self.generate_quality_measures(500), db_type))
        all_sql.append(self.generate_insert_sql('regulatory_reports', self.generate_regulatory_reports(50), db_type))

        # 11. E-Commerce order child tables
        all_sql.append(self.generate_insert_sql('order_items', self.generate_order_items(3000), db_type))
        all_sql.append(self.generate_insert_sql('order_status_history', self.generate_order_status_history(2000), db_type))
        all_sql.append(self.generate_insert_sql('shipments', self.generate_shipments(800), db_type))
        all_sql.append(self.generate_insert_sql('shipment_items', self.generate_shipment_items(1500), db_type))
        all_sql.append(self.generate_insert_sql('returns', self.generate_returns(200), db_type))
        all_sql.append(self.generate_insert_sql('return_items', self.generate_return_items(400), db_type))
        all_sql.append(self.generate_insert_sql('order_notes', self.generate_order_notes(500), db_type))
        all_sql.append(self.generate_insert_sql('order_discounts', self.generate_order_discounts(500), db_type))
        all_sql.append(self.generate_insert_sql('shopping_carts', self.generate_shopping_carts(500), db_type))
        all_sql.append(self.generate_insert_sql('cart_items', self.generate_cart_items(1000), db_type))
        all_sql.append(self.generate_insert_sql('saved_for_later', self.generate_saved_for_later(300), db_type))
        all_sql.append(self.generate_insert_sql('order_fulfillment', self.generate_order_fulfillment(800), db_type))
        all_sql.append(self.generate_insert_sql('fulfillment_items', self.generate_fulfillment_items(1500), db_type))

        # 12. E-Commerce payment tables
        all_sql.append(self.generate_insert_sql('payment_methods', self.generate_payment_methods(500), db_type))
        all_sql.append(self.generate_insert_sql('transactions', self.generate_transactions_ecom(1000), db_type))
        all_sql.append(self.generate_insert_sql('refunds', self.generate_refunds(200), db_type))
        all_sql.append(self.generate_insert_sql('invoices', self.generate_invoices(800), db_type))
        all_sql.append(self.generate_insert_sql('invoice_items', self.generate_invoice_items(2000), db_type))
        all_sql.append(self.generate_insert_sql('gift_cards', self.generate_gift_cards(200), db_type))
        all_sql.append(self.generate_insert_sql('gift_card_transactions', self.generate_gift_card_transactions(400), db_type))
        all_sql.append(self.generate_insert_sql('payment_plans', self.generate_payment_plans(200), db_type))
        all_sql.append(self.generate_insert_sql('payment_plan_installments', self.generate_payment_plan_installments(500), db_type))
        all_sql.append(self.generate_insert_sql('wallets', self.generate_wallets(300), db_type))

        # 13. E-Commerce marketing tables
        all_sql.append(self.generate_insert_sql('campaigns', self.generate_campaigns(50), db_type))
        all_sql.append(self.generate_insert_sql('coupon_usage', self.generate_coupon_usage(300), db_type))
        all_sql.append(self.generate_insert_sql('wishlists', self.generate_wishlists(300), db_type))
        all_sql.append(self.generate_insert_sql('wishlist_items', self.generate_wishlist_items(800), db_type))
        all_sql.append(self.generate_insert_sql('recommendations', self.generate_recommendations(500), db_type))
        all_sql.append(self.generate_insert_sql('recommendation_clicks', self.generate_recommendation_clicks(1000), db_type))

        # 14. E-Commerce analytics tables
        all_sql.append(self.generate_insert_sql('page_views', self.generate_page_views(2000), db_type))
        all_sql.append(self.generate_insert_sql('conversion_events', self.generate_conversion_events(500), db_type))
        all_sql.append(self.generate_insert_sql('sales_daily', self.generate_sales_daily(365), db_type))
        all_sql.append(self.generate_insert_sql('product_performance', self.generate_product_performance(500), db_type))
        all_sql.append(self.generate_insert_sql('search_queries', self.generate_search_queries(1000), db_type))
        all_sql.append(self.generate_insert_sql('abandoned_carts', self.generate_abandoned_carts(300), db_type))
        all_sql.append(self.generate_insert_sql('customer_lifetime_value', self.generate_customer_lifetime_value(500), db_type))

        # =====================================================================
        # 15. Banking Domain Tables - Reference tables first
        # =====================================================================
        all_sql.append(self.generate_insert_sql('loan_types', self.generate_loan_types(), db_type))
        all_sql.append(self.generate_insert_sql('loan_officers', self.generate_loan_officers(50), db_type))
        all_sql.append(self.generate_insert_sql('billing_codes', self.generate_billing_codes(100), db_type))

        # 16. Banking Domain - User and session tables (depend on customers)
        all_sql.append(self.generate_insert_sql('bank_users', self.generate_bank_users(500), db_type))
        all_sql.append(self.generate_insert_sql('bank_user_sessions', self.generate_bank_user_sessions(1000), db_type))
        all_sql.append(self.generate_insert_sql('security_questions', self.generate_security_questions(500), db_type))
        all_sql.append(self.generate_insert_sql('trusted_devices', self.generate_trusted_devices(500), db_type))
        all_sql.append(self.generate_insert_sql('bank_login_history', self.generate_bank_login_history(2000), db_type))

        # 17. Banking Domain - Transaction categories and tags
        all_sql.append(self.generate_insert_sql('bank_transaction_categories', self.generate_bank_transaction_categories(100), db_type))
        all_sql.append(self.generate_insert_sql('bank_transaction_tags', self.generate_bank_transaction_tags(500), db_type))

        # 18. Banking Domain - Account sub-types (depend on accounts)
        all_sql.append(self.generate_insert_sql('checking_accounts', self.generate_checking_accounts(500), db_type))
        all_sql.append(self.generate_insert_sql('savings_accounts', self.generate_savings_accounts(500), db_type))
        all_sql.append(self.generate_insert_sql('money_market_accounts', self.generate_money_market_accounts(200), db_type))
        all_sql.append(self.generate_insert_sql('joint_accounts', self.generate_joint_accounts(200), db_type))
        all_sql.append(self.generate_insert_sql('certificates_of_deposit', self.generate_certificates_of_deposit(200), db_type))

        # 19. Banking Domain - Account relationship tables
        all_sql.append(self.generate_insert_sql('account_holders', self.generate_account_holders(500), db_type))
        all_sql.append(self.generate_insert_sql('account_limits', self.generate_account_limits(500), db_type))
        all_sql.append(self.generate_insert_sql('account_statements', self.generate_account_statements(1000), db_type))
        all_sql.append(self.generate_insert_sql('account_alerts', self.generate_account_alerts(500), db_type))
        all_sql.append(self.generate_insert_sql('account_beneficiaries', self.generate_account_beneficiaries(500), db_type))

        # 20. Banking Domain - Card tables
        all_sql.append(self.generate_insert_sql('debit_cards', self.generate_debit_cards(500), db_type))
        all_sql.append(self.generate_insert_sql('virtual_cards', self.generate_virtual_cards(200), db_type))
        all_sql.append(self.generate_insert_sql('card_transactions', self.generate_card_transactions(2000), db_type))
        all_sql.append(self.generate_insert_sql('card_statements', self.generate_card_statements(500), db_type))
        all_sql.append(self.generate_insert_sql('card_rewards', self.generate_card_rewards(500), db_type))
        all_sql.append(self.generate_insert_sql('card_reward_redemptions', self.generate_card_reward_redemptions(300), db_type))
        all_sql.append(self.generate_insert_sql('card_limits', self.generate_card_limits(500), db_type))
        all_sql.append(self.generate_insert_sql('card_controls', self.generate_card_controls(500), db_type))
        all_sql.append(self.generate_insert_sql('card_disputes', self.generate_card_disputes(200), db_type))

        # 21. Banking Domain - Loan tables
        all_sql.append(self.generate_insert_sql('loans', self.generate_loans(500), db_type))
        all_sql.append(self.generate_insert_sql('loan_applications', self.generate_loan_applications(500), db_type))
        all_sql.append(self.generate_insert_sql('loan_payments', self.generate_loan_payments(2000), db_type))
        all_sql.append(self.generate_insert_sql('loan_schedules', self.generate_loan_schedules(2000), db_type))
        all_sql.append(self.generate_insert_sql('loan_status_history', self.generate_loan_status_history(500), db_type))
        all_sql.append(self.generate_insert_sql('loan_fees', self.generate_loan_fees(300), db_type))
        all_sql.append(self.generate_insert_sql('loan_documents', self.generate_loan_documents(500), db_type))
        all_sql.append(self.generate_insert_sql('loan_refinancing', self.generate_loan_refinancing(100), db_type))
        all_sql.append(self.generate_insert_sql('collateral', self.generate_collateral(300), db_type))
        all_sql.append(self.generate_insert_sql('guarantors', self.generate_guarantors(200), db_type))

        # 22. Banking Domain - Transfer tables
        all_sql.append(self.generate_insert_sql('transfers', self.generate_transfers(1000), db_type))
        all_sql.append(self.generate_insert_sql('ach_transfers', self.generate_ach_transfers(500), db_type))
        all_sql.append(self.generate_insert_sql('wire_transfers', self.generate_wire_transfers(200), db_type))
        all_sql.append(self.generate_insert_sql('scheduled_payments', self.generate_scheduled_payments(500), db_type))
        all_sql.append(self.generate_insert_sql('standing_orders', self.generate_standing_orders(300), db_type))

        # 23. Banking Domain - Compliance tables
        all_sql.append(self.generate_insert_sql('compliance_cases', self.generate_compliance_cases(200), db_type))
        all_sql.append(self.generate_insert_sql('aml_checks', self.generate_aml_checks(500), db_type))
        all_sql.append(self.generate_insert_sql('suspicious_activity_reports', self.generate_suspicious_activity_reports(100), db_type))
        all_sql.append(self.generate_insert_sql('kyc_documents', self.generate_kyc_documents(500), db_type))
        all_sql.append(self.generate_insert_sql('sanctions_screening', self.generate_sanctions_screening(500), db_type))

        # 24. Banking Domain - Transaction detail tables
        all_sql.append(self.generate_insert_sql('transaction_disputes', self.generate_transaction_disputes(200), db_type))
        all_sql.append(self.generate_insert_sql('transaction_fees', self.generate_transaction_fees(500), db_type))
        all_sql.append(self.generate_insert_sql('atm_transactions', self.generate_atm_transactions(500), db_type))
        all_sql.append(self.generate_insert_sql('pos_transactions', self.generate_pos_transactions(500), db_type))
        all_sql.append(self.generate_insert_sql('check_deposits', self.generate_check_deposits(500), db_type))
        all_sql.append(self.generate_insert_sql('recurring_transactions', self.generate_recurring_transactions(300), db_type))

        # =====================================================================
        # Generate additional params (not tied to specific seed tables)
        # =====================================================================
        print("  Generating additional params...")
        self.generate_date_range_params()
        self.generate_ddl_test_table_params(db_type)  # DDL on ddl_test_NNN only (vendor-specific types)
        self.generate_temp_user_params()               # Temp users only (load_user_NNN)
        self.generate_grant_params()
        self.generate_user_credentials_params()

        # =====================================================================
        # Write seed data SQL files
        # =====================================================================
        combined_sql = "\n".join(all_sql)
        combined_file = seed_path / "seed_data.sql"
        combined_file.write_text(combined_sql)
        files['seed_data.sql'] = str(combined_file)

        # Write batched files
        lines = combined_sql.split('\n')
        batch = []
        for line in lines:
            batch.append(line)
            if len(batch) >= self.batch_size:
                batch_file = batched_path / f"batch_{batch_num:03d}.sql"
                batch_file.write_text('\n'.join(batch))
                files[f'batch_{batch_num:03d}.sql'] = str(batch_file)
                batch = []
                batch_num += 1

        if batch:
            batch_file = batched_path / f"batch_{batch_num:03d}.sql"
            batch_file.write_text('\n'.join(batch))
            files[f'batch_{batch_num:03d}.sql'] = str(batch_file)

        print(f"  Generated seed data in {seed_path}")

        # =====================================================================
        # Write params CSV files (SINGLE-PASS: values from actual seed data)
        # =====================================================================
        param_files = self.params.write_all(params_path)
        files.update({f"params/{k}.csv": v for k, v in param_files.items()})
        print(f"  Generated {len(param_files)} param files in {params_path}")
        print("  Params contain ACTUAL values from seed data (single-pass)")

        return files
