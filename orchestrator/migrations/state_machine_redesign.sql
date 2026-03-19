-- State Machine Redesign Migration
-- Adds per-LP per-cycle tracking fields, updates constraints for cycle support,
-- and cleans up any in-progress rows with old states.
--
-- Supports both SQL Server and PostgreSQL.
-- Run the appropriate section for your database.

-- ============================================================================
-- SECTION A: COMMON (both SQL Server and PostgreSQL)
-- ============================================================================

-- 1. baseline_test_runs: add cycle tracking + failed_at_state
ALTER TABLE baseline_test_runs ADD current_cycle INT NOT NULL DEFAULT 1;
ALTER TABLE baseline_test_runs ADD cycle_count INT NOT NULL DEFAULT 1;
ALTER TABLE baseline_test_runs ADD failed_at_state VARCHAR(50) NULL;

-- 2. snapshot_profile_data: add cycle column, update unique constraint
ALTER TABLE snapshot_profile_data ADD cycle INT NOT NULL DEFAULT 1;

ALTER TABLE snapshot_profile_data DROP CONSTRAINT uq_snapshot_profile;
ALTER TABLE snapshot_profile_data
    ADD CONSTRAINT uq_snapshot_profile_cycle UNIQUE (snapshot_id, load_profile_id, cycle);

-- 3. comparison_results: add cycle column + unique constraint
ALTER TABLE comparison_results ADD cycle INT NOT NULL DEFAULT 1;

ALTER TABLE comparison_results
    ADD CONSTRAINT uq_baseline_comparison_cycle
    UNIQUE (baseline_test_run_id, target_id, load_profile_id, cycle);

-- 4. Clean up any in-progress rows with old states (BEFORE changing constraints)
UPDATE baseline_test_runs
SET state = 'failed',
    error_message = 'Auto-failed during state_machine_redesign migration (old state removed)'
WHERE state IN ('setting_up', 'deploying', 'setup_testing');

UPDATE baseline_test_run_targets
SET state = 'failed',
    error_message = 'Auto-failed during state_machine_redesign migration (old state removed)'
WHERE state IN ('setting_up', 'deploying', 'setup_testing');


-- ============================================================================
-- SECTION B: SQL SERVER ONLY
-- ============================================================================
-- SQL Server uses CHECK constraints for enum columns (VARCHAR with allowed values).
-- Drop old constraints and recreate with new state values.

-- baseline_test_runs.state: replace old CHECK constraint
ALTER TABLE baseline_test_runs DROP CONSTRAINT IF EXISTS CK_baseline_test_runs_state;
ALTER TABLE baseline_test_runs ADD CONSTRAINT CK_baseline_test_runs_state
    CHECK (state IN (
        'created', 'validating',
        'deploying_loadgen', 'deploying_calibration', 'deploying_testing',
        'calibrating', 'generating',
        'executing', 'storing', 'comparing',
        'completed', 'failed', 'cancelled'
    ));

-- baseline_test_run_targets.state: replace old CHECK constraint
ALTER TABLE baseline_test_run_targets DROP CONSTRAINT IF EXISTS CK_baseline_test_run_targets_state;
ALTER TABLE baseline_test_run_targets ADD CONSTRAINT CK_baseline_test_run_targets_state
    CHECK (state IN (
        'pending',
        'deploying_calibration', 'deploying_testing',
        'calibrating', 'generating',
        'executing', 'storing', 'comparing',
        'completed', 'failed', 'skipped'
    ));


-- ============================================================================
-- SECTION C: POSTGRESQL ONLY
-- Run this section instead of Section B on PostgreSQL.
-- ============================================================================
-- PostgreSQL uses native ENUM types. Cannot remove values from existing enums,
-- but CAN add new values. Old values ('setting_up', 'deploying', 'setup_testing')
-- become unused but harmless — rows using them were already updated to 'failed'
-- in Section A step 4.

-- Add new values to baselineteststate enum
-- (IF NOT EXISTS requires PostgreSQL 9.3+)
-- ALTER TYPE baselineteststate ADD VALUE IF NOT EXISTS 'deploying_loadgen';
-- ALTER TYPE baselineteststate ADD VALUE IF NOT EXISTS 'deploying_calibration';
-- ALTER TYPE baselineteststate ADD VALUE IF NOT EXISTS 'deploying_testing';

-- Add new values to baselinetargetstate enum
-- ALTER TYPE baselinetargetstate ADD VALUE IF NOT EXISTS 'deploying_calibration';
-- ALTER TYPE baselinetargetstate ADD VALUE IF NOT EXISTS 'deploying_testing';

-- NOTE: If your PostgreSQL setup does not use native enum types (e.g. SQLAlchemy
-- was configured with create_constraint=False or uses VARCHAR), these ALTER TYPE
-- commands are not needed and can be skipped.
--
-- To check if you have native enums:
--   SELECT typname FROM pg_type WHERE typname IN ('baselineteststate', 'baselinetargetstate');
-- If this returns rows, uncomment the ALTER TYPE lines above and run them.
-- If it returns nothing, your setup uses VARCHAR and no action needed beyond Section A.
