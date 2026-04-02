-- Migration: Add baseline_execution_results table
-- Stores per-LP per-cycle execution results (CPU stats, JTL data, success rate)
-- Previously only persisted in execution_manifest.json on disk.

-- PostgreSQL version (default)
CREATE TABLE IF NOT EXISTS baseline_execution_results (
    id SERIAL PRIMARY KEY,
    baseline_test_run_id INT NOT NULL REFERENCES baseline_test_runs(id),
    server_id INT NOT NULL REFERENCES servers(id),
    load_profile_id INT NOT NULL REFERENCES load_profiles(id),
    cycle INT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'in_progress',
    thread_count INT,
    cpu_avg DOUBLE PRECISION,
    cpu_p50 DOUBLE PRECISION,
    cpu_p95 DOUBLE PRECISION,
    cpu_min DOUBLE PRECISION,
    cpu_max DOUBLE PRECISION,
    mem_avg DOUBLE PRECISION,
    jtl_total_requests INT,
    jtl_total_errors INT,
    jtl_success_rate_pct DOUBLE PRECISION,
    stats_path VARCHAR(500),
    jtl_path VARCHAR(500),
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    UNIQUE (baseline_test_run_id, server_id, load_profile_id, cycle)
);

-- SQL Server version (comment out above, uncomment below):
-- CREATE TABLE baseline_execution_results (
--     id INT IDENTITY(1,1) PRIMARY KEY,
--     baseline_test_run_id INT NOT NULL,
--     server_id INT NOT NULL,
--     load_profile_id INT NOT NULL,
--     cycle INT NOT NULL,
--     status VARCHAR(20) NOT NULL DEFAULT 'in_progress',
--     thread_count INT NULL,
--     cpu_avg FLOAT NULL,
--     cpu_p50 FLOAT NULL,
--     cpu_p95 FLOAT NULL,
--     cpu_min FLOAT NULL,
--     cpu_max FLOAT NULL,
--     mem_avg FLOAT NULL,
--     jtl_total_requests INT NULL,
--     jtl_total_errors INT NULL,
--     jtl_success_rate_pct FLOAT NULL,
--     stats_path VARCHAR(500) NULL,
--     jtl_path VARCHAR(500) NULL,
--     started_at DATETIME NULL,
--     completed_at DATETIME NULL,
--     CONSTRAINT fk_ber_test_run FOREIGN KEY (baseline_test_run_id) REFERENCES baseline_test_runs(id),
--     CONSTRAINT fk_ber_server FOREIGN KEY (server_id) REFERENCES servers(id),
--     CONSTRAINT fk_ber_lp FOREIGN KEY (load_profile_id) REFERENCES load_profiles(id),
--     CONSTRAINT uq_baseline_exec_result UNIQUE (baseline_test_run_id, server_id, load_profile_id, cycle)
-- );
