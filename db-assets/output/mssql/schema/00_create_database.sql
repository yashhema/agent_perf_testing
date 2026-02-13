-- ============================================================
-- Database Creation Script for MSSQL
-- Database: agent_performance_measurement
-- ============================================================
-- IMPORTANT: Run this script FIRST, connected to master/postgres
-- This will DROP the existing database if it exists!
-- ============================================================

-- Switch to master database
USE master;
GO

-- Drop database if exists (with single user mode to close connections)
IF EXISTS (SELECT name FROM sys.databases WHERE name = N'agent_performance_measurement')
BEGIN
    ALTER DATABASE [agent_performance_measurement] SET SINGLE_USER WITH ROLLBACK IMMEDIATE;
    DROP DATABASE [agent_performance_measurement];
END
GO

-- Create database
CREATE DATABASE [agent_performance_measurement];
GO

-- Switch to the new database
USE [agent_performance_measurement];
GO

-- ============================================================
-- Database 'agent_performance_measurement' is ready. Run the following scripts next:
-- 1. 01_create_tables.sql
-- 2. 02_create_indexes.sql
-- 3. 03_create_constraints.sql
-- 4. 04_create_users.sql
-- 5. seed/seed_data.sql
-- ============================================================