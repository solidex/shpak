-- =================================================================
-- StarRocks Database Setup for shpak-k8s Project
-- =================================================================
-- This script creates the RADIUS database and all necessary tables
-- for analytical queries on UTM logs, firewall profiles, and policy logs
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
-- Retention: Unlimited (with automatic partitioning)
-- =================================================================

CREATE TABLE IF NOT EXISTS UTMLogs (
    -- Event action
    action VARCHAR(50) COMMENT 'Action taken: accept, deny, block',
    
    -- Date and time (separated for FortiGate compatibility)
    date DATE COMMENT 'Event date (YYYY-MM-DD)',
    time VARCHAR(20) COMMENT 'Event time (HH:MM:SS)',
    event_time DATETIME AS CONCAT(date, ' ', time) COMMENT 'Computed datetime for queries',
    
    -- Destination information
    dstcountry VARCHAR(50) COMMENT 'Destination country',
    dstip VARCHAR(45) COMMENT 'Destination IP address (IPv4/IPv6)',
    dstport INT COMMENT 'Destination port',
    
    -- Event metadata
    eventtype VARCHAR(50) COMMENT 'Event type: utm, traffic, etc.',
    ipaddr VARCHAR(45) COMMENT 'IP address of the event source',
    msg TEXT COMMENT 'Log message',
    
    -- Source information
    srccountry VARCHAR(50) COMMENT 'Source country',
    srcip VARCHAR(45) COMMENT 'Source IP address (IPv4/IPv6)',
    
    -- UTM specific
    utmtype VARCHAR(50) COMMENT 'UTM subtype: webfilter, virus, ips, etc.',
    user VARCHAR(100) COMMENT 'Username (RADIUS login)',
    category VARCHAR(100) COMMENT 'Web category or threat category',
    hostname VARCHAR(255) COMMENT 'Destination hostname or domain',
    service VARCHAR(100) COMMENT 'Service name',
    url TEXT COMMENT 'Requested URL',
    httpagent TEXT COMMENT 'HTTP User-Agent',
    level VARCHAR(20) COMMENT 'Threat level: critical, high, medium, low',
    threat VARCHAR(255) COMMENT 'Threat name (virus/attack signature)',
    
    -- Indexes
    INDEX idx_user (user),
    INDEX idx_date (date),
    INDEX idx_srcip (srcip),
    INDEX idx_utmtype (utmtype)
)
DUPLICATE KEY(date, user, event_time)
PARTITION BY RANGE(date) (
    START ("2024-01-01") END ("2027-12-31") EVERY (INTERVAL 1 MONTH)
)
DISTRIBUTED BY HASH(user) BUCKETS 10
PROPERTIES (
    "replication_num" = "3",
    "storage_medium" = "SSD",
    "enable_persistent_index" = "true",
    "compression" = "LZ4"
)
COMMENT 'FortiGate UTM security logs (analytical storage)';

-- =================================================================
-- Table 2: firewall_profiles (Read-only analytical copy)
-- =================================================================
-- Firewall profiles for users
-- Source: MySQL firewall_profiles table (replicated for analytics)
-- =================================================================

CREATE TABLE IF NOT EXISTS FW_Profiles (
    id BIGINT COMMENT 'Profile ID',
    profile_type VARCHAR(50) COMMENT 'Profile type: billing, custom',
    can_delete TINYINT COMMENT 'Can be deleted: 0=no, 1=yes',
    profile_name VARCHAR(100) COMMENT 'Profile name',
    created_at DATETIME COMMENT 'Created timestamp',
    updated_at DATETIME COMMENT 'Updated timestamp',
    name VARCHAR(100) COMMENT 'User full name',
    login VARCHAR(100) COMMENT 'User login (RADIUS User-Name)',
    ip_pool VARCHAR(50) COMMENT 'IPv4 pool',
    ip_v6_pool VARCHAR(50) COMMENT 'IPv6 pool',
    region_id VARCHAR(20) COMMENT 'Region identifier',
    tcp_rules TEXT COMMENT 'TCP port rules (comma-separated)',
    udp_rules TEXT COMMENT 'UDP port rules (comma-separated)',
    firewall_profile VARCHAR(50) COMMENT 'FortiGate profile reference',
    hash VARCHAR(64) COMMENT 'MD5 hash of tcp_rules|udp_rules',
    policy_id VARCHAR(50) COMMENT 'FortiGate policy ID',
    
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
COMMENT 'Firewall profiles (analytical copy from MySQL)';

-- Removed PolicyLogs: policy_id is stored in FW_Profiles (simplified architecture)

-- =================================================================
-- Table 4: RADIUS_Sessions (Active sessions - optional)
-- =================================================================
-- Active RADIUS sessions (Accounting-Start without Stop)
-- Note: Main OLTP table remains in MySQL, this is for analytics
-- =================================================================

CREATE TABLE IF NOT EXISTS RADIUS_Sessions (
    `User_Name` VARCHAR(100) COMMENT 'RADIUS User-Name',
    `Timestamp` DATETIME COMMENT 'Session start timestamp',
    `Acct_Status_Type` VARCHAR(20) COMMENT 'Accounting status: Start, Stop',
    `Framed_IP_Address` VARCHAR(45) COMMENT 'Assigned IPv4 address',
    `Delegated_IPv6_Prefix` VARCHAR(100) COMMENT 'Assigned IPv6 prefix',
    `NAS_IP_Address` VARCHAR(45) COMMENT 'NAS (RADIUS server) IP'
)
AGGREGATE KEY(`User_Name`)
DISTRIBUTED BY HASH(User_Name) BUCKETS 10
PROPERTIES (
    "replication_num" = "3",
    "compression" = "LZ4"
)
COMMENT 'RADIUS accounting sessions (analytical copy)';

-- =================================================================
-- Materialized Views (Pre-computed analytics)
-- =================================================================

-- Daily UTM statistics per user
CREATE MATERIALIZED VIEW IF NOT EXISTS utm_daily_stats
AS
SELECT 
    date,
    user,
    COUNT(*) as event_count,
    COUNT(DISTINCT srcip) as unique_sources,
    COUNT(DISTINCT dstip) as unique_destinations,
    SUM(CASE WHEN action = 'deny' THEN 1 ELSE 0 END) as blocked_count,
    SUM(CASE WHEN action = 'accept' THEN 1 ELSE 0 END) as allowed_count,
    SUM(CASE WHEN level IN ('critical', 'high') THEN 1 ELSE 0 END) as high_threats
FROM UTMLogs
GROUP BY date, user;

-- Hourly threat statistics
CREATE MATERIALIZED VIEW IF NOT EXISTS utm_hourly_threats
AS
SELECT 
    DATE_TRUNC('hour', event_time) as hour,
    utmtype,
    threat,
    COUNT(*) as threat_count,
    COUNT(DISTINCT user) as affected_users
FROM UTMLogs
WHERE threat IS NOT NULL AND threat != ''
GROUP BY hour, utmtype, threat;

-- =================================================================
-- Indexes for performance (optional, StarRocks auto-optimizes)
-- =================================================================

-- Bitmap indexes for categorical columns (very efficient in StarRocks)
-- Note: StarRocks automatically creates indexes based on query patterns

-- =================================================================
-- Verification queries
-- =================================================================

-- Show all tables
SHOW TABLES;

-- Show table structure
DESC UTMLogs;
DESC firewall_profiles;
DESC PolicyLogs;

-- Show partitions
SHOW PARTITIONS FROM UTMLogs;

-- Show materialized views
SHOW MATERIALIZED VIEWS FROM RADIUS;

-- =================================================================
-- Sample queries for testing
-- =================================================================

-- Count UTM logs by user (should be fast)
-- SELECT user, COUNT(*) as events
-- FROM UTMLogs
-- GROUP BY user
-- ORDER BY events DESC
-- LIMIT 10;

-- Daily threat statistics
-- SELECT 
--     date,
--     COUNT(*) as total_events,
--     COUNT(DISTINCT user) as users_affected,
--     SUM(CASE WHEN level = 'critical' THEN 1 ELSE 0 END) as critical_threats
-- FROM UTMLogs
-- WHERE date >= CURRENT_DATE - INTERVAL 7 DAY
-- GROUP BY date
-- ORDER BY date DESC;

-- =================================================================
-- Success message
-- =================================================================

SELECT 
    'Database RADIUS created successfully!' as Status,
    COUNT(*) as Tables
FROM information_schema.tables
WHERE table_schema = 'RADIUS';

