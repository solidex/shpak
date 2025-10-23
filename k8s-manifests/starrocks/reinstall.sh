#!/usr/bin/env bash
# =================================================================
# StarRocks Reinstall Script
# =================================================================
# Usage:
#   ./reinstall.sh [password] [--delete-repo]
# =================================================================

set -e

PASSWORD=${1:-"password"}
DELETE_REPO=""

# Check if --delete-repo flag is passed
for arg in "$@"; do
    if [ "$arg" = "--delete-repo" ] || [ "$arg" = "-r" ]; then
        DELETE_REPO="--delete-repo"
    fi
done

echo "=================================================================="
echo "StarRocks Quick Reinstall"
echo "=================================================================="
echo ""
echo "This will perform a full uninstall and then a full install."
echo "Password: $PASSWORD"
if [ -n "$DELETE_REPO" ]; then
    echo "Helm repository will be removed"
fi
echo ""
read -p "Continue? (yes/no): " confirm

if [ "$confirm" != "yes" ]; then
    echo "Cancelled"
    exit 0
fi

echo ""
echo "--- Uninstalling ---"
./uninstall_starrocks.sh --delete-all $DELETE_REPO

echo ""
echo "--- Installing ---"
./setup_starrocks.sh all "$PASSWORD"

echo ""
echo "Reinstallation complete. Check status: ./setup_starrocks.sh status"

