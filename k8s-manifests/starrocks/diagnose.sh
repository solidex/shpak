#!/usr/bin/env bash
# =================================================================
# StarRocks Diagnostics - Collect all info
# =================================================================

# Detect MicroK8s
if command -v microk8s &> /dev/null; then
    KUBECTL="microk8s kubectl"
else
    KUBECTL="kubectl"
fi

NAMESPACE="starrocks"
OUTPUT_FILE="starrocks-diagnostics-$(date +%Y%m%d-%H%M%S).txt"

echo "Collecting StarRocks diagnostics..."
echo "Output: $OUTPUT_FILE"
echo ""

{
    echo "==================================================================="
    echo "StarRocks Diagnostics Report"
    echo "Generated: $(date)"
    echo "==================================================================="
    echo ""
    
    echo "=== CLUSTER INFO ==="
    $KUBECTL version --short 2>/dev/null || echo "kubectl version N/A"
    echo ""
    
    echo "=== NODES ==="
    $KUBECTL get nodes -o wide
    echo ""
    
    echo "=== STORAGE CLASSES ==="
    $KUBECTL get storageclass
    echo ""
    
    echo "=== NAMESPACE ==="
    $KUBECTL get namespace starrocks 2>/dev/null || echo "Namespace not found"
    echo ""
    
    echo "=== PODS ==="
    $KUBECTL get pods -n $NAMESPACE -o wide 2>/dev/null || echo "No pods"
    echo ""
    
    echo "=== SERVICES ==="
    $KUBECTL get svc -n $NAMESPACE 2>/dev/null || echo "No services"
    echo ""
    
    echo "=== PVC ==="
    $KUBECTL get pvc -n $NAMESPACE 2>/dev/null || echo "No PVC"
    echo ""
    
    echo "=== PV ==="
    $KUBECTL get pv 2>/dev/null || echo "No PV"
    echo ""
    
    echo "=== STATEFULSETS ==="
    $KUBECTL get statefulset -n $NAMESPACE 2>/dev/null || echo "No statefulsets"
    echo ""
    
    echo "=== EVENTS (last 50) ==="
    $KUBECTL get events -n $NAMESPACE --sort-by='.lastTimestamp' 2>/dev/null | tail -50 || echo "No events"
    echo ""
    
    echo "==================================================================="
    echo "POD DESCRIPTIONS"
    echo "==================================================================="
    
    for pod in $($KUBECTL get pods -n $NAMESPACE -o name 2>/dev/null | grep -E 'fe-|be-'); do
        POD_NAME=$(basename $pod)
        echo ""
        echo "=== DESCRIBE: $POD_NAME ==="
        $KUBECTL describe pod $POD_NAME -n $NAMESPACE 2>/dev/null || echo "Failed to describe"
    done
    
    echo ""
    echo "==================================================================="
    echo "POD LOGS"
    echo "==================================================================="
    
    for pod in $($KUBECTL get pods -n $NAMESPACE -o name 2>/dev/null | grep -E 'fe-|be-|initpwd'); do
        POD_NAME=$(basename $pod)
        echo ""
        echo "=== LOGS: $POD_NAME (last 100 lines) ==="
        $KUBECTL logs $POD_NAME -n $NAMESPACE --tail=100 2>/dev/null || echo "No logs or pod not ready"
    done
    
    echo ""
    echo "==================================================================="
    echo "CONFIGMAPS"
    echo "==================================================================="
    $KUBECTL get configmap -n $NAMESPACE 2>/dev/null || echo "No configmaps"
    echo ""
    
    echo "==================================================================="
    echo "END OF DIAGNOSTICS"
    echo "==================================================================="
    
} > "$OUTPUT_FILE" 2>&1

echo "✅ Diagnostics saved to: $OUTPUT_FILE"
echo ""
echo "Please share this file for analysis"

