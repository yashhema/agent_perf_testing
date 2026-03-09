-- Migration: Add baseline-compare mode tables and columns
-- Run against the 'orchestrator' database on SQL Server

-- 1. Add execution_mode to labs
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('labs') AND name = 'execution_mode')
BEGIN
    ALTER TABLE labs ADD execution_mode VARCHAR(20) NOT NULL DEFAULT 'live_compare';
END
GO

-- 2. Add baseline-compare defaults to servers
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('servers') AND name = 'default_loadgen_id')
BEGIN
    ALTER TABLE servers ADD default_loadgen_id INT NULL;
    ALTER TABLE servers ADD CONSTRAINT FK_servers_default_loadgen FOREIGN KEY (default_loadgen_id) REFERENCES servers(id);
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('servers') AND name = 'default_partner_id')
BEGIN
    ALTER TABLE servers ADD default_partner_id INT NULL;
    ALTER TABLE servers ADD CONSTRAINT FK_servers_default_partner FOREIGN KEY (default_partner_id) REFERENCES servers(id);
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('servers') AND name = 'service_monitor_patterns')
BEGIN
    ALTER TABLE servers ADD service_monitor_patterns NVARCHAR(MAX) NULL;
END
GO

-- 3. Create snapshots table
IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'snapshots')
BEGIN
    CREATE TABLE snapshots (
        id INT IDENTITY(1,1) PRIMARY KEY,
        name VARCHAR(200) NOT NULL,
        description NVARCHAR(MAX) NULL,
        server_id INT NOT NULL,
        parent_id INT NULL,
        provider_snapshot_id VARCHAR(100) NOT NULL,
        provider_ref NVARCHAR(MAX) NOT NULL,
        is_baseline BIT NOT NULL DEFAULT 0,
        is_archived BIT NOT NULL DEFAULT 0,
        created_at DATETIME NOT NULL DEFAULT GETUTCDATE(),

        CONSTRAINT FK_snapshots_server FOREIGN KEY (server_id) REFERENCES servers(id),
        CONSTRAINT FK_snapshots_parent FOREIGN KEY (parent_id) REFERENCES snapshots(id),
        CONSTRAINT UQ_snapshot_server_provider_id UNIQUE (server_id, provider_snapshot_id)
    );
END
GO

-- 4. Create snapshot_profile_data table
IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'snapshot_profile_data')
BEGIN
    CREATE TABLE snapshot_profile_data (
        id INT IDENTITY(1,1) PRIMARY KEY,
        snapshot_id INT NOT NULL,
        load_profile_id INT NOT NULL,
        thread_count INT NOT NULL,
        jmx_test_case_data VARCHAR(500) NULL,
        stats_data VARCHAR(500) NULL,
        stats_summary NVARCHAR(MAX) NULL,
        jtl_data VARCHAR(500) NULL,
        source_snapshot_id INT NULL,
        created_at DATETIME NOT NULL DEFAULT GETUTCDATE(),

        CONSTRAINT FK_spd_snapshot FOREIGN KEY (snapshot_id) REFERENCES snapshots(id),
        CONSTRAINT FK_spd_load_profile FOREIGN KEY (load_profile_id) REFERENCES load_profiles(id),
        CONSTRAINT FK_spd_source_snapshot FOREIGN KEY (source_snapshot_id) REFERENCES snapshots(id),
        CONSTRAINT UQ_snapshot_profile UNIQUE (snapshot_id, load_profile_id)
    );
END
GO

-- 5. Create baseline_test_runs table
IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'baseline_test_runs')
BEGIN
    CREATE TABLE baseline_test_runs (
        id INT IDENTITY(1,1) PRIMARY KEY,
        server_id INT NOT NULL,
        lab_id INT NOT NULL,
        scenario_id INT NOT NULL,
        test_type VARCHAR(40) NOT NULL,
        test_snapshot_id INT NOT NULL,
        compare_snapshot_id INT NULL,
        loadgenerator_id INT NOT NULL,
        partner_id INT NULL,
        service_monitor_patterns NVARCHAR(MAX) NULL,
        state VARCHAR(20) NOT NULL DEFAULT 'created',
        current_load_profile_id INT NULL,
        error_message NVARCHAR(MAX) NULL,
        verdict VARCHAR(10) NULL,
        os_kind VARCHAR(100) NULL,
        os_major_ver VARCHAR(20) NULL,
        os_minor_ver VARCHAR(20) NULL,
        agent_versions NVARCHAR(MAX) NULL,
        created_at DATETIME NOT NULL DEFAULT GETUTCDATE(),
        started_at DATETIME NULL,
        completed_at DATETIME NULL,

        CONSTRAINT FK_btr_server FOREIGN KEY (server_id) REFERENCES servers(id),
        CONSTRAINT FK_btr_lab FOREIGN KEY (lab_id) REFERENCES labs(id),
        CONSTRAINT FK_btr_scenario FOREIGN KEY (scenario_id) REFERENCES scenarios(id),
        CONSTRAINT FK_btr_test_snapshot FOREIGN KEY (test_snapshot_id) REFERENCES snapshots(id),
        CONSTRAINT FK_btr_compare_snapshot FOREIGN KEY (compare_snapshot_id) REFERENCES snapshots(id),
        CONSTRAINT FK_btr_loadgen FOREIGN KEY (loadgenerator_id) REFERENCES servers(id),
        CONSTRAINT FK_btr_partner FOREIGN KEY (partner_id) REFERENCES servers(id),
        CONSTRAINT FK_btr_current_lp FOREIGN KEY (current_load_profile_id) REFERENCES load_profiles(id)
    );
END
GO

-- 6. Create baseline_test_run_load_profiles join table
IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'baseline_test_run_load_profiles')
BEGIN
    CREATE TABLE baseline_test_run_load_profiles (
        id INT IDENTITY(1,1) PRIMARY KEY,
        baseline_test_run_id INT NOT NULL,
        load_profile_id INT NOT NULL,

        CONSTRAINT FK_btrlp_btr FOREIGN KEY (baseline_test_run_id) REFERENCES baseline_test_runs(id),
        CONSTRAINT FK_btrlp_lp FOREIGN KEY (load_profile_id) REFERENCES load_profiles(id),
        CONSTRAINT UQ_baseline_test_run_lp UNIQUE (baseline_test_run_id, load_profile_id)
    );
END
GO

-- 7. Add baseline_test_run_id to comparison_results (nullable FK)
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('comparison_results') AND name = 'baseline_test_run_id')
BEGIN
    ALTER TABLE comparison_results ADD baseline_test_run_id INT NULL;
    ALTER TABLE comparison_results ADD CONSTRAINT FK_cr_baseline_test_run
        FOREIGN KEY (baseline_test_run_id) REFERENCES baseline_test_runs(id);
END
GO

-- 8. Make test_run_id nullable on comparison_results (can be NULL for baseline-compare)
-- Only if it's currently NOT NULL
IF EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('comparison_results')
    AND name = 'test_run_id'
    AND is_nullable = 0
)
BEGIN
    ALTER TABLE comparison_results ALTER COLUMN test_run_id INT NULL;
END
GO

PRINT 'Baseline-compare migration completed successfully.';
