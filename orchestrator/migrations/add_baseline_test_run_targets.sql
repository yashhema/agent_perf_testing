-- Migration: Add baseline_test_run_targets table for multi-server support
-- Moves per-server fields from baseline_test_runs to a new targets table.

-- 1. Create new targets table
CREATE TABLE baseline_test_run_targets (
    id INT IDENTITY(1,1) PRIMARY KEY,
    baseline_test_run_id INT NOT NULL
        REFERENCES baseline_test_runs(id),
    target_id INT NOT NULL
        REFERENCES servers(id),
    loadgenerator_id INT NOT NULL
        REFERENCES servers(id),
    partner_id INT NULL
        REFERENCES servers(id),
    test_snapshot_id INT NOT NULL
        REFERENCES snapshots(id),
    compare_snapshot_id INT NULL
        REFERENCES snapshots(id),
    service_monitor_patterns NVARCHAR(MAX) NULL,
    os_kind VARCHAR(100) NULL,
    os_major_ver VARCHAR(20) NULL,
    os_minor_ver VARCHAR(20) NULL,
    agent_versions NVARCHAR(MAX) NULL,
    CONSTRAINT uq_baseline_run_target
        UNIQUE(baseline_test_run_id, target_id)
);

CREATE INDEX ix_btrt_run_id ON baseline_test_run_targets(baseline_test_run_id);

-- 2. Migrate existing data (one target row per existing run)
INSERT INTO baseline_test_run_targets
    (baseline_test_run_id, target_id, loadgenerator_id,
     partner_id, test_snapshot_id, compare_snapshot_id,
     service_monitor_patterns, os_kind, os_major_ver,
     os_minor_ver, agent_versions)
SELECT
    id, server_id, loadgenerator_id,
    partner_id, test_snapshot_id, compare_snapshot_id,
    service_monitor_patterns, os_kind, os_major_ver,
    os_minor_ver, agent_versions
FROM baseline_test_runs
WHERE server_id IS NOT NULL;

-- 3. Drop moved columns and batch_id from baseline_test_runs
-- NOTE: Run these AFTER deploying code that uses the new targets table.
-- Drop default constraints first (SQL Server requires this).

-- Drop FK constraints on columns being removed
DECLARE @sql NVARCHAR(MAX) = '';
SELECT @sql = @sql + 'ALTER TABLE baseline_test_runs DROP CONSTRAINT ' + fk.name + '; '
FROM sys.foreign_keys fk
JOIN sys.foreign_key_columns fkc ON fk.object_id = fkc.constraint_object_id
JOIN sys.columns c ON fkc.parent_column_id = c.column_id AND fkc.parent_object_id = c.object_id
WHERE fk.parent_object_id = OBJECT_ID('baseline_test_runs')
  AND c.name IN ('server_id', 'test_snapshot_id', 'compare_snapshot_id',
                  'loadgenerator_id', 'partner_id');
EXEC sp_executesql @sql;

-- Drop index on batch_id if exists
IF EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_baseline_test_runs_batch_id'
           AND object_id = OBJECT_ID('baseline_test_runs'))
    DROP INDEX ix_baseline_test_runs_batch_id ON baseline_test_runs;

-- Drop the columns
ALTER TABLE baseline_test_runs DROP COLUMN server_id;
ALTER TABLE baseline_test_runs DROP COLUMN test_snapshot_id;
ALTER TABLE baseline_test_runs DROP COLUMN compare_snapshot_id;
ALTER TABLE baseline_test_runs DROP COLUMN loadgenerator_id;
ALTER TABLE baseline_test_runs DROP COLUMN partner_id;
ALTER TABLE baseline_test_runs DROP COLUMN service_monitor_patterns;
ALTER TABLE baseline_test_runs DROP COLUMN os_kind;
ALTER TABLE baseline_test_runs DROP COLUMN os_major_ver;
ALTER TABLE baseline_test_runs DROP COLUMN os_minor_ver;
ALTER TABLE baseline_test_runs DROP COLUMN agent_versions;
ALTER TABLE baseline_test_runs DROP COLUMN batch_id;
