-- Migration: Fix baseline-compare mode issues found during analysis
-- Date: 2026-03-09
--
-- Changes:
--   1. Add OS version columns to servers table (for package resolution)
--   2. Add baseline_test_run_id to calibration_results (FK to baseline_test_runs)
--   3. Make calibration_results.test_run_id nullable (baseline mode uses baseline_test_run_id)
--   4. Add snapshot_id column to snapshot_groups if not exists

-- 1. Server OS version columns (for PackageResolver in baseline-compare mode)
ALTER TABLE servers ADD os_vendor_family VARCHAR(100) NULL;
ALTER TABLE servers ADD os_major_ver VARCHAR(20) NULL;
ALTER TABLE servers ADD os_minor_ver VARCHAR(20) NULL;

-- 2. CalibrationResultORM: add baseline_test_run_id FK
ALTER TABLE calibration_results ADD baseline_test_run_id INT NULL;
ALTER TABLE calibration_results ADD CONSTRAINT fk_cal_baseline_test_run
    FOREIGN KEY (baseline_test_run_id) REFERENCES baseline_test_runs(id);

-- 3. Make test_run_id nullable (baseline calibrations don't have a test_runs row)
ALTER TABLE calibration_results ALTER COLUMN test_run_id INT NULL;

-- 4. Add snapshot_id to snapshot_groups if missing
IF COL_LENGTH('snapshot_groups', 'snapshot_id') IS NULL
BEGIN
    ALTER TABLE snapshot_groups ADD snapshot_id INT NULL;
    ALTER TABLE snapshot_groups ADD CONSTRAINT fk_sg_snapshot
        FOREIGN KEY (snapshot_id) REFERENCES snapshots(id);
END;

-- 5. Add indexes for common baseline-compare queries
CREATE INDEX IF NOT EXISTS ix_baseline_test_runs_server_id
    ON baseline_test_runs(server_id);
CREATE INDEX IF NOT EXISTS ix_baseline_test_runs_state
    ON baseline_test_runs(state);
CREATE INDEX IF NOT EXISTS ix_comparison_results_baseline_test_run_id
    ON comparison_results(baseline_test_run_id);
