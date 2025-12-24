"""Initial schema with all tables.

Revision ID: 001_initial
Revises:
Create Date: 2024-01-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create labs table
    op.create_table(
        "labs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("lab_type", sa.String(length=50), nullable=False),
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

    # Create servers table
    op.create_table(
        "servers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("hostname", sa.String(length=255), nullable=False),
        sa.Column("ip_address", sa.String(length=45), nullable=False),
        sa.Column("os_family", sa.String(length=20), nullable=False),
        sa.Column("server_type", sa.String(length=20), nullable=False),
        sa.Column("ssh_username", sa.String(length=100), nullable=True),
        sa.Column("ssh_key_path", sa.String(length=500), nullable=True),
        sa.Column("winrm_username", sa.String(length=100), nullable=True),
        sa.Column("emulator_port", sa.Integer(), nullable=False, server_default="8080"),
        sa.Column(
            "loadgen_service_port", sa.Integer(), nullable=False, server_default="8090"
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("lab_id", sa.Integer(), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_servers_lab", "servers", ["lab_id"])
    op.create_index("idx_servers_type", "servers", ["server_type"])

    # Create baseline table
    op.create_table(
        "baseline",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("baseline_type", sa.String(length=20), nullable=False),
        sa.Column("baseline_conf", postgresql.JSONB(), nullable=False),
        sa.Column("lab_id", sa.Integer(), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
    )

    # Create test_runs table
    op.create_table(
        "test_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "req_loadprofile",
            postgresql.ARRAY(sa.String(length=20)),
            nullable=False,
        ),
        sa.Column("warmup_sec", sa.Integer(), nullable=False, server_default="300"),
        sa.Column("measured_sec", sa.Integer(), nullable=False, server_default="10800"),
        sa.Column(
            "analysis_trim_sec", sa.Integer(), nullable=False, server_default="300"
        ),
        sa.Column("repetitions", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "loadgenerator_package_grpid_lst",
            postgresql.ARRAY(sa.Integer()),
            nullable=False,
        ),
        sa.Column("lab_id", sa.Integer(), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
    )

    # Create test_run_targets table
    op.create_table(
        "test_run_targets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("test_run_id", sa.Integer(), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("loadgenerator_id", sa.Integer(), nullable=False),
        sa.Column("jmeter_port", sa.Integer(), nullable=True),
        sa.Column("jmx_file_path", sa.String(length=500), nullable=True),
        sa.Column("base_baseline_id", sa.Integer(), nullable=True),
        sa.Column("initial_baseline_id", sa.Integer(), nullable=True),
        sa.Column("upgrade_baseline_id", sa.Integer(), nullable=True),
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
        sa.ForeignKeyConstraint(["base_baseline_id"], ["baseline.id"]),
        sa.ForeignKeyConstraint(["initial_baseline_id"], ["baseline.id"]),
        sa.ForeignKeyConstraint(["loadgenerator_id"], ["servers.id"]),
        sa.ForeignKeyConstraint(["target_id"], ["servers.id"]),
        sa.ForeignKeyConstraint(["test_run_id"], ["test_runs.id"]),
        sa.ForeignKeyConstraint(["upgrade_baseline_id"], ["baseline.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("test_run_id", "target_id", name="uq_test_run_target"),
        sa.UniqueConstraint(
            "test_run_id",
            "loadgenerator_id",
            "jmeter_port",
            name="uq_test_run_loadgen_port",
        ),
    )
    op.create_index(
        "idx_test_run_targets_test_run", "test_run_targets", ["test_run_id"]
    )
    op.create_index(
        "idx_test_run_targets_loadgen", "test_run_targets", ["loadgenerator_id"]
    )

    # Create test_run_execution table
    op.create_table(
        "test_run_execution",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("test_run_id", sa.Integer(), nullable=False),
        sa.Column(
            "run_mode", sa.String(length=20), nullable=False, server_default="continuous"
        ),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="notstarted"
        ),
        sa.Column("current_loadprofile", sa.String(length=20), nullable=True),
        sa.Column("current_repetition", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
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
        sa.ForeignKeyConstraint(["test_run_id"], ["test_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create calibration_results table
    op.create_table(
        "calibration_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("baseline_id", sa.Integer(), nullable=False),
        sa.Column("loadprofile", sa.String(length=20), nullable=False),
        sa.Column("thread_count", sa.Integer(), nullable=False),
        sa.Column("cpu_count", sa.Integer(), nullable=False),
        sa.Column("memory_gb", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("cpu_target_percent", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column(
            "achieved_cpu_percent", sa.Numeric(precision=5, scale=2), nullable=True
        ),
        sa.Column("avg_iteration_time_ms", sa.Integer(), nullable=True),
        sa.Column("stddev_iteration_time_ms", sa.Integer(), nullable=True),
        sa.Column("min_iteration_time_ms", sa.Integer(), nullable=True),
        sa.Column("max_iteration_time_ms", sa.Integer(), nullable=True),
        sa.Column("iteration_sample_count", sa.Integer(), nullable=True),
        sa.Column("calibration_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "calibration_status",
            sa.String(length=50),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("calibrated_at", sa.DateTime(), nullable=True),
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
        sa.ForeignKeyConstraint(["baseline_id"], ["baseline.id"]),
        sa.ForeignKeyConstraint(["target_id"], ["servers.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "target_id",
            "baseline_id",
            "loadprofile",
            name="uq_calibration_target_baseline_profile",
        ),
    )
    op.create_index(
        "idx_calibration_lookup",
        "calibration_results",
        ["target_id", "baseline_id", "loadprofile"],
    )

    # Create execution_workflow_state table
    op.create_table(
        "execution_workflow_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "test_run_execution_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("loadprofile", sa.String(length=20), nullable=False),
        sa.Column("runcount", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("base_baseline_id", sa.Integer(), nullable=True),
        sa.Column("initial_baseline_id", sa.Integer(), nullable=True),
        sa.Column("upgrade_baseline_id", sa.Integer(), nullable=True),
        sa.Column("current_phase", sa.String(length=50), nullable=False),
        sa.Column("phase_state", sa.String(length=50), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default="3"),
        sa.Column(
            "error_history",
            postgresql.JSONB(),
            nullable=False,
            server_default="'[]'::jsonb",
        ),
        sa.Column("phase_started_at", sa.DateTime(), nullable=True),
        sa.Column("phase_completed_at", sa.DateTime(), nullable=True),
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
        sa.ForeignKeyConstraint(["base_baseline_id"], ["baseline.id"]),
        sa.ForeignKeyConstraint(["initial_baseline_id"], ["baseline.id"]),
        sa.ForeignKeyConstraint(["target_id"], ["servers.id"]),
        sa.ForeignKeyConstraint(
            ["test_run_execution_id"], ["test_run_execution.id"]
        ),
        sa.ForeignKeyConstraint(["upgrade_baseline_id"], ["baseline.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "test_run_execution_id",
            "target_id",
            "loadprofile",
            "runcount",
            name="uq_workflow_state",
        ),
    )


def downgrade() -> None:
    op.drop_table("execution_workflow_state")
    op.drop_table("calibration_results")
    op.drop_table("test_run_execution")
    op.drop_table("test_run_targets")
    op.drop_table("test_runs")
    op.drop_table("baseline")
    op.drop_table("servers")
    op.drop_table("labs")
