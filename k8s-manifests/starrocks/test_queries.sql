-- =================================================================
-- StarRocks Test Queries for shpak-k8s Project
-- =================================================================
-- Sample analytical queries to test StarRocks performance
-- Usage:
--   mysql -h <NODE-IP> -P 30030 -u root -p < test_queries.sql
-- =================================================================

USE RADIUS;

-- =================================================================
-- 1. Basic Statistics
-- =================================================================

-- Total UTM events
SELECT COUNT(*) as total_events
FROM UTMLogs;

-- Events by user (top 10)
SELECT 
    user,
    COUNT(*) as events,
    MIN(date) as first_seen,
    MAX(date) as last_seen
FROM UTMLogs
GROUP BY user
ORDER BY events DESC
LIMIT 10;

-- Events by date (last 30 days)
SELECT 
    date,
    COUNT(*) as events,
    COUNT(DISTINCT user) as users
FROM UTMLogs
WHERE date >= CURRENT_DATE - INTERVAL 30 DAY
GROUP BY date
ORDER BY date DESC;

-- =================================================================
-- 2. Security Analytics
-- =================================================================

-- Blocked events by user
SELECT 
    user,
    COUNT(*) as blocked_events,
    COUNT(DISTINCT dstip) as unique_destinations
FROM UTMLogs
WHERE action = 'deny' OR action = 'block'
GROUP BY user
ORDER BY blocked_events DESC
LIMIT 20;

-- Critical threats detected
SELECT 
    date,
    user,
    threat,
    utmtype,
    srcip,
    dstip,
    COUNT(*) as occurrences
FROM UTMLogs
WHERE level IN ('critical', 'high')
  AND threat IS NOT NULL
  AND threat != ''
GROUP BY date, user, threat, utmtype, srcip, dstip
ORDER BY date DESC, occurrences DESC
LIMIT 50;

-- Web filtering statistics
SELECT 
    category,
    COUNT(*) as blocks,
    COUNT(DISTINCT user) as users_affected
FROM UTMLogs
WHERE utmtype = 'webfilter'
  AND action IN ('deny', 'block')
GROUP BY category
ORDER BY blocks DESC
LIMIT 20;

-- =================================================================
-- 3. Traffic Analysis
-- =================================================================

-- Top blocked destinations
SELECT 
    dstip,
    dstcountry,
    COUNT(*) as blocks,
    COUNT(DISTINCT user) as users
FROM UTMLogs
WHERE action IN ('deny', 'block')
  AND dstip IS NOT NULL
GROUP BY dstip, dstcountry
ORDER BY blocks DESC
LIMIT 30;

-- Hourly traffic pattern (last 24 hours)
SELECT 
    DATE_TRUNC('hour', event_time) as hour,
    COUNT(*) as events,
    SUM(CASE WHEN action = 'accept' THEN 1 ELSE 0 END) as accepted,
    SUM(CASE WHEN action IN ('deny', 'block') THEN 1 ELSE 0 END) as blocked
FROM UTMLogs
WHERE event_time >= NOW() - INTERVAL 24 HOUR
GROUP BY hour
ORDER BY hour DESC;

-- =================================================================
-- 4. User Behavior Analytics
-- =================================================================

-- Most active users by time of day
SELECT 
    HOUR(event_time) as hour_of_day,
    user,
    COUNT(*) as events
FROM UTMLogs
WHERE date >= CURRENT_DATE - INTERVAL 7 DAY
GROUP BY hour_of_day, user
ORDER BY events DESC
LIMIT 50;

-- Users with most threats detected
SELECT 
    user,
    COUNT(*) as threat_count,
    COUNT(DISTINCT threat) as unique_threats,
    MAX(level) as max_level
FROM UTMLogs
WHERE threat IS NOT NULL AND threat != ''
GROUP BY user
ORDER BY threat_count DESC
LIMIT 20;

-- =================================================================
-- 5. Firewall Profile Analytics
-- =================================================================

-- Profile usage statistics
SELECT 
    fp.login,
    fp.firewall_profile,
    COUNT(utm.user) as utm_events,
    MIN(utm.date) as first_event,
    MAX(utm.date) as last_event
FROM FW_Profiles fp
LEFT JOIN UTMLogs utm ON fp.login = utm.user
GROUP BY fp.login, fp.firewall_profile
ORDER BY utm_events DESC
LIMIT 20;

-- Profiles with most policy changes
SELECT 
    login,
    COUNT(policy_id) as policies_set,
    COUNT(DISTINCT policy_id) as unique_policies,
    MIN(updated_at) as first,
    MAX(updated_at) as last
FROM FW_Profiles
WHERE policy_id IS NOT NULL
GROUP BY login
ORDER BY policies_set DESC
LIMIT 20;

-- =================================================================
-- 6. Performance Test Query
-- =================================================================

-- This query should be FAST in StarRocks (< 2 seconds)
-- In MySQL it would take 30-60 seconds!
SELECT 
    user,
    DATE(event_time) as day,
    COUNT(*) as events,
    COUNT(DISTINCT srcip) as sources,
    COUNT(DISTINCT dstip) as destinations,
    SUM(CASE WHEN action = 'deny' THEN 1 ELSE 0 END) as blocked
FROM UTMLogs
WHERE user = 'testuser'  -- Replace with real username
  AND event_time BETWEEN '2025-01-01' AND '2025-01-31'
GROUP BY user, day
ORDER BY day DESC;

-- =================================================================
-- 7. Data Quality Checks
-- =================================================================

-- Check for NULL critical fields
SELECT 
    'Missing user' as issue,
    COUNT(*) as count
FROM UTMLogs
WHERE user IS NULL OR user = ''
UNION ALL
SELECT 
    'Missing timestamp' as issue,
    COUNT(*) as count
FROM UTMLogs
WHERE date IS NULL OR time IS NULL;

-- Check partition distribution
SELECT 
    CONCAT(YEAR(date), '-', LPAD(MONTH(date), 2, '0')) as partition_month,
    COUNT(*) as events,
    ROUND(COUNT(*) / (SELECT COUNT(*) FROM UTMLogs) * 100, 2) as percent
FROM UTMLogs
GROUP BY partition_month
ORDER BY partition_month DESC
LIMIT 12;

-- =================================================================
-- End of test queries
-- =================================================================

