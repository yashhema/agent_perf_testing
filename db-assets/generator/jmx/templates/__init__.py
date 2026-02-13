"""JMX Template Generators."""

from .server_normal import generate_server_normal
from .server_file_heavy import generate_server_file_heavy
from .server_file_confidential import generate_server_file_confidential
from .db_load import generate_db_load

__all__ = [
    'generate_server_normal',
    'generate_server_file_heavy',
    'generate_server_file_confidential',
    'generate_db_load',
]
