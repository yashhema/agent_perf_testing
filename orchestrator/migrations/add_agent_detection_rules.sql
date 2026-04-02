-- Migration: Add agent_detection_rules table
-- Per-OS detection rules for verifying agent installation on servers.
-- Each agent can have multiple rules (one per OS family).

-- PostgreSQL version (default)
CREATE TABLE IF NOT EXISTS agent_detection_rules (
    id SERIAL PRIMARY KEY,
    agent_id INT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    os_regex VARCHAR(255) NOT NULL,
    cmd_type VARCHAR(20) NOT NULL,
    service_regex VARCHAR(255) NOT NULL,
    version_cmd TEXT
);

-- SQL Server version (comment out above, uncomment below):
-- CREATE TABLE agent_detection_rules (
--     id INT IDENTITY(1,1) PRIMARY KEY,
--     agent_id INT NOT NULL FOREIGN KEY REFERENCES agents(id) ON DELETE CASCADE,
--     os_regex VARCHAR(255) NOT NULL,
--     cmd_type VARCHAR(20) NOT NULL,
--     service_regex VARCHAR(255) NOT NULL,
--     version_cmd TEXT
-- );
