"""SQLAlchemy ORM Models Package.

This package contains 200 tables across 4 domains:
- shared: 20 tables (users, roles, addresses, audit, config)
- ecommerce: 60 tables (customers, products, orders, payments, marketing, analytics)
- banking: 60 tables (accounts, transactions, cards, loans, compliance, users)
- healthcare: 60 tables (patients, records, appointments, billing, clinical)
"""

from .base import Base, TimestampMixin, AuditMixin, SoftDeleteMixin

# Import all domain models to register them with Base
from . import shared
from . import ecommerce
from . import banking
from . import healthcare

# Re-export Base for easy access
__all__ = ['Base', 'TimestampMixin', 'AuditMixin', 'SoftDeleteMixin']
