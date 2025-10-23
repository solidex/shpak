-- =================================================================
-- StarRocks Database Setup for shpak-k8s
-- =================================================================
-- UTMLogs: 12 полей (оптимизировано)
-- Retention: 365 дней (12 месяцев)
-- Размер: ~84 GB за 12 месяцев (152M записей, 50k пользователей)
-- =================================================================

CREATE DATABASE IF NOT EXISTS RADIUS;
USE RADIUS;

-- =================================================================
-- UTMLogs (12 полей)
-- =================================================================
CREATE TABLE IF NOT EXISTS UTMLogs (
    -- Время события (объединено date + time)
    event_time DATETIME NOT NULL COMMENT 'Event timestamp',
    reporting_date DATE AS DATE(DATE_SUB(event_time, INTERVAL 8 HOUR)) COMMENT 'Reporting date (8:00 AM aligned)',
    
    -- Основные поля
    user VARCHAR(100) NOT NULL COMMENT 'RADIUS username',
    action VARCHAR(20) NULL COMMENT 'accept, deny, block',
    utmtype VARCHAR(50) NULL COMMENT 'webfilter, virus, ips, etc',
    
    -- Источник и назначение
    source VARCHAR(60) NULL COMMENT 'Source IP:port (e.g. 192.168.1.1:54321)',
    destination VARCHAR(60) NULL COMMENT 'Destination IP:port (e.g. 8.8.8.8:443)',
    service VARCHAR(100) NULL COMMENT 'Service name',
    
    -- Web фильтрация
    target TEXT NULL COMMENT 'Hostname or URL',
    category VARCHAR(100) NULL COMMENT 'Web category',
    
    -- Безопасность
    threat VARCHAR(255) NULL COMMENT 'Threat name (virus/attack)',
    level VARCHAR(20) NULL COMMENT 'critical, high, medium, low',
    
    -- Дополнительная информация
    msg TEXT NULL COMMENT 'Log message',
    
    -- Индексы
    INDEX idx_user (user),
    INDEX idx_reporting_date (reporting_date),
    INDEX idx_source (source),
    INDEX idx_utmtype (utmtype),
    INDEX idx_action (action)
)
DUPLICATE KEY(reporting_date, user, event_time)
PARTITION BY RANGE(reporting_date) ()
DISTRIBUTED BY HASH(user) BUCKETS 10
PROPERTIES (
    "replication_num" = "3",
    "storage_medium" = "SSD",
    "enable_persistent_index" = "true",
    "compression" = "LZ4",
    
    "dynamic_partition.enable" = "true",
    "dynamic_partition.time_unit" = "DAY",
    "dynamic_partition.start" = "-365",
    "dynamic_partition.end" = "3",
    "dynamic_partition.prefix" = "p",
    "dynamic_partition.buckets" = "10",
    "dynamic_partition.create_history_partition" = "true"
)
COMMENT 'FortiGate UTM logs (12 fields, 365 days retention)';

-- =================================================================
-- FW_Profiles (без изменений)
-- =================================================================
CREATE TABLE IF NOT EXISTS FW_Profiles (
    login VARCHAR(100) NOT NULL,
    name VARCHAR(100) REPLACE_IF_NOT_NULL NULL,
    id BIGINT REPLACE_IF_NOT_NULL NULL,
    profile_type VARCHAR(50) REPLACE_IF_NOT_NULL NULL,
    can_delete TINYINT REPLACE_IF_NOT_NULL NULL,
    profile_name VARCHAR(100) REPLACE_IF_NOT_NULL NULL,
    created_at DATETIME REPLACE_IF_NOT_NULL NULL,
    updated_at DATETIME REPLACE_IF_NOT_NULL NULL,
    ip_pool VARCHAR(50) REPLACE_IF_NOT_NULL NULL,
    ip_v6_pool VARCHAR(50) REPLACE_IF_NOT_NULL NULL,
    region_id VARCHAR(20) REPLACE_IF_NOT_NULL NULL,
    tcp_rules TEXT REPLACE_IF_NOT_NULL NULL,
    udp_rules TEXT REPLACE_IF_NOT_NULL NULL,
    firewall_profile VARCHAR(50) REPLACE_IF_NOT_NULL NULL,
    hash VARCHAR(64) REPLACE_IF_NOT_NULL NULL,
    policy_id VARCHAR(50) REPLACE_IF_NOT_NULL NULL,
    
    INDEX idx_login (login),
    INDEX idx_hash (hash),
    INDEX idx_policy_id (policy_id)
)
AGGREGATE KEY(`login`)
DISTRIBUTED BY HASH(login) BUCKETS 10
PROPERTIES (
    "replication_num" = "3",
    "compression" = "LZ4"
);

-- =================================================================
-- RADIUS_Sessions (без изменений)
-- =================================================================
CREATE TABLE IF NOT EXISTS RADIUS_Sessions (
    `User_Name` VARCHAR(100) NOT NULL,
    `Timestamp` DATETIME REPLACE_IF_NOT_NULL NULL,
    `Acct_Status_Type` VARCHAR(20) REPLACE_IF_NOT_NULL NULL,
    `Framed_IP_Address` VARCHAR(45) REPLACE_IF_NOT_NULL NULL,
    `Delegated_IPv6_Prefix` VARCHAR(100) REPLACE_IF_NOT_NULL NULL,
    `NAS_IP_Address` VARCHAR(45) REPLACE_IF_NOT_NULL NULL
)
AGGREGATE KEY(`User_Name`)
DISTRIBUTED BY HASH(User_Name) BUCKETS 10
PROPERTIES (
    "replication_num" = "3",
    "compression" = "LZ4"
);

-- =================================================================
-- Materialized Views (обновлены под новую схему)
-- =================================================================

-- MV1: Daily stats
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_utm_daily_user_stats
AS
SELECT 
    reporting_date,
    user,
    COUNT(*) as total_events,
    COUNT(DISTINCT source) as unique_sources,
    COUNT(DISTINCT destination) as unique_destinations,
    SUM(CASE WHEN action = 'deny' THEN 1 ELSE 0 END) as blocked_count,
    SUM(CASE WHEN action = 'accept' THEN 1 ELSE 0 END) as allowed_count,
    SUM(CASE WHEN level IN ('critical', 'high') THEN 1 ELSE 0 END) as high_severity_threats,
    COUNT(DISTINCT CASE WHEN threat IS NOT NULL THEN threat END) as unique_threats
FROM UTMLogs
GROUP BY reporting_date, user;

-- MV2: Hourly threats
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_utm_hourly_threats
AS
SELECT 
    DATE_TRUNC('hour', event_time) as hour,
    user,
    utmtype,
    threat,
    level,
    COUNT(*) as threat_count
FROM UTMLogs
WHERE threat IS NOT NULL
GROUP BY hour, user, utmtype, threat, level;

-- MV3: Top blocked
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_utm_top_blocked
AS
SELECT
    user,
    reporting_date,
    target,
    category,
    COUNT(*) as block_count
FROM UTMLogs
WHERE action = 'deny' AND utmtype = 'webfilter' AND target IS NOT NULL
GROUP BY user, reporting_date, target, category;

SELECT 'Database RADIUS created successfully!' as Status;

