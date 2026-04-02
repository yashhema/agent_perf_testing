-- Migration: Add subgroup definitions and agent junction tables
-- SubgroupDefinitionORM = named agent combinations (e.g., "CrowdStrike Only", "CS + Tanium")
-- SubgroupAgentORM = junction linking definitions to agents
-- Also adds subgroup_def_id FK on snapshot_groups

-- PostgreSQL version (default)
CREATE TABLE IF NOT EXISTS subgroup_definitions (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    description TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS subgroup_agents (
    id SERIAL PRIMARY KEY,
    subgroup_def_id INT NOT NULL REFERENCES subgroup_definitions(id) ON DELETE CASCADE,
    agent_id INT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    UNIQUE (subgroup_def_id, agent_id)
);

ALTER TABLE snapshot_groups ADD COLUMN IF NOT EXISTS subgroup_def_id INT NULL REFERENCES subgroup_definitions(id);

-- SQL Server version (comment out above, uncomment below):
-- CREATE TABLE subgroup_definitions (
--     id INT IDENTITY(1,1) PRIMARY KEY,
--     name VARCHAR(255) NOT NULL UNIQUE,
--     description TEXT,
--     created_at DATETIME NOT NULL DEFAULT GETDATE()
-- );
-- CREATE TABLE subgroup_agents (
--     id INT IDENTITY(1,1) PRIMARY KEY,
--     subgroup_def_id INT NOT NULL FOREIGN KEY REFERENCES subgroup_definitions(id) ON DELETE CASCADE,
--     agent_id INT NOT NULL FOREIGN KEY REFERENCES agents(id) ON DELETE CASCADE,
--     CONSTRAINT uq_subgroup_agent UNIQUE (subgroup_def_id, agent_id)
-- );
-- ALTER TABLE snapshot_groups ADD subgroup_def_id INT NULL FOREIGN KEY REFERENCES subgroup_definitions(id);
