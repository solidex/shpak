#!/usr/bin/env bash
# =================================================================
# StarRocks Uninstall Script for shpak-k8s
# =================================================================
# Usage:
#   ./uninstall_starrocks.sh                 - Uninstall (keep PVC)
#   ./uninstall_starrocks.sh --delete-all    - Uninstall + delete PVC + namespace
#   ./uninstall_starrocks.sh --delete-repo   - Also remove Helm repository
# =================================================================

# Force bash
if [ -z "$BASH_VERSION" ]; then
    exec bash "$0" "$@"
fi

set -e

NAMESPACE="starrocks"
RELEASE_NAME="kube-starrocks"

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
DELETE_REPO=false

# Parse arguments
for arg in "$@"; do
    if [ "$arg" = "--delete-all" ] || [ "$arg" = "-a" ]; then
        DELETE_PVC=true
    elif [ "$arg" = "--delete-repo" ] || [ "$arg" = "-r" ]; then
        DELETE_REPO=true
    fi
done

# Show what will be deleted
echo -e "${CYAN}Current resources:${NC}"
$KUBECTL get pods -n "$NAMESPACE" 2>/dev/null || true
echo ""
$KUBECTL get pvc -n "$NAMESPACE" 2>/dev/null || true
echo ""

# Confirmation
echo -e "${RED}⚠️  WARNING: This will remove StarRocks${NC}"
if [ "$DELETE_PVC" = "true" ]; then
    echo -e "${RED}    and DELETE all data (PVC will be removed)${NC}"
else
    echo -e "${YELLOW}    PVC will be kept (data preserved)${NC}"
fi
if [ "$DELETE_REPO" = "true" ]; then
    echo -e "${RED}    and REMOVE Helm repository${NC}"
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
sleep 3

# Delete PVC if requested
if [ "$DELETE_PVC" = "true" ]; then
    echo -e "${CYAN}▶ Deleting PVC...${NC}"
    
    # Try graceful delete first (with timeout)
    $KUBECTL delete pvc -n "$NAMESPACE" --all --timeout=30s 2>/dev/null || {
        echo -e "${YELLOW}⚠️  Graceful delete timeout, forcing...${NC}"
        # Force delete by removing finalizers
        for pvc in $($KUBECTL get pvc -n "$NAMESPACE" -o name 2>/dev/null); do
            $KUBECTL patch $pvc -n "$NAMESPACE" -p '{"metadata":{"finalizers":null}}' --type=merge 2>/dev/null || true
        done
        $KUBECTL delete pvc -n "$NAMESPACE" --all --grace-period=0 --force 2>/dev/null || true
    }
    echo -e "${GREEN}✅ PVC deleted${NC}"
    
    echo -e "${CYAN}▶ Deleting namespace...${NC}"
    $KUBECTL delete namespace "$NAMESPACE" --timeout=30s 2>/dev/null || {
        echo -e "${YELLOW}⚠️  Force deleting namespace...${NC}"
        $KUBECTL delete namespace "$NAMESPACE" --grace-period=0 --force 2>/dev/null || true
    }
    echo -e "${GREEN}✅ Namespace deleted${NC}"
else
    echo -e "${YELLOW}⚠️  PVC kept (data preserved)${NC}"
    echo -e "    To delete manually: ${CYAN}$KUBECTL delete pvc --all -n $NAMESPACE${NC}"
fi

echo ""

# Remove Helm repository if requested
if [ "$DELETE_REPO" = "true" ]; then
    echo -e "${CYAN}▶ Removing Helm repository...${NC}"
    if $HELM repo list 2>/dev/null | grep -q "^starrocks"; then
        $HELM repo remove starrocks 2>/dev/null || true
        echo -e "${GREEN}✅ Helm repository removed${NC}"
    else
        echo -e "${YELLOW}⚠️  Helm repository not found${NC}"
    fi
    echo ""
fi

echo -e "${GREEN}✅ StarRocks uninstalled successfully!${NC}"
echo ""

if [ "$DELETE_PVC" = "false" ]; then
    echo -e "${CYAN}To reinstall with existing data:${NC}"
    echo -e "  ${GREEN}./setup_starrocks.sh install${NC}"
    echo ""
fi

