-- =================================================================
-- StarRocks Database Setup for shpak-k8s Project
-- =================================================================
-- This script creates the RADIUS database and all necessary tables
-- for UTM logs, firewall profiles, RADIUS sessions, and policy logs
--
-- Usage:
--   mysql -h <NODE-IP> -P 30030 -u root -p < create_database.sql
--
-- Or from MicroK8s:
--   microk8s kubectl exec -it starrocks-fe-0 -n starrocks -- \
--     mysql -u root -p < /tmp/create_database.sql
-- =================================================================

-- Create database
CREATE DATABASE IF NOT EXISTS RADIUS;
USE RADIUS;

-- =================================================================
-- Table 1: UTMLogs (Main analytical table)
-- =================================================================
-- FortiGate UTM security logs
-- Expected volume: 50,000+ events/day
-- Retention: 60 reporting days (auto-cleanup via dynamic partitioning)
-- Partitions aligned to 8:00 AM (reporting_date = DATE(event_time - 8 hours))
-- Events 00:00-07:59 belong to previous reporting day
-- Partitions are created automatically and deleted after 60 days
-- =================================================================

CREATE TABLE IF NOT EXISTS UTMLogs (
    -- Event action
    action VARCHAR(50) NULL COMMENT 'Action taken: accept, deny, block',
    
    -- Date and time (separated for FortiGate compatibility)
    date DATE NULL COMMENT 'Event date (YYYY-MM-DD)',
    time VARCHAR(20) NULL COMMENT 'Event time (HH:MM:SS)',
    event_time DATETIME AS CONCAT(date, ' ', time) COMMENT 'Computed datetime for queries',
    reporting_date DATE AS DATE(DATE_SUB(event_time, INTERVAL 8 HOUR)) COMMENT 'Reporting date: day starts at 8:00 AM (events 00:00-07:59 belong to previous day)',
    
    -- Destination information
    dstcountry VARCHAR(50) NULL COMMENT 'Destination country',
    dstip VARCHAR(45) NULL COMMENT 'Destination IP address (IPv4/IPv6)',
    dstport INT NULL COMMENT 'Destination port',
    
    -- Event metadata
    eventtype VARCHAR(50) NULL COMMENT 'Event type: utm, traffic, etc.',
    ipaddr VARCHAR(45) NULL COMMENT 'IP address of the event source',
    msg TEXT NULL COMMENT 'Log message',
    
    -- Source information
    srccountry VARCHAR(50) NULL COMMENT 'Source country',
    srcip VARCHAR(45) NULL COMMENT 'Source IP address (IPv4/IPv6)',
    
    -- UTM specific
    utmtype VARCHAR(50) NULL COMMENT 'UTM subtype: webfilter, virus, ips, etc.',
    user VARCHAR(100) NOT NULL COMMENT 'Username (RADIUS login)',
    category VARCHAR(100) NULL COMMENT 'Web category or threat category',
    hostname VARCHAR(255) NULL COMMENT 'Destination hostname or domain',
    service VARCHAR(100) NULL COMMENT 'Service name',
    url TEXT NULL COMMENT 'Requested URL',
    httpagent TEXT NULL COMMENT 'HTTP User-Agent',
    level VARCHAR(20) NULL COMMENT 'Threat level: critical, high, medium, low',
    threat VARCHAR(255) NULL COMMENT 'Threat name (virus/attack signature)',
    
    -- Indexes
    INDEX idx_user (user),
    INDEX idx_date (date),
    INDEX idx_reporting_date (reporting_date),
    INDEX idx_srcip (srcip),
    INDEX idx_utmtype (utmtype)
)
DUPLICATE KEY(reporting_date, user, event_time)
PARTITION BY RANGE(reporting_date) ()
DISTRIBUTED BY HASH(user) BUCKETS 10
PROPERTIES (
    "replication_num" = "3",
    "storage_medium" = "SSD",
    "enable_persistent_index" = "true",
    "compression" = "LZ4",
    
    -- Dynamic partitioning with auto-cleanup (older than 60 days)
    -- Partitions aligned to reporting days (8:00 AM - 8:00 AM)
    "dynamic_partition.enable" = "true",
    "dynamic_partition.time_unit" = "DAY",
    "dynamic_partition.start" = "-60",
    "dynamic_partition.end" = "3",
    "dynamic_partition.prefix" = "p",
    "dynamic_partition.buckets" = "10",
    "dynamic_partition.create_history_partition" = "true"
)
COMMENT 'FortiGate UTM security logs (primary storage)';

-- =================================================================
-- Table 2: FW_Profiles (Firewall profiles)
-- =================================================================
-- Firewall profiles for users (Read-Write)
-- Primary storage for user firewall configurations
-- =================================================================

CREATE TABLE IF NOT EXISTS FW_Profiles (
    login VARCHAR(100) NOT NULL COMMENT 'User login (RADIUS User-Name)',
    name VARCHAR(100) REPLACE_IF_NOT_NULL NULL COMMENT 'User full name',
    id BIGINT REPLACE_IF_NOT_NULL NULL COMMENT 'Profile ID',
    profile_type VARCHAR(50) REPLACE_IF_NOT_NULL NULL COMMENT 'Profile type: billing, custom',
    can_delete TINYINT REPLACE_IF_NOT_NULL NULL COMMENT 'Can be deleted: 0=no, 1=yes',
    profile_name VARCHAR(100) REPLACE_IF_NOT_NULL NULL COMMENT 'Profile name',
    created_at DATETIME REPLACE_IF_NOT_NULL NULL COMMENT 'Created timestamp',
    updated_at DATETIME REPLACE_IF_NOT_NULL NULL COMMENT 'Updated timestamp',
    ip_pool VARCHAR(50) REPLACE_IF_NOT_NULL NULL COMMENT 'IPv4 pool',
    ip_v6_pool VARCHAR(50) REPLACE_IF_NOT_NULL NULL COMMENT 'IPv6 pool',
    region_id VARCHAR(20) REPLACE_IF_NOT_NULL NULL COMMENT 'Region identifier',
    tcp_rules TEXT REPLACE_IF_NOT_NULL NULL COMMENT 'TCP port rules (comma-separated)',
    udp_rules TEXT REPLACE_IF_NOT_NULL NULL COMMENT 'UDP port rules (comma-separated)',
    firewall_profile VARCHAR(50) REPLACE_IF_NOT_NULL NULL COMMENT 'FortiGate profile reference',
    hash VARCHAR(64) REPLACE_IF_NOT_NULL NULL COMMENT 'MD5 hash of tcp_rules|udp_rules',
    policy_id VARCHAR(50) REPLACE_IF_NOT_NULL NULL COMMENT 'FortiGate policy ID',
    
    INDEX idx_login (login),
    INDEX idx_hash (hash),
    INDEX idx_policy_id (policy_id)
)
AGGREGATE KEY(`login`)
DISTRIBUTED BY HASH(login) BUCKETS 10
PROPERTIES (
    "replication_num" = "3",
    "compression" = "LZ4"
)
COMMENT 'Firewall profiles for users (primary storage)';

-- Removed PolicyLogs: policy_id is stored in FW_Profiles (simplified architecture)

-- =================================================================
-- Table 3: RADIUS_Sessions (Active sessions)
-- =================================================================
-- Active RADIUS sessions (Read-Write)
-- Stores RADIUS accounting data (Start/Stop events)
-- =================================================================

CREATE TABLE IF NOT EXISTS RADIUS_Sessions (
    `User_Name` VARCHAR(100) NOT NULL COMMENT 'RADIUS User-Name',
    `Timestamp` DATETIME REPLACE_IF_NOT_NULL NULL COMMENT 'Session start timestamp',
    `Acct_Status_Type` VARCHAR(20) REPLACE_IF_NOT_NULL NULL COMMENT 'Accounting status: Start, Stop',
    `Framed_IP_Address` VARCHAR(45) REPLACE_IF_NOT_NULL NULL COMMENT 'Assigned IPv4 address',
    `Delegated_IPv6_Prefix` VARCHAR(100) REPLACE_IF_NOT_NULL NULL COMMENT 'Assigned IPv6 prefix',
    `NAS_IP_Address` VARCHAR(45) REPLACE_IF_NOT_NULL NULL COMMENT 'NAS (RADIUS server) IP'
)
AGGREGATE KEY(`User_Name`)
DISTRIBUTED BY HASH(User_Name) BUCKETS 10
PROPERTIES (
    "replication_num" = "3",
    "compression" = "LZ4"
)
COMMENT 'RADIUS accounting sessions (primary storage)';

-- =================================================================
-- Materialized Views (Pre-computed analytics)
-- =================================================================
-- These views match actual SELECT queries from the application code
-- and optimize performance for frequently accessed data patterns
--
-- Performance benefits:
--   - mv_utm_daily_user_stats: Speeds up daily reports in mhe_email.py
--   - mv_utm_hourly_threats: Real-time threat monitoring dashboard
--   - mv_utm_user_event_types: Analytics API queries
--   - mv_utm_top_blocked: Webfilter statistics and reports
--
-- Maintenance:
--   - Automatically updated when new data inserted into UTMLogs
--   - No manual refresh required (StarRocks async materialization)
--   - Storage overhead: ~5-10% of base table size
-- =================================================================

-- MV1: Daily UTM statistics per user (for dashboard and summary reports)
-- Uses reporting_date (8:00 AM - 8:00 AM aligned partitions)
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_utm_daily_user_stats
AS
SELECT 
    reporting_date,
    user,
    COUNT(*) as total_events,
    COUNT(DISTINCT srcip) as unique_sources,
    COUNT(DISTINCT dstip) as unique_destinations,
    COUNT(DISTINCT CASE WHEN utmtype = 'webfilter' THEN url END) as unique_urls,
    SUM(CASE WHEN action = 'deny' THEN 1 ELSE 0 END) as blocked_count,
    SUM(CASE WHEN action = 'accept' THEN 1 ELSE 0 END) as allowed_count,
    SUM(CASE WHEN level IN ('critical', 'high') THEN 1 ELSE 0 END) as high_severity_threats,
    COUNT(DISTINCT CASE WHEN threat IS NOT NULL AND threat != '' THEN threat END) as unique_threats,
    MAX(CASE WHEN level = 'critical' THEN threat END) as worst_threat
FROM UTMLogs
GROUP BY reporting_date, user;

-- MV2: Hourly threat statistics (for real-time monitoring)
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_utm_hourly_threats
AS
SELECT 
    DATE_TRUNC('hour', event_time) as hour,
    user,
    utmtype,
    threat,
    level,
    COUNT(*) as threat_count,
    COUNT(DISTINCT srcip) as source_ips,
    COUNT(DISTINCT dstip) as target_ips
FROM UTMLogs
WHERE threat IS NOT NULL AND threat != ''
GROUP BY hour, user, utmtype, threat, level;

-- MV3: UTM event type breakdown per user (for analytics dashboard)
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_utm_user_event_types
AS
SELECT
    user,
    reporting_date,
    utmtype,
    action,
    COUNT(*) as event_count,
    COUNT(DISTINCT srcip) as unique_sources,
    COUNT(DISTINCT dstip) as unique_destinations
FROM UTMLogs
GROUP BY user, reporting_date, utmtype, action;

-- MV4: Top blocked URLs/domains per user (for webfilter analysis)
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_utm_top_blocked
AS
SELECT
    user,
    reporting_date,
    hostname,
    category,
    COUNT(*) as block_count
FROM UTMLogs
WHERE action = 'deny' AND utmtype = 'webfilter' AND hostname IS NOT NULL
GROUP BY user, reporting_date, hostname, category;

-- =================================================================
-- Note: Why some tables don't need Materialized Views
-- =================================================================
--
-- 1. UTMLogs detailed queries (mhe_email.py):
--    Query: SELECT all_columns FROM UTMLogs 
--           WHERE user=? AND event_time BETWEEN ? AND ?
--    Reason: Needs ALL columns for email reports (not aggregated data)
--    Solution: Uses base table with computed column event_time and indexes
--              (idx_user, idx_date) for optimal performance
--
-- 2. FW_Profiles queries (routes_firewall.py, routes_query.py, routes_radius.py):
--    - SELECT * FROM FW_Profiles WHERE login = ? (idx_login)
--    - SELECT policy_id FROM FW_Profiles WHERE hash = ? (idx_hash)
--    - SELECT COUNT(*) FROM FW_Profiles WHERE policy_id = ? (idx_policy_id)
--    - SELECT * FROM FW_Profiles WHERE id = ? (primary key)
--    Reason: Point lookups already optimized by indexes
--
-- 3. RADIUS_Sessions queries (routes_firewall.py, routes_radius.py):
--    - SELECT * FROM RADIUS_Sessions WHERE User_Name = ? (aggregate key)
--    - DELETE FROM RADIUS_Sessions WHERE User_Name = ? (aggregate key)
--    Reason: Point lookups using AGGREGATE KEY are extremely fast
--
-- MVs are beneficial ONLY for aggregated/pre-computed data, not raw selects.
-- =================================================================

-- =================================================================
-- Indexes for performance (optional, StarRocks auto-optimizes)
-- =================================================================

-- Bitmap indexes for categorical columns (very efficient in StarRocks)
-- Note: StarRocks automatically creates indexes based on query patterns

-- =================================================================
-- Dynamic Partition Management (Optional)
-- =================================================================

-- To change retention period (e.g., to 90 days):
-- ALTER TABLE UTMLogs SET ("dynamic_partition.start" = "-90");

-- To disable dynamic partitioning:
-- ALTER TABLE UTMLogs SET ("dynamic_partition.enable" = "false");

-- To manually drop specific old partition:
-- ALTER TABLE UTMLogs DROP PARTITION p20240101;

-- =================================================================
-- Reporting Date Partitioning Explanation
-- =================================================================
-- Partitions are aligned to 8:00 AM (not midnight) using reporting_date
--
-- Timeline example for October 22, 2025:
--   00:00 ─────── 07:59 │ 08:00 ──────── 23:59
--   reporting_date:     │ reporting_date:
--   2025-10-21         │ 2025-10-22
--                      │
--   [Partition p20251021] │ [Partition p20251022]
--
-- Benefits:
--   1. Daily reports (8:00-8:00) fit into single partition (faster queries)
--   2. Automatic cleanup at reporting day boundaries
--   3. Consistent with mhe_email.py report windows
-- =================================================================

-- =================================================================
-- Verification queries
-- =================================================================

-- Show all tables
SHOW TABLES;

-- Show table structure
DESC UTMLogs;
DESC firewall_profiles;
DESC PolicyLogs;

-- Show partitions (should auto-create and auto-delete)
SHOW PARTITIONS FROM UTMLogs;

-- Show dynamic partition settings
SHOW DYNAMIC PARTITION TABLES FROM RADIUS;

-- Show materialized views
SHOW MATERIALIZED VIEWS FROM RADIUS;

-- =================================================================
-- Sample queries for testing (using Materialized Views)
-- =================================================================

-- Query 1: Get daily stats for specific user (uses mv_utm_daily_user_stats)
-- SELECT * FROM mv_utm_daily_user_stats 
-- WHERE user = 'john.doe@example.com' 
-- AND reporting_date >= CURRENT_DATE - INTERVAL 7 DAY
-- ORDER BY reporting_date DESC;

-- Query 2: Find users with most blocked events (uses mv_utm_daily_user_stats)
-- SELECT user, SUM(blocked_count) as total_blocked
-- FROM mv_utm_daily_user_stats
-- WHERE reporting_date >= CURRENT_DATE - INTERVAL 7 DAY
-- GROUP BY user
-- ORDER BY total_blocked DESC
-- LIMIT 10;

-- Query 3: Hourly threat detection (uses mv_utm_hourly_threats)
-- SELECT hour, threat, level, SUM(threat_count) as total
-- FROM mv_utm_hourly_threats
-- WHERE hour >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
-- GROUP BY hour, threat, level
-- ORDER BY hour DESC, total DESC;

-- Query 4: Top blocked websites per user (uses mv_utm_top_blocked)
-- SELECT hostname, category, SUM(block_count) as total_blocks
-- FROM mv_utm_top_blocked
-- WHERE user = 'john.doe@example.com' AND reporting_date >= CURRENT_DATE - INTERVAL 7 DAY
-- GROUP BY hostname, category
-- ORDER BY total_blocks DESC
-- LIMIT 20;

-- Query 5: Raw event details for daily reports (uses base table UTMLogs)
-- Optimized query used by mhe_email.py - uses computed column event_time
-- SELECT action, date, time, dstcountry, dstip, dstport, eventtype, ipaddr, msg,
--        srccountry, srcip, utmtype, user, category, hostname, service, url, 
--        httpagent, level, threat
-- FROM UTMLogs
-- WHERE user = 'john.doe@example.com'
-- AND event_time >= '2025-10-21 08:00:00' AND event_time < '2025-10-22 08:00:00'
-- ORDER BY event_time ASC;

-- Query 6: Recent events for specific user (with limit)
-- Uses reporting_date for partition pruning (faster than date)
-- SELECT date, time, action, utmtype, hostname, url, threat, level, reporting_date
-- FROM UTMLogs
-- WHERE user = 'john.doe@example.com' AND reporting_date >= CURRENT_DATE - INTERVAL 1 DAY
-- ORDER BY event_time DESC
-- LIMIT 100;

-- Query 7: Example showing reporting_date benefit
-- Event at 2025-10-22 03:00 has reporting_date = 2025-10-21 (belongs to 21st report)
-- Event at 2025-10-22 08:00 has reporting_date = 2025-10-22 (belongs to 22nd report)
-- SELECT date, time, event_time, reporting_date
-- FROM UTMLogs
-- WHERE user = 'john.doe@example.com'
-- ORDER BY event_time DESC
-- LIMIT 10;

-- =================================================================
-- Success message
-- =================================================================

SELECT 
    'Database RADIUS created successfully!' as Status,
    COUNT(*) as Tables
FROM information_schema.tables
WHERE table_schema = 'RADIUS';

