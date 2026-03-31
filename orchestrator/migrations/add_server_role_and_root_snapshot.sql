-- Migration: Add server role and root snapshot
-- Adds role column to distinguish target vs loadgen servers,
-- and root_snapshot_id for target servers' original OS snapshot.

-- SQL Server version
ALTER TABLE servers ADD role VARCHAR(10) NOT NULL DEFAULT 'target';
ALTER TABLE servers ADD root_snapshot_id INT NULL;
ALTER TABLE servers ADD CONSTRAINT fk_servers_root_snapshot
    FOREIGN KEY (root_snapshot_id) REFERENCES snapshots(id);

-- After migration: manually set role='loadgen' for loadgen servers, e.g.:
-- UPDATE servers SET role = 'loadgen' WHERE id IN (...);

-- PostgreSQL version (comment out above, uncomment below):
-- ALTER TABLE servers ADD COLUMN role VARCHAR(10) NOT NULL DEFAULT 'target';
-- ALTER TABLE servers ADD COLUMN root_snapshot_id INT NULL REFERENCES snapshots(id);
