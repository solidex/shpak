#!/bin/bash
# =================================================================
# StarRocks Uninstall Script for shpak-k8s
# =================================================================
# Usage:
#   ./uninstall_starrocks.sh              - Uninstall (keep PVC)
#   ./uninstall_starrocks.sh --delete-all - Uninstall + delete PVC
# =================================================================

set -e

NAMESPACE="starrocks"
RELEASE_NAME="starrocks"

# Detect MicroK8s
if command -v microk8s &> /dev/null; then
    KUBECTL="microk8s kubectl"
    HELM="microk8s helm3"
else
    KUBECTL="kubectl"
    HELM="helm"
fi

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}==================================================================${NC}"
echo -e "${CYAN}StarRocks Uninstall${NC}"
echo -e "${CYAN}==================================================================${NC}"
echo ""

# Check if installed
if ! $HELM list -n "$NAMESPACE" 2>/dev/null | grep -q "$RELEASE_NAME"; then
    echo -e "${YELLOW}⚠️  StarRocks not installed${NC}"
    exit 0
fi

# Determine what to delete
DELETE_PVC=false
if [ "$1" == "--delete-all" ] || [ "$1" == "-a" ]; then
    DELETE_PVC=true
fi

# Show what will be deleted
echo -e "${CYAN}Current resources:${NC}"
$KUBECTL get pods -n "$NAMESPACE" 2>/dev/null || true
echo ""
$KUBECTL get pvc -n "$NAMESPACE" 2>/dev/null || true
echo ""

# Confirmation
echo -e "${RED}⚠️  WARNING: This will remove StarRocks${NC}"
if [ "$DELETE_PVC" == "true" ]; then
    echo -e "${RED}    and DELETE all data (PVC will be removed)${NC}"
else
    echo -e "${YELLOW}    PVC will be kept (data preserved)${NC}"
fi
echo ""
read -p "Are you sure? (yes/no): " confirm

if [ "$confirm" != "yes" ]; then
    echo -e "${YELLOW}⚠️  Cancelled${NC}"
    exit 0
fi

echo ""
echo -e "${CYAN}▶ Uninstalling Helm release...${NC}"
$HELM uninstall "$RELEASE_NAME" -n "$NAMESPACE"
echo -e "${GREEN}✅ Helm release uninstalled${NC}"

# Wait for pods to terminate
echo -e "${CYAN}▶ Waiting for pods to terminate...${NC}"
sleep 5

# Delete PVC if requested
if [ "$DELETE_PVC" == "true" ]; then
    echo -e "${CYAN}▶ Deleting PVC...${NC}"
    $KUBECTL delete pvc -n "$NAMESPACE" --all --wait=true 2>/dev/null || true
    echo -e "${GREEN}✅ PVC deleted${NC}"
    
    echo -e "${CYAN}▶ Deleting namespace...${NC}"
    $KUBECTL delete namespace "$NAMESPACE" --wait=true 2>/dev/null || true
    echo -e "${GREEN}✅ Namespace deleted${NC}"
else
    echo -e "${YELLOW}⚠️  PVC kept (data preserved)${NC}"
    echo -e "    To delete manually: ${CYAN}$KUBECTL delete pvc --all -n $NAMESPACE${NC}"
fi

echo ""
echo -e "${GREEN}✅ StarRocks uninstalled successfully!${NC}"
echo ""

if [ "$DELETE_PVC" == "false" ]; then
    echo -e "${CYAN}To reinstall with existing data:${NC}"
    echo -e "  ${GREEN}./setup_starrocks.sh install${NC}"
    echo ""
fi

