#!/bin/bash
# =================================================================
# StarRocks Setup Script for shpak-k8s Project
# =================================================================
# This script:
# 1. Waits for StarRocks to be ready
# 2. Creates RADIUS database and tables
# 3. Verifies the setup
# =================================================================

set -e

# Configuration
NAMESPACE="starrocks"
NODE_IP="${1:-}"  # First argument: node IP
STARROCKS_PORT="30030"
STARROCKS_USER="root"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo -e "${CYAN}==================================================================${NC}"
echo -e "${CYAN}StarRocks Setup for shpak-k8s Project${NC}"
echo -e "${CYAN}==================================================================${NC}"
echo ""

# Check if kubectl is available
if ! command -v kubectl &> /dev/null; then
    echo -e "${RED}❌ kubectl not found. Please install kubectl first.${NC}"
    exit 1
fi

# Check if mysql client is available
if ! command -v mysql &> /dev/null; then
    echo -e "${YELLOW}⚠️  mysql client not found. Installing...${NC}"
    # Try to install (Ubuntu/Debian)
    if command -v apt-get &> /dev/null; then
        sudo apt-get update && sudo apt-get install -y mysql-client
    else
        echo -e "${RED}❌ Please install mysql client manually${NC}"
        exit 1
    fi
fi

echo -e "${CYAN}📋 Step 1: Checking StarRocks installation...${NC}"

# Check if StarRocks pods are running
if ! kubectl get pods -n "$NAMESPACE" -l app.kubernetes.io/instance=starrocks &> /dev/null; then
    echo -e "${RED}❌ StarRocks not found in namespace '${NAMESPACE}'${NC}"
    echo -e "${YELLOW}   Please install StarRocks first:${NC}"
    echo -e "   helm install starrocks starrocks/kube-starrocks -n starrocks -f starrocks-values.yaml"
    exit 1
fi

echo -e "${GREEN}✅ StarRocks found${NC}"

# Wait for FE pods to be ready
echo -e "${CYAN}⏳ Waiting for StarRocks FE pods to be ready...${NC}"
kubectl wait --for=condition=ready pod \
    -l app.kubernetes.io/component=fe \
    -n "$NAMESPACE" \
    --timeout=300s

echo -e "${GREEN}✅ StarRocks FE pods are ready${NC}"
echo ""

# Get node IP if not provided
if [ -z "$NODE_IP" ]; then
    echo -e "${CYAN}🔍 Detecting node IP...${NC}"
    NODE_IP=$(kubectl get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}')
    if [ -z "$NODE_IP" ]; then
        echo -e "${RED}❌ Could not detect node IP. Please provide it as first argument:${NC}"
        echo -e "   ./setup_starrocks.sh <NODE-IP>"
        exit 1
    fi
    echo -e "${GREEN}✅ Detected node IP: ${NODE_IP}${NC}"
fi

echo ""
echo -e "${CYAN}📊 Step 2: Creating RADIUS database and tables...${NC}"

# Prompt for password
echo -e "${YELLOW}Enter StarRocks root password:${NC}"
read -s STARROCKS_PASSWORD
echo ""

# Create database using SQL file
echo -e "${CYAN}Executing create_database.sql...${NC}"

mysql -h "$NODE_IP" -P "$STARROCKS_PORT" -u "$STARROCKS_USER" -p"$STARROCKS_PASSWORD" < create_database.sql

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ Database and tables created successfully!${NC}"
else
    echo -e "${RED}❌ Failed to create database. Check the error above.${NC}"
    exit 1
fi

echo ""
echo -e "${CYAN}📋 Step 3: Verifying setup...${NC}"

# Verify tables
TABLES=$(mysql -h "$NODE_IP" -P "$STARROCKS_PORT" -u "$STARROCKS_USER" -p"$STARROCKS_PASSWORD" \
    -e "USE RADIUS; SHOW TABLES;" 2>/dev/null | grep -v Tables_in | wc -l)

echo -e "${GREEN}✅ Created $TABLES tables in RADIUS database${NC}"

# Show table details
echo ""
echo -e "${CYAN}📊 Table details:${NC}"
mysql -h "$NODE_IP" -P "$STARROCKS_PORT" -u "$STARROCKS_USER" -p"$STARROCKS_PASSWORD" \
    -e "USE RADIUS; 
        SELECT 
            TABLE_NAME, 
            TABLE_ROWS as 'Rows',
            ROUND(DATA_LENGTH / 1024 / 1024, 2) as 'Size_MB'
        FROM information_schema.TABLES 
        WHERE TABLE_SCHEMA = 'RADIUS' 
        ORDER BY TABLE_NAME;"

echo ""
echo -e "${CYAN}==================================================================${NC}"
echo -e "${GREEN}✅ StarRocks setup completed successfully!${NC}"
echo -e "${CYAN}==================================================================${NC}"
echo ""
echo -e "${YELLOW}📝 Next steps:${NC}"
echo ""
echo -e "1. Update app/config/env.txt with StarRocks settings:"
echo -e "   ${CYAN}STARROCKS_HOST=${NODE_IP}${NC}"
echo -e "   ${CYAN}STARROCKS_PORT=30030${NC}"
echo -e "   ${CYAN}STARROCKS_USER=root${NC}"
echo -e "   ${CYAN}STARROCKS_PASSWORD=<your-password>${NC}"
echo -e "   ${CYAN}STARROCKS_DB=RADIUS${NC}"
echo ""
echo -e "2. Use mhe_log_starrocks.py for dual write (MySQL + StarRocks)"
echo ""
echo -e "3. Update mhe_email.py to query StarRocks for reports:"
echo -e "   ${CYAN}mysql -h ${NODE_IP} -P 30030 -u root -p${NC}"
echo ""
echo -e "4. Test query performance:"
echo -e "   ${CYAN}SELECT COUNT(*) FROM RADIUS.UTMLogs;${NC}"
echo ""
echo -e "5. Access Web UI:"
echo -e "   ${CYAN}http://${NODE_IP}:30080${NC}"
echo ""

