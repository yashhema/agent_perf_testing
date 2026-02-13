"""JMX Template Generator Package.

Generates JMeter test plans for:
- server-normal.jmx: CPU/MEM/DISK load
- server-file-heavy.jmx: File operations (no confidential)
- server-file-heavy_withconfidential.jmx: File operations with confidential data
- db-load.jmx: Database load (per database type)
"""

from .jmx_generator import JMXGenerator

__all__ = ['JMXGenerator']
