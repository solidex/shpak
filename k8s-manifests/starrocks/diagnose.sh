#!/usr/bin/env bash
# =================================================================
# StarRocks Diagnostics - Collect all info
# =================================================================

set -e

# Detect MicroK8s
if command -v microk8s &> /dev/null; then
    KUBECTL="microk8s kubectl"
    HELM="microk8s helm3"
else
    KUBECTL="kubectl"
    HELM="helm"
fi

NAMESPACE="starrocks"
OUTPUT_FILE="starrocks-diagnostics-$(date +%Y%m%d-%H%M%S).txt"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

print_header() {
    echo -e "${CYAN}===================================================================${NC}"
    echo -e "${CYAN}$1${NC}"
    echo -e "${CYAN}===================================================================${NC}"
}

print_step() {
    echo -e "${CYAN}▶ $1${NC}"
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

echo ""
print_header "StarRocks Diagnostics Collection"
echo ""
print_step "Collecting comprehensive diagnostics..."
echo -e "${YELLOW}Output file: $OUTPUT_FILE${NC}"
echo ""

{
    echo "==================================================================="
    echo "StarRocks Diagnostics Report"
    echo "Generated: $(date)"
    echo "==================================================================="
    echo ""
    
    echo "=== CLUSTER INFO ==="
    echo "Kubectl version:"
    $KUBECTL version --short 2>/dev/null || echo "kubectl version N/A"
    echo ""
    echo "Helm version:"
    $HELM version --short 2>/dev/null || echo "helm version N/A"
    echo ""
    
    echo "=== NODES ==="
    $KUBECTL get nodes -o wide
    echo ""
    
    echo "=== STORAGE CLASSES ==="
    $KUBECTL get storageclass
    echo ""
    
    echo "=== NAMESPACE ==="
    $KUBECTL get namespace $NAMESPACE 2>/dev/null || echo "Namespace '$NAMESPACE' not found"
    echo ""
    
    echo "=== HELM RELEASES ==="
    $HELM list -n $NAMESPACE 2>/dev/null || echo "No helm releases in namespace '$NAMESPACE'"
    echo ""
    
    echo "=== PODS ==="
    $KUBECTL get pods -n $NAMESPACE -o wide 2>/dev/null || echo "No pods in namespace '$NAMESPACE'"
    echo ""
    
    echo "=== SERVICES ==="
    $KUBECTL get svc -n $NAMESPACE 2>/dev/null || echo "No services in namespace '$NAMESPACE'"
    echo ""
    
    echo "=== PVC ==="
    $KUBECTL get pvc -n $NAMESPACE 2>/dev/null || echo "No PVC in namespace '$NAMESPACE'"
    echo ""
    
    echo "=== PV ==="
    $KUBECTL get pv 2>/dev/null || echo "No PV found"
    echo ""
    
    echo "=== STATEFULSETS ==="
    $KUBECTL get statefulset -n $NAMESPACE 2>/dev/null || echo "No statefulsets in namespace '$NAMESPACE'"
    echo ""
    
    echo "=== CONFIGMAPS ==="
    $KUBECTL get configmap -n $NAMESPACE 2>/dev/null || echo "No configmaps in namespace '$NAMESPACE'"
    echo ""
    
    echo "=== SECRETS ==="
    $KUBECTL get secret -n $NAMESPACE 2>/dev/null || echo "No secrets in namespace '$NAMESPACE'"
    echo ""
    
    echo "=== EVENTS (last 100) ==="
    $KUBECTL get events -n $NAMESPACE --sort-by='.lastTimestamp' 2>/dev/null | tail -100 || echo "No events in namespace '$NAMESPACE'"
    echo ""
    
    echo "==================================================================="
    echo "POD DESCRIPTIONS"
    echo "==================================================================="
    
    # Get all pods in namespace
    PODS=$($KUBECTL get pods -n $NAMESPACE -o name 2>/dev/null || echo "")
    
    if [ -n "$PODS" ]; then
        for pod in $PODS; do
            POD_NAME=$(basename $pod)
            echo ""
            echo "=== DESCRIBE: $POD_NAME ==="
            $KUBECTL describe pod $POD_NAME -n $NAMESPACE 2>/dev/null || echo "Failed to describe pod $POD_NAME"
        done
    else
        echo "No pods found to describe"
    fi
    
    echo ""
    echo "==================================================================="
    echo "POD LOGS"
    echo "==================================================================="
    
    if [ -n "$PODS" ]; then
        for pod in $PODS; do
            POD_NAME=$(basename $pod)
            echo ""
            echo "=== LOGS: $POD_NAME (last 200 lines) ==="
            $KUBECTL logs $POD_NAME -n $NAMESPACE --tail=200 2>/dev/null || echo "No logs available for pod $POD_NAME"
        done
    else
        echo "No pods found for log collection"
    fi
    
    echo ""
    echo "==================================================================="
    echo "SERVICE DETAILS"
    echo "==================================================================="
    
    # Get all services in namespace
    SERVICES=$($KUBECTL get svc -n $NAMESPACE -o name 2>/dev/null || echo "")
    
    if [ -n "$SERVICES" ]; then
        for svc in $SERVICES; do
            SVC_NAME=$(basename $svc)
            echo ""
            echo "=== SERVICE: $SVC_NAME ==="
            $KUBECTL describe svc $SVC_NAME -n $NAMESPACE 2>/dev/null || echo "Failed to describe service $SVC_NAME"
        done
    else
        echo "No services found to describe"
    fi
    
    echo ""
    echo "==================================================================="
    echo "PVC DETAILS"
    echo "==================================================================="
    
    # Get all PVCs in namespace
    PVCS=$($KUBECTL get pvc -n $NAMESPACE -o name 2>/dev/null || echo "")
    
    if [ -n "$PVCS" ]; then
        for pvc in $PVCS; do
            PVC_NAME=$(basename $pvc)
            echo ""
            echo "=== PVC: $PVC_NAME ==="
            $KUBECTL describe pvc $PVC_NAME -n $NAMESPACE 2>/dev/null || echo "Failed to describe PVC $PVC_NAME"
        done
    else
        echo "No PVCs found to describe"
    fi
    
    echo ""
    echo "==================================================================="
    echo "CONFIGMAP DETAILS"
    echo "==================================================================="
    
    # Get all configmaps in namespace
    CONFIGMAPS=$($KUBECTL get configmap -n $NAMESPACE -o name 2>/dev/null || echo "")
    
    if [ -n "$CONFIGMAPS" ]; then
        for cm in $CONFIGMAPS; do
            CM_NAME=$(basename $cm)
            echo ""
            echo "=== CONFIGMAP: $CM_NAME ==="
            $KUBECTL describe configmap $CM_NAME -n $NAMESPACE 2>/dev/null || echo "Failed to describe configmap $CM_NAME"
        done
    else
        echo "No configmaps found to describe"
    fi
    
    echo "==================================================================="
    echo "END OF DIAGNOSTICS"
    echo "==================================================================="
    
} > "$OUTPUT_FILE" 2>&1

# Check if file was created successfully
if [ -f "$OUTPUT_FILE" ]; then
    FILE_SIZE=$(wc -c < "$OUTPUT_FILE" 2>/dev/null || echo "0")
    if [ "$FILE_SIZE" -gt 0 ]; then
        print_success "Diagnostics saved to: $OUTPUT_FILE"
        print_success "File size: $(du -h "$OUTPUT_FILE" | cut -f1)"
        echo ""
        echo -e "${CYAN}📋 Summary:${NC}"
        echo -e "  • Cluster info and versions"
        echo -e "  • All pods, services, PVCs, and configmaps"
        echo -e "  • Detailed descriptions and logs"
        echo -e "  • Recent events (last 100)"
        echo ""
        echo -e "${YELLOW}💡 Next steps:${NC}"
        echo -e "  • Review the file: ${CYAN}cat $OUTPUT_FILE${NC}"
        echo -e "  • Share for analysis if needed"
        echo -e "  • Check for errors in pod logs"
        echo ""
    else
        print_error "Diagnostics file is empty"
        exit 1
    fi
else
    print_error "Failed to create diagnostics file"
    exit 1
fi

