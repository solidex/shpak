#!/usr/bin/env bash
# Quick reinstall script

set -e

# Detect MicroK8s
if command -v microk8s &> /dev/null; then
    KUBECTL="microk8s kubectl"
    HELM="microk8s helm3"
else
    KUBECTL="kubectl"
    HELM="helm"
fi

echo "Uninstalling StarRocks..."
$HELM uninstall starrocks -n starrocks 2>/dev/null || true

echo "Deleting PVC..."
$KUBECTL delete pvc --all -n starrocks --timeout=30s 2>/dev/null || {
    for pvc in $($KUBECTL get pvc -n starrocks -o name 2>/dev/null); do
        $KUBECTL patch $pvc -n starrocks -p '{"metadata":{"finalizers":null}}' --type=merge 2>/dev/null || true
    done
}

echo "Deleting namespace..."
$KUBECTL delete namespace starrocks --timeout=30s 2>/dev/null || true

sleep 5

echo "Reinstalling..."
./setup_starrocks.sh all 'password'

