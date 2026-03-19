-- State Machine Redesign Migration — PostgreSQL
-- Run this on PostgreSQL. For SQL Server, use state_machine_redesign.sql sections A+B.

BEGIN;

-- ============================================================================
-- 1. Add new enum values to native PostgreSQL enum types
-- Must be done BEFORE any rows use these values
-- ============================================================================

-- Check if enum types exist and add new values
DO $$
BEGIN
    -- baselineteststate: add 3 new deploy states
    IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'baselineteststate') THEN
        BEGIN ALTER TYPE baselineteststate ADD VALUE IF NOT EXISTS 'deploying_loadgen'; EXCEPTION WHEN duplicate_object THEN NULL; END;
        BEGIN ALTER TYPE baselineteststate ADD VALUE IF NOT EXISTS 'deploying_calibration'; EXCEPTION WHEN duplicate_object THEN NULL; END;
        BEGIN ALTER TYPE baselineteststate ADD VALUE IF NOT EXISTS 'deploying_testing'; EXCEPTION WHEN duplicate_object THEN NULL; END;
    END IF;

    -- baselinetargetstate: add 2 new deploy states
    IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'baselinetargetstate') THEN
        BEGIN ALTER TYPE baselinetargetstate ADD VALUE IF NOT EXISTS 'deploying_calibration'; EXCEPTION WHEN duplicate_object THEN NULL; END;
        BEGIN ALTER TYPE baselinetargetstate ADD VALUE IF NOT EXISTS 'deploying_testing'; EXCEPTION WHEN duplicate_object THEN NULL; END;
    END IF;
END$$;

-- ============================================================================
-- 2. Clean up rows with old states (before they become orphaned)
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

-- Drop old constraint, add new one including cycle
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

COMMIT;
