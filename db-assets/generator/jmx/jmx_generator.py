"""Main JMX Generator.

Generates all JMeter test plan templates:
1. server-normal.jmx
2. server-file-heavy.jmx (also generates confidential variant)
3. db-load.jmx (per database type)

All templates use deterministic operation sequences via CSV Data Set Config
+ If Controllers instead of probabilistic Throughput Controllers.
"""

from pathlib import Path
from typing import Dict

from .templates.server_normal import save_server_normal
from .templates.server_file_heavy import save_server_file_heavy, save_server_file_confidential
from .templates.db_load import save_db_load


class JMXGenerator:
    """Generator for JMeter test plan templates."""

    SUPPORTED_DB_TYPES = ['postgresql', 'mssql', 'oracle', 'db2']

    TEMPLATES = {
        'server-normal': {
            'filename': 'server-normal.jmx',
            'description': 'Normal server load (CPU/MEM/DISK)',
        },
        'server-file-heavy': {
            'filename': 'server-file-heavy.jmx',
            'description': 'File-heavy load (no confidential data)',
        },
        'server-file-confidential': {
            'filename': 'server-file-heavy_withconfidential.jmx',
            'description': 'File-heavy load (with confidential data)',
        },
        'db-load': {
            'filename': 'db-load-{db_type}.jmx',
            'description': 'Database load (per database type)',
        },
    }

    def __init__(self, output_dir: str):
        """Initialize the JMX generator.

        Args:
            output_dir: Directory to save generated JMX files
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_server_normal(self) -> str:
        """Generate server-normal.jmx.

        Returns:
            Path to the generated file
        """
        output_path = self.output_dir / 'server-normal.jmx'
        save_server_normal(str(output_path))
        return str(output_path)

    def generate_server_file_heavy(self) -> str:
        """Generate server-file-heavy.jmx.

        Returns:
            Path to the generated file
        """
        output_path = self.output_dir / 'server-file-heavy.jmx'
        save_server_file_heavy(str(output_path))
        return str(output_path)

    def generate_server_file_confidential(self) -> str:
        """Generate server-file-heavy_withconfidential.jmx.

        Returns:
            Path to the generated file
        """
        output_path = self.output_dir / 'server-file-heavy_withconfidential.jmx'
        save_server_file_confidential(str(output_path))
        return str(output_path)

    def generate_db_load(self, db_type: str) -> str:
        """Generate db-load.jmx for a specific database type.

        Args:
            db_type: Database type (postgresql, mssql, oracle, db2)

        Returns:
            Path to the generated file
        """
        if db_type not in self.SUPPORTED_DB_TYPES:
            raise ValueError(f"Unsupported database type: {db_type}. "
                           f"Supported types: {self.SUPPORTED_DB_TYPES}")

        output_path = self.output_dir / f'db-load-{db_type}.jmx'
        save_db_load(db_type, str(output_path))
        return str(output_path)

    def generate_all_server_templates(self) -> Dict[str, str]:
        """Generate all server load templates.

        Returns:
            Dictionary mapping template name to output path
        """
        results = {}
        results['server-normal'] = self.generate_server_normal()
        results['server-file-heavy'] = self.generate_server_file_heavy()
        results['server-file-confidential'] = self.generate_server_file_confidential()
        return results

    def generate_all_db_templates(self) -> Dict[str, str]:
        """Generate db-load templates for all database types.

        Returns:
            Dictionary mapping db type to output path
        """
        results = {}
        for db_type in self.SUPPORTED_DB_TYPES:
            results[db_type] = self.generate_db_load(db_type)
        return results

    def generate_all(self) -> Dict[str, str]:
        """Generate all JMX templates.

        Returns:
            Dictionary mapping template name to output path
        """
        results = {}

        # Server templates
        results.update(self.generate_all_server_templates())

        # Database templates
        for db_type in self.SUPPORTED_DB_TYPES:
            results[f'db-load-{db_type}'] = self.generate_db_load(db_type)

        return results

    @classmethod
    def get_template_info(cls) -> Dict[str, dict]:
        """Get information about available templates.

        Returns:
            Dictionary mapping template name to template info
        """
        return cls.TEMPLATES.copy()
