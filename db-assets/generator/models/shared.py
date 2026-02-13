"""Shared domain models (20 tables).

Categories:
- Users & Auth: 8 tables (users, roles, permissions, user_roles, sessions, api_keys, password_history, login_attempts)
- Addresses: 4 tables (addresses, countries, states, cities)
- Audit: 5 tables (audit_logs, data_changes, access_logs, system_events, error_logs)
- Config: 3 tables (system_config, feature_flags, notifications)
"""

from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime, Numeric,
    ForeignKey, UniqueConstraint, Index, Enum as SQLEnum
)
from sqlalchemy.orm import relationship
import enum

from .base import Base, TimestampMixin, AuditMixin


# ============================================================================
# Users & Auth (8 tables)
# ============================================================================

class User(Base, AuditMixin):
    """User accounts for all systems."""
    __tablename__ = 'users'

    user_id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), nullable=False, unique=True)
    email = Column(String(255), nullable=False, unique=True)
    password_hash = Column(String(255), nullable=False)
    first_name = Column(String(100))
    last_name = Column(String(100))
    phone = Column(String(20))
    is_verified = Column(Boolean, default=False)
    last_login_at = Column(DateTime)
    failed_login_count = Column(Integer, default=0)
    locked_until = Column(DateTime)

    # Relationships
    user_roles = relationship("UserRole", back_populates="user")
    sessions = relationship("Session", back_populates="user")
    api_keys = relationship("ApiKey", back_populates="user")
    password_history = relationship("PasswordHistory", back_populates="user")
    login_attempts = relationship("LoginAttempt", back_populates="user")


class Role(Base, TimestampMixin):
    """User roles for authorization."""
    __tablename__ = 'roles'

    role_id = Column(Integer, primary_key=True, autoincrement=True)
    role_name = Column(String(50), nullable=False, unique=True)
    description = Column(String(255))
    is_system_role = Column(Boolean, default=False)

    # Relationships
    user_roles = relationship("UserRole", back_populates="role")
    role_permissions = relationship("RolePermission", back_populates="role")


class Permission(Base, TimestampMixin):
    """Granular permissions."""
    __tablename__ = 'permissions'

    permission_id = Column(Integer, primary_key=True, autoincrement=True)
    permission_name = Column(String(100), nullable=False, unique=True)
    resource = Column(String(100), nullable=False)
    action = Column(String(50), nullable=False)
    description = Column(String(255))

    # Relationships
    role_permissions = relationship("RolePermission", back_populates="permission")

    __table_args__ = (
        UniqueConstraint('resource', 'action', name='uq_permission_resource_action'),
    )


class UserRole(Base, TimestampMixin):
    """User-Role assignments."""
    __tablename__ = 'user_roles'

    user_role_id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.user_id'), nullable=False)
    role_id = Column(Integer, ForeignKey('roles.role_id'), nullable=False)
    granted_by = Column(Integer, ForeignKey('users.user_id'))
    expires_at = Column(DateTime)

    # Relationships
    user = relationship("User", back_populates="user_roles", foreign_keys=[user_id])
    role = relationship("Role", back_populates="user_roles")

    __table_args__ = (
        UniqueConstraint('user_id', 'role_id', name='uq_user_role'),
    )


class RolePermission(Base, TimestampMixin):
    """Role-Permission assignments."""
    __tablename__ = 'role_permissions'

    role_permission_id = Column(Integer, primary_key=True, autoincrement=True)
    role_id = Column(Integer, ForeignKey('roles.role_id'), nullable=False)
    permission_id = Column(Integer, ForeignKey('permissions.permission_id'), nullable=False)

    # Relationships
    role = relationship("Role", back_populates="role_permissions")
    permission = relationship("Permission", back_populates="role_permissions")

    __table_args__ = (
        UniqueConstraint('role_id', 'permission_id', name='uq_role_permission'),
    )


class Session(Base, TimestampMixin):
    """User sessions."""
    __tablename__ = 'sessions'

    session_id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.user_id'), nullable=False)
    session_token = Column(String(255), nullable=False, unique=True)
    ip_address = Column(String(45))
    user_agent = Column(String(500))
    expires_at = Column(DateTime, nullable=False)
    is_revoked = Column(Boolean, default=False)

    # Relationships
    user = relationship("User", back_populates="sessions")

    __table_args__ = (
        Index('ix_sessions_user_id', 'user_id'),
        Index('ix_sessions_token', 'session_token'),
    )


class ApiKey(Base, TimestampMixin):
    """API keys for programmatic access."""
    __tablename__ = 'api_keys'

    api_key_id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.user_id'), nullable=False)
    key_hash = Column(String(255), nullable=False, unique=True)
    key_prefix = Column(String(10), nullable=False)
    name = Column(String(100))
    scopes = Column(Text)
    expires_at = Column(DateTime)
    last_used_at = Column(DateTime)
    is_revoked = Column(Boolean, default=False)

    # Relationships
    user = relationship("User", back_populates="api_keys")


class PasswordHistory(Base, TimestampMixin):
    """Password history for policy enforcement."""
    __tablename__ = 'password_history'

    history_id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.user_id'), nullable=False)
    password_hash = Column(String(255), nullable=False)

    # Relationships
    user = relationship("User", back_populates="password_history")


class LoginAttempt(Base):
    """Login attempt tracking."""
    __tablename__ = 'login_attempts'

    attempt_id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.user_id'))
    username_attempted = Column(String(100), nullable=False)
    ip_address = Column(String(45), nullable=False)
    user_agent = Column(String(500))
    success = Column(Boolean, nullable=False)
    failure_reason = Column(String(100))
    attempted_at = Column(DateTime, nullable=False)

    # Relationships
    user = relationship("User", back_populates="login_attempts")

    __table_args__ = (
        Index('ix_login_attempts_user_id', 'user_id'),
        Index('ix_login_attempts_ip', 'ip_address'),
    )


# ============================================================================
# Addresses (4 tables)
# ============================================================================

class Country(Base, TimestampMixin):
    """Countries reference table."""
    __tablename__ = 'countries'

    country_id = Column(Integer, primary_key=True, autoincrement=True)
    country_code = Column(String(3), nullable=False, unique=True)
    country_name = Column(String(100), nullable=False)
    phone_code = Column(String(10))
    currency_code = Column(String(3))

    # Relationships
    states = relationship("State", back_populates="country")


class State(Base, TimestampMixin):
    """States/Provinces reference table."""
    __tablename__ = 'states'

    state_id = Column(Integer, primary_key=True, autoincrement=True)
    country_id = Column(Integer, ForeignKey('countries.country_id'), nullable=False)
    state_code = Column(String(10), nullable=False)
    state_name = Column(String(100), nullable=False)

    # Relationships
    country = relationship("Country", back_populates="states")
    cities = relationship("City", back_populates="state")

    __table_args__ = (
        UniqueConstraint('country_id', 'state_code', name='uq_state_code'),
    )


class City(Base, TimestampMixin):
    """Cities reference table."""
    __tablename__ = 'cities'

    city_id = Column(Integer, primary_key=True, autoincrement=True)
    state_id = Column(Integer, ForeignKey('states.state_id'), nullable=False)
    city_name = Column(String(100), nullable=False)
    zip_code = Column(String(20))
    latitude = Column(Numeric(10, 7))
    longitude = Column(Numeric(10, 7))

    # Relationships
    state = relationship("State", back_populates="cities")
    addresses = relationship("Address", back_populates="city")


class Address(Base, AuditMixin):
    """Addresses that can be linked to any entity."""
    __tablename__ = 'addresses'

    address_id = Column(Integer, primary_key=True, autoincrement=True)
    address_type = Column(String(20), nullable=False)  # HOME, WORK, BILLING, SHIPPING
    address_line1 = Column(String(255), nullable=False)
    address_line2 = Column(String(255))
    city_id = Column(Integer, ForeignKey('cities.city_id'))
    city_name = Column(String(100))
    state_code = Column(String(10))
    postal_code = Column(String(20))
    country_code = Column(String(3))
    is_verified = Column(Boolean, default=False)
    verified_at = Column(DateTime)

    # Relationships
    city = relationship("City", back_populates="addresses")


# ============================================================================
# Audit (5 tables)
# ============================================================================

class AuditLog(Base):
    """General audit log for all system actions."""
    __tablename__ = 'audit_logs'

    audit_id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.user_id'))
    action = Column(String(50), nullable=False)
    entity_type = Column(String(100), nullable=False)
    entity_id = Column(String(50))
    old_values = Column(Text)
    new_values = Column(Text)
    ip_address = Column(String(45))
    user_agent = Column(String(500))
    performed_at = Column(DateTime, nullable=False)

    __table_args__ = (
        Index('ix_audit_logs_entity', 'entity_type', 'entity_id'),
        Index('ix_audit_logs_user_id', 'user_id'),
        Index('ix_audit_logs_performed_at', 'performed_at'),
    )


class DataChange(Base):
    """Detailed data change tracking."""
    __tablename__ = 'data_changes'

    change_id = Column(Integer, primary_key=True, autoincrement=True)
    table_name = Column(String(100), nullable=False)
    record_id = Column(String(50), nullable=False)
    column_name = Column(String(100), nullable=False)
    old_value = Column(Text)
    new_value = Column(Text)
    change_type = Column(String(20), nullable=False)  # INSERT, UPDATE, DELETE
    changed_by = Column(Integer, ForeignKey('users.user_id'))
    changed_at = Column(DateTime, nullable=False)

    __table_args__ = (
        Index('ix_data_changes_table_record', 'table_name', 'record_id'),
    )


class AccessLog(Base):
    """Access log for sensitive data."""
    __tablename__ = 'access_logs'

    access_id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.user_id'), nullable=False)
    resource_type = Column(String(100), nullable=False)
    resource_id = Column(String(50))
    access_type = Column(String(20), nullable=False)  # READ, WRITE, DELETE
    query_text = Column(Text)
    row_count = Column(Integer)
    ip_address = Column(String(45))
    accessed_at = Column(DateTime, nullable=False)

    __table_args__ = (
        Index('ix_access_logs_user_id', 'user_id'),
        Index('ix_access_logs_resource', 'resource_type', 'resource_id'),
    )


class SystemEvent(Base):
    """System events and notifications."""
    __tablename__ = 'system_events'

    event_id = Column(Integer, primary_key=True, autoincrement=True)
    event_type = Column(String(50), nullable=False)
    severity = Column(String(20), nullable=False)  # INFO, WARNING, ERROR, CRITICAL
    source = Column(String(100), nullable=False)
    message = Column(Text, nullable=False)
    details = Column(Text)
    occurred_at = Column(DateTime, nullable=False)
    acknowledged_at = Column(DateTime)
    acknowledged_by = Column(Integer, ForeignKey('users.user_id'))

    __table_args__ = (
        Index('ix_system_events_type', 'event_type'),
        Index('ix_system_events_severity', 'severity'),
    )


class ErrorLog(Base):
    """Application error logs."""
    __tablename__ = 'error_logs'

    error_id = Column(Integer, primary_key=True, autoincrement=True)
    error_code = Column(String(50))
    error_type = Column(String(100), nullable=False)
    message = Column(Text, nullable=False)
    stack_trace = Column(Text)
    user_id = Column(Integer, ForeignKey('users.user_id'))
    request_url = Column(String(500))
    request_method = Column(String(10))
    request_body = Column(Text)
    ip_address = Column(String(45))
    occurred_at = Column(DateTime, nullable=False)
    resolved_at = Column(DateTime)
    resolved_by = Column(Integer, ForeignKey('users.user_id'))

    __table_args__ = (
        Index('ix_error_logs_type', 'error_type'),
        Index('ix_error_logs_occurred_at', 'occurred_at'),
    )


# ============================================================================
# Config (3 tables)
# ============================================================================

class SystemConfig(Base, AuditMixin):
    """System configuration key-value store."""
    __tablename__ = 'system_config'

    config_id = Column(Integer, primary_key=True, autoincrement=True)
    config_key = Column(String(100), nullable=False, unique=True)
    config_value = Column(Text)
    value_type = Column(String(20), nullable=False)  # STRING, INTEGER, BOOLEAN, JSON
    category = Column(String(50))
    description = Column(String(255))
    is_encrypted = Column(Boolean, default=False)


class FeatureFlag(Base, AuditMixin):
    """Feature flags for controlled rollouts."""
    __tablename__ = 'feature_flags'

    flag_id = Column(Integer, primary_key=True, autoincrement=True)
    flag_key = Column(String(100), nullable=False, unique=True)
    flag_name = Column(String(100), nullable=False)
    description = Column(String(255))
    is_enabled = Column(Boolean, default=False)
    rollout_percentage = Column(Integer, default=0)
    target_users = Column(Text)
    target_roles = Column(Text)
    start_date = Column(DateTime)
    end_date = Column(DateTime)


class Notification(Base, AuditMixin):
    """System notifications and alerts."""
    __tablename__ = 'notifications'

    notification_id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.user_id'))
    notification_type = Column(String(50), nullable=False)
    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    priority = Column(String(20), default='NORMAL')
    is_read = Column(Boolean, default=False)
    read_at = Column(DateTime)
    action_url = Column(String(500))
    expires_at = Column(DateTime)

    __table_args__ = (
        Index('ix_notifications_user_id', 'user_id'),
        Index('ix_notifications_type', 'notification_type'),
    )


# Export all models
__all__ = [
    # Users & Auth
    'User', 'Role', 'Permission', 'UserRole', 'RolePermission',
    'Session', 'ApiKey', 'PasswordHistory', 'LoginAttempt',
    # Addresses
    'Country', 'State', 'City', 'Address',
    # Audit
    'AuditLog', 'DataChange', 'AccessLog', 'SystemEvent', 'ErrorLog',
    # Config
    'SystemConfig', 'FeatureFlag', 'Notification',
]
