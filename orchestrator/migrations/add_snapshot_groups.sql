-- Migration: Add snapshot_baselines and snapshot_groups tables
-- Adds group_id and snapshot_tree columns to snapshots table
-- Run against the 'orchestrator' database on SQL Server

-- 1. Create snapshot_baselines table
IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'snapshot_baselines')
BEGIN
    CREATE TABLE snapshot_baselines (
        id INT IDENTITY(1,1) PRIMARY KEY,
        server_id INT NOT NULL,
        snapshot_id INT NOT NULL,
        name VARCHAR(200) NOT NULL,
        description NVARCHAR(MAX) NULL,
        created_at DATETIME NOT NULL DEFAULT GETUTCDATE(),

        CONSTRAINT FK_sb_server FOREIGN KEY (server_id) REFERENCES servers(id),
        CONSTRAINT FK_sb_snapshot FOREIGN KEY (snapshot_id) REFERENCES snapshots(id),
        CONSTRAINT UQ_sb_server_snapshot UNIQUE (server_id, snapshot_id)
    );
END
GO

-- 2. Create snapshot_groups table
IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'snapshot_groups')
BEGIN
    CREATE TABLE snapshot_groups (
        id INT IDENTITY(1,1) PRIMARY KEY,
        baseline_id INT NOT NULL,
        name VARCHAR(200) NOT NULL,
        description NVARCHAR(MAX) NULL,
        created_at DATETIME NOT NULL DEFAULT GETUTCDATE(),

        CONSTRAINT FK_sg_baseline FOREIGN KEY (baseline_id) REFERENCES snapshot_baselines(id)
    );
END
GO

-- 3. Add group_id to snapshots table
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('snapshots') AND name = 'group_id')
BEGIN
    ALTER TABLE snapshots ADD group_id INT NULL;
    ALTER TABLE snapshots ADD CONSTRAINT FK_snapshots_group FOREIGN KEY (group_id) REFERENCES snapshot_groups(id);
END
GO

-- 4. Add snapshot_tree JSON column to snapshots table
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('snapshots') AND name = 'snapshot_tree')
BEGIN
    ALTER TABLE snapshots ADD snapshot_tree NVARCHAR(MAX) NULL;
END
GO

PRINT 'Snapshot groups migration completed successfully.';
