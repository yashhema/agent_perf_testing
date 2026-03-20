-- Add clean_snapshot_id to servers table
-- Used by loadgens to store a known-good hypervisor snapshot for reverting
-- before each test run (pre-JMeter/emulator install state).
--
-- Works on both SQL Server and PostgreSQL.

ALTER TABLE servers ADD clean_snapshot_id INT NULL;

-- Foreign key to snapshots table
ALTER TABLE servers
    ADD CONSTRAINT fk_servers_clean_snapshot
    FOREIGN KEY (clean_snapshot_id) REFERENCES snapshots(id);
