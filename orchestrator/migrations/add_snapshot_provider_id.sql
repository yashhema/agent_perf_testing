-- Migration: Add provider_snapshot_id to snapshots table
-- Replaces name-based uniqueness with provider-ID-based uniqueness.
-- vSphere allows duplicate snapshot names; MoRef ID is the true unique key.
-- Run against the 'orchestrator' database on SQL Server

-- 1. Add provider_snapshot_id column (nullable initially for backfill)
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('snapshots') AND name = 'provider_snapshot_id')
BEGIN
    ALTER TABLE snapshots ADD provider_snapshot_id VARCHAR(100) NULL;
END
GO

-- 2. Backfill existing rows: extract from provider_ref JSON or fall back to name
UPDATE snapshots
SET provider_snapshot_id = COALESCE(
    JSON_VALUE(provider_ref, '$.snapshot_moref_id'),
    JSON_VALUE(provider_ref, '$.snapshot_id'),
    JSON_VALUE(provider_ref, '$.snapshot_name'),
    name
)
WHERE provider_snapshot_id IS NULL;
GO

-- 3. Make column NOT NULL after backfill
ALTER TABLE snapshots ALTER COLUMN provider_snapshot_id VARCHAR(100) NOT NULL;
GO

-- 4. Drop old unique constraint (name-based)
IF EXISTS (SELECT 1 FROM sys.key_constraints WHERE name = 'UQ_snapshot_server_name')
BEGIN
    ALTER TABLE snapshots DROP CONSTRAINT UQ_snapshot_server_name;
END
GO

-- 5. Add new unique constraint (provider-ID-based)
IF NOT EXISTS (SELECT 1 FROM sys.key_constraints WHERE name = 'UQ_snapshot_server_provider_id')
BEGIN
    ALTER TABLE snapshots ADD CONSTRAINT UQ_snapshot_server_provider_id
        UNIQUE (server_id, provider_snapshot_id);
END
GO

PRINT 'Snapshot provider_snapshot_id migration completed successfully.';
