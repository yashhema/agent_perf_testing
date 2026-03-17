-- Migration: Restructure baseline tests — test run = test case
-- Adds: name/description/parent_run_id to baseline_test_runs,
--        per-target state tracking, duration overrides on load profile links.
-- All columns are nullable or have defaults — zero breaking changes.
--
-- SQL Server (T-SQL) version.  PostgreSQL version below (commented out).

-- =====================================================================
-- 1. baseline_test_runs: add name, description, parent_run_id
-- =====================================================================

IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('baseline_test_runs') AND name = 'name')
BEGIN
    ALTER TABLE baseline_test_runs ADD name NVARCHAR(255) NULL;
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('baseline_test_runs') AND name = 'description')
BEGIN
    ALTER TABLE baseline_test_runs ADD description NVARCHAR(MAX) NULL;
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('baseline_test_runs') AND name = 'parent_run_id')
BEGIN
    ALTER TABLE baseline_test_runs ADD parent_run_id INT NULL;
    ALTER TABLE baseline_test_runs ADD CONSTRAINT FK_baseline_test_runs_parent
        FOREIGN KEY (parent_run_id) REFERENCES baseline_test_runs(id);
END
GO

-- =====================================================================
-- 2. baseline_test_run_targets: add per-target state tracking
-- =====================================================================
-- Note: SQLAlchemy stores Enum as VARCHAR on SQL Server (no native enum type).
-- The state column uses VARCHAR(20) with a CHECK constraint.

IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('baseline_test_run_targets') AND name = 'state')
BEGIN
    ALTER TABLE baseline_test_run_targets ADD state VARCHAR(20) NOT NULL
        CONSTRAINT DF_bltrt_state DEFAULT 'pending'
        CONSTRAINT CK_bltrt_state CHECK (state IN (
            'pending','setting_up','calibrating','generating',
            'executing','storing','comparing','completed','failed','skipped'
        ));
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('baseline_test_run_targets') AND name = 'error_message')
BEGIN
    ALTER TABLE baseline_test_run_targets ADD error_message NVARCHAR(MAX) NULL;
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('baseline_test_run_targets') AND name = 'current_load_profile_id')
BEGIN
    ALTER TABLE baseline_test_run_targets ADD current_load_profile_id INT NULL;
    ALTER TABLE baseline_test_run_targets ADD CONSTRAINT FK_bltrt_current_lp
        FOREIGN KEY (current_load_profile_id) REFERENCES load_profiles(id);
END
GO

-- =====================================================================
-- 3. baseline_test_run_load_profiles: add duration overrides
-- =====================================================================

IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('baseline_test_run_load_profiles') AND name = 'duration_sec')
BEGIN
    ALTER TABLE baseline_test_run_load_profiles ADD duration_sec INT NULL;
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('baseline_test_run_load_profiles') AND name = 'ramp_up_sec')
BEGIN
    ALTER TABLE baseline_test_run_load_profiles ADD ramp_up_sec INT NULL;
END
GO


-- =====================================================================
-- PostgreSQL version (uncomment if using PostgreSQL instead of SQL Server)
-- =====================================================================
/*
-- 1. baseline_test_runs
ALTER TABLE baseline_test_runs ADD COLUMN IF NOT EXISTS name VARCHAR(255) NULL;
ALTER TABLE baseline_test_runs ADD COLUMN IF NOT EXISTS description TEXT NULL;
ALTER TABLE baseline_test_runs ADD COLUMN IF NOT EXISTS parent_run_id INTEGER NULL
    REFERENCES baseline_test_runs(id) ON DELETE SET NULL;

-- 2. baseline_test_run_targets
-- PostgreSQL uses native ENUM types; create if not exists
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'baselinetargetstate') THEN
        CREATE TYPE baselinetargetstate AS ENUM (
            'pending','setting_up','calibrating','generating',
            'executing','storing','comparing','completed','failed','skipped'
        );
    END IF;
END$$;

ALTER TABLE baseline_test_run_targets ADD COLUMN IF NOT EXISTS state baselinetargetstate NOT NULL DEFAULT 'pending';
ALTER TABLE baseline_test_run_targets ADD COLUMN IF NOT EXISTS error_message TEXT NULL;
ALTER TABLE baseline_test_run_targets ADD COLUMN IF NOT EXISTS current_load_profile_id INTEGER NULL
    REFERENCES load_profiles(id) ON DELETE SET NULL;

-- 3. baseline_test_run_load_profiles
ALTER TABLE baseline_test_run_load_profiles ADD COLUMN IF NOT EXISTS duration_sec INTEGER NULL;
ALTER TABLE baseline_test_run_load_profiles ADD COLUMN IF NOT EXISTS ramp_up_sec INTEGER NULL;
*/
