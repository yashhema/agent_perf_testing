"""Add scenarios, hardware_profiles, packages tables.

Revision ID: 002_scenarios_packages
Revises: 001_initial
Create Date: 2024-01-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "002_scenarios_packages"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create hardware_profiles table
    op.create_table(
        "hardware_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("cpu_count", sa.Integer(), nullable=False),
        sa.Column("cpu_model", sa.String(length=255), nullable=True),
        sa.Column("memory_gb", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("disk_type", sa.String(length=50), nullable=True),
        sa.Column("disk_size_gb", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    # Create scenarios table
    op.create_table(
        "scenarios",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("lab_id", sa.Integer(), nullable=False),
        sa.Column("hardware_profile_id", sa.Integer(), nullable=True),
        sa.Column(
            "target_server_ids",
            postgresql.ARRAY(sa.Integer()),
            nullable=False,
        ),
        sa.Column(
            "loadgen_server_ids",
            postgresql.ARRAY(sa.Integer()),
            nullable=False,
        ),
        sa.Column("baseline_id", sa.Integer(), nullable=False),
        sa.Column(
            "is_calibrated", sa.Boolean(), nullable=False, server_default="false"
        ),
        sa.Column("calibrated_at", sa.DateTime(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["lab_id"], ["labs.id"]),
        sa.ForeignKeyConstraint(["hardware_profile_id"], ["hardware_profiles.id"]),
        sa.ForeignKeyConstraint(["baseline_id"], ["baseline.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index("idx_scenarios_lab", "scenarios", ["lab_id"])
    op.create_index("idx_scenarios_active", "scenarios", ["is_active"])

    # Create package_groups table
    op.create_table(
        "package_groups",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("group_type", sa.String(length=50), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    # Create packages table
    op.create_table(
        "packages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("version", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("package_type", sa.String(length=50), nullable=False),
        sa.Column("download_url", sa.String(length=1000), nullable=True),
        sa.Column("checksum", sa.String(length=128), nullable=True),
        sa.Column("checksum_type", sa.String(length=20), nullable=True),
        sa.Column("install_command", sa.Text(), nullable=True),
        sa.Column("uninstall_command", sa.Text(), nullable=True),
        sa.Column("verify_command", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", "version", name="uq_package_name_version"),
    )
    op.create_index("idx_packages_type", "packages", ["package_type"])

    # Create package_group_members table
    op.create_table(
        "package_group_members",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("package_group_id", sa.Integer(), nullable=False),
        sa.Column("package_id", sa.Integer(), nullable=False),
        sa.Column("os_family", sa.String(length=20), nullable=False),
        sa.Column("install_path", sa.String(length=500), nullable=True),
        sa.Column("config_template", sa.Text(), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["package_group_id"], ["package_groups.id"]),
        sa.ForeignKeyConstraint(["package_id"], ["packages.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "package_group_id",
            "package_id",
            "os_family",
            name="uq_package_group_member",
        ),
    )
    op.create_index(
        "idx_package_group_members_group", "package_group_members", ["package_group_id"]
    )


def downgrade() -> None:
    op.drop_table("package_group_members")
    op.drop_table("packages")
    op.drop_table("package_groups")
    op.drop_table("scenarios")
    op.drop_table("hardware_profiles")
