-- State Machine Redesign Migration — PostgreSQL
-- Run this on PostgreSQL. For SQL Server, use state_machine_redesign.sql sections A+B.
--
-- NOTE: ALTER TYPE ... ADD VALUE cannot run inside a transaction block in PostgreSQL.
-- This script must be run with autocommit (psql default) or with:
--   psql -d <db> -f state_machine_redesign_postgres.sql

-- ============================================================================
-- 1. Add new enum values to native PostgreSQL enum types
-- Must run OUTSIDE a transaction (ALTER TYPE ADD VALUE restriction)
-- ============================================================================

-- baselineteststate: add 3 new deploy states
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'baselineteststate') THEN
        IF NOT EXISTS (SELECT 1 FROM pg_enum WHERE enumlabel = 'deploying_loadgen' AND enumtypid = (SELECT oid FROM pg_type WHERE typname = 'baselineteststate')) THEN
            ALTER TYPE baselineteststate ADD VALUE 'deploying_loadgen';
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_enum WHERE enumlabel = 'deploying_calibration' AND enumtypid = (SELECT oid FROM pg_type WHERE typname = 'baselineteststate')) THEN
            ALTER TYPE baselineteststate ADD VALUE 'deploying_calibration';
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_enum WHERE enumlabel = 'deploying_testing' AND enumtypid = (SELECT oid FROM pg_type WHERE typname = 'baselineteststate')) THEN
            ALTER TYPE baselineteststate ADD VALUE 'deploying_testing';
        END IF;
    END IF;
END$$;

-- baselinetargetstate: add 2 new deploy states
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'baselinetargetstate') THEN
        IF NOT EXISTS (SELECT 1 FROM pg_enum WHERE enumlabel = 'deploying_calibration' AND enumtypid = (SELECT oid FROM pg_type WHERE typname = 'baselinetargetstate')) THEN
            ALTER TYPE baselinetargetstate ADD VALUE 'deploying_calibration';
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_enum WHERE enumlabel = 'deploying_testing' AND enumtypid = (SELECT oid FROM pg_type WHERE typname = 'baselinetargetstate')) THEN
            ALTER TYPE baselinetargetstate ADD VALUE 'deploying_testing';
        END IF;
    END IF;
END$$;

-- ============================================================================
-- 2. Clean up rows with old states
-- Old values ('setting_up', 'deploying', 'setup_testing') remain in the enum
-- type but will no longer be used by the application.
-- ============================================================================

UPDATE baseline_test_runs
SET state = 'failed',
    error_message = 'Auto-failed during state_machine_redesign migration (old state removed)'
WHERE state IN ('setting_up', 'deploying', 'setup_testing');

UPDATE baseline_test_run_targets
SET state = 'failed',
    error_message = 'Auto-failed during state_machine_redesign migration (old state removed)'
WHERE state IN ('setting_up', 'deploying', 'setup_testing');

-- ============================================================================
-- 3. baseline_test_runs: add cycle tracking + failed_at_state
-- ============================================================================

ALTER TABLE baseline_test_runs ADD COLUMN IF NOT EXISTS current_cycle INT NOT NULL DEFAULT 1;
ALTER TABLE baseline_test_runs ADD COLUMN IF NOT EXISTS cycle_count INT NOT NULL DEFAULT 1;
ALTER TABLE baseline_test_runs ADD COLUMN IF NOT EXISTS failed_at_state VARCHAR(50) NULL;

-- ============================================================================
-- 4. snapshot_profile_data: add cycle column, update unique constraint
-- ============================================================================

ALTER TABLE snapshot_profile_data ADD COLUMN IF NOT EXISTS cycle INT NOT NULL DEFAULT 1;

ALTER TABLE snapshot_profile_data DROP CONSTRAINT IF EXISTS uq_snapshot_profile;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'uq_snapshot_profile_cycle'
    ) THEN
        ALTER TABLE snapshot_profile_data
            ADD CONSTRAINT uq_snapshot_profile_cycle UNIQUE (snapshot_id, load_profile_id, cycle);
    END IF;
END$$;

-- ============================================================================
-- 5. comparison_results: add cycle column + unique constraint
-- ============================================================================

ALTER TABLE comparison_results ADD COLUMN IF NOT EXISTS cycle INT NOT NULL DEFAULT 1;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'uq_baseline_comparison_cycle'
    ) THEN
        ALTER TABLE comparison_results
            ADD CONSTRAINT uq_baseline_comparison_cycle
            UNIQUE (baseline_test_run_id, target_id, load_profile_id, cycle);
    END IF;
END$$;
