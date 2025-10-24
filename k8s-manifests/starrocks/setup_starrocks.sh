#!/bin/bash
# =================================================================
# StarRocks Setup Script for shpak-k8s Project
# =================================================================
# Quick start:
#   ./setup_starrocks.sh all 'YourPassword123!'
#
# Commands:
#   ./setup_starrocks.sh all [password]           - Full setup
#   ./setup_starrocks.sh create-secret [password] - Create secret
#   ./setup_starrocks.sh install                  - Install StarRocks
#   ./setup_starrocks.sh init                     - Initialize database
#   ./setup_starrocks.sh status                   - Check status
#   ./setup_starrocks.sh port-forward             - Port-forward
#   ./setup_starrocks.sh logs [fe|be]             - Show logs
#   ./setup_starrocks.sh resize be 150Gi          - Resize PVC
#   ./setup_starrocks.sh uninstall                - Uninstall
# =================================================================

set -e

# Configuration
NAMESPACE="starrocks"
RELEASE_NAME="kube-starrocks"
CHART="starrocks/kube-starrocks"
VALUES_FILE="starrocks-values.yaml"
STARROCKS_PORT="30030"
STARROCKS_USER="root"

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
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Functions
print_header() {
echo -e "${CYAN}==================================================================${NC}"
    echo -e "${CYAN}$1${NC}"
echo -e "${CYAN}==================================================================${NC}"
echo ""
}

print_step() {
    echo -e "${BLUE}▶ $1${NC}"
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

check_dependencies() {
    # Check kubectl
    if ! $KUBECTL version &> /dev/null; then
        print_error "$KUBECTL not available (tried: $KUBECTL)"
        return 1
    fi
    
    # Check helm
    if ! $HELM version &> /dev/null; then
        print_error "$HELM not available (tried: $HELM)"
        return 1
    fi
    
    return 0
}

get_service_info() {
    # Проверяем реальное имя сервиса (может быть starrocks-fe-service или kube-starrocks-fe-service)
    local svc_name=$($KUBECTL get svc -n "$NAMESPACE" -o name 2>/dev/null | grep -E "(kube-starrocks-fe-service|starrocks-fe-service)" | head -1 | cut -d'/' -f2)
    
    if [ -z "$svc_name" ]; then
        echo "NotFound"
        return
    fi
    
    local svc_type=$($KUBECTL get svc "$svc_name" -n "$NAMESPACE" -o jsonpath='{.spec.type}' 2>/dev/null)
    
    echo "$svc_type"
}

start_port_forward() {
    print_step "Starting port-forward for MySQL connection..."
    local svc_name=$($KUBECTL get svc -n "$NAMESPACE" -o name 2>/dev/null | grep -E "(kube-starrocks-fe-service|starrocks-fe-service)" | head -1 | cut -d'/' -f2)
    $KUBECTL port-forward -n "$NAMESPACE" svc/$svc_name 9030:9030 &>/dev/null &
    local pf_pid=$!
    sleep 2
    echo "$pf_pid"
}

wait_for_pods() {
    local component=$1
    local timeout=${2:-300}
    
    print_step "Waiting for $component pods to be ready (timeout: ${timeout}s)..."
    
    if $KUBECTL wait --for=condition=ready pod \
        -l app.kubernetes.io/component=$component \
        -n "$NAMESPACE" \
        --timeout=${timeout}s &> /dev/null; then
        print_success "$component pods are ready"
        return 0
    else
        print_warning "$component pods not ready yet"
        echo ""
        print_step "Checking pod status..."
        $KUBECTL get pods -n "$NAMESPACE" -l app.kubernetes.io/component=$component
        echo ""
        print_step "Checking events..."
        $KUBECTL get events -n "$NAMESPACE" --sort-by='.lastTimestamp' | tail -20
        return 1
    fi
}

# Command: all (full setup)
cmd_all() {
    local password=${1:-"password"}
    
    print_header "StarRocks Full Setup"
    
    echo -e "${CYAN}This will:${NC}"
    echo -e "  1. Create namespace and secret"
    echo -e "  2. Install StarRocks (3 FE + 3 BE)"
    echo -e "  3. Initialize RADIUS database"
    echo ""
    echo -e "${YELLOW}Password: ${password}${NC}"
    echo ""
    read -p "Continue? (yes/no): " confirm
    
    if [ "$confirm" != "yes" ]; then
        print_warning "Cancelled"
        exit 0
    fi
    
    echo ""
    print_header "Step 1: Creating Secret"
    cmd_create_secret "$password"
    
    echo ""
    print_header "Step 2: Installing StarRocks"
    cmd_install
    
    echo ""
    print_header "Step 3: Initializing Database"
    
    # Auto init without password prompt
    check_dependencies
    
    if ! command -v mysql &> /dev/null; then
        print_error "mysql client not found"
        print_warning "Install: sudo apt-get install mysql-client"
        exit 1
    fi
    
    wait_for_pods "fe" 300 || {
        print_warning "FE pods not ready yet. Skipping database initialization."
        echo ""
        echo -e "${YELLOW}Run this when pods are ready:${NC}"
        echo -e "  ${CYAN}./setup_starrocks.sh init${NC}"
        return 0
    }
    
    local svc_info=$(get_service_info)
    local mysql_host=""
    local mysql_port="$STARROCKS_PORT"
    local pf_pid=""
    
    if [ "$svc_info" == "ClusterIP" ]; then
        print_step "Using ClusterIP - starting port-forward..."
        pf_pid=$(start_port_forward)
        mysql_host="127.0.0.1"
        mysql_port="9030"
        print_success "Port-forward started"
    else
        mysql_host="$svc_info"
        mysql_port="$STARROCKS_PORT"
    fi
    
    if [ ! -f "create_database.sql" ]; then
        print_error "SQL file not found: create_database.sql"
        [ -n "$pf_pid" ] && kill "$pf_pid" 2>/dev/null
    exit 1
fi

    print_step "Creating RADIUS database and tables..."
    if mysql -h "$mysql_host" -P "$mysql_port" -u "$STARROCKS_USER" -p"$password" < create_database.sql 2>/dev/null; then
        print_success "Database initialized successfully!"
    else
        print_error "Failed to initialize database"
        [ -n "$pf_pid" ] && kill "$pf_pid" 2>/dev/null
        exit 1
    fi
    
    # Cleanup
    if [ -n "$pf_pid" ]; then
        kill "$pf_pid" 2>/dev/null
    fi
    
    echo ""
    print_header "Setup Complete!"
    echo ""
    echo -e "${GREEN}StarRocks is ready!${NC}"
    
    # Show actual ClusterIP
    local svc_name=$($KUBECTL get svc -n "$NAMESPACE" -o name 2>/dev/null | grep -E "(kube-starrocks-fe-service|starrocks-fe-service)" | head -1 | cut -d'/' -f2)
    local cluster_ip=$($KUBECTL get svc "$svc_name" -n "$NAMESPACE" -o jsonpath='{.spec.clusterIP}' 2>/dev/null)
    
    echo -e "${CYAN}ClusterIP:${NC}"
    echo -e "  FE: ${GREEN}$cluster_ip:9030${NC}"
    
    if [ "$cluster_ip" != "10.152.183.10" ]; then
        echo -e "  ${YELLOW}⚠️  Static IP 10.152.183.10 not applied (may be in use)${NC}"
    fi
    
    echo ""
    echo -e "${CYAN}Connection:${NC}"
    echo -e "  From inside cluster: ${GREEN}mysql -h $cluster_ip -P 9030 -u root -p${NC}"
    echo -e "  From outside: ${GREEN}./setup_starrocks.sh port-forward${NC}"
    echo ""
}

# Command: create-secret
cmd_create_secret() {
    local password=${1:-"password"}
    
    print_header "Creating StarRocks Secret"
    
    check_dependencies
    
    # Create namespace
    print_step "Creating namespace: $NAMESPACE"
    $KUBECTL create namespace "$NAMESPACE" 2>/dev/null || print_warning "Namespace already exists"
    
    # Check if secret already exists
    if $KUBECTL get secret starrocks-root-pass -n "$NAMESPACE" &>/dev/null; then
        print_warning "Secret 'starrocks-root-pass' already exists"
        read -p "Overwrite? (yes/no): " confirm
        if [ "$confirm" != "yes" ]; then
            print_warning "Cancelled"
            exit 0
        fi
        $KUBECTL delete secret starrocks-root-pass -n "$NAMESPACE"
    fi
    
    # Create secret
    print_step "Creating secret with password: $password"
    $KUBECTL create secret generic starrocks-root-pass \
        --from-literal=password="$password" \
        -n "$NAMESPACE"
    
    print_success "Secret created successfully!"
    echo ""
    echo -e "${YELLOW}Next step:${NC}"
    echo -e "  ${CYAN}./setup_starrocks.sh install${NC}"
}

# Command: install
cmd_install() {
    print_header "Installing StarRocks"
    
    check_dependencies
    
    # Check StorageClass
    print_step "Checking StorageClass..."
    if ! $KUBECTL get storageclass microk8s-hostpath &>/dev/null; then
        print_warning "StorageClass 'microk8s-hostpath' not found"
        echo ""
        echo -e "${YELLOW}Available StorageClasses:${NC}"
        $KUBECTL get storageclass
        echo ""
        print_error "Enable storage addon: microk8s enable storage"
        exit 1
    fi
    print_success "StorageClass 'microk8s-hostpath' found"
    
    # Check if already installed
    if $HELM list -n "$NAMESPACE" 2>/dev/null | grep -q "$RELEASE_NAME"; then
        print_warning "StarRocks already installed"
        echo -e "Use: ${CYAN}$HELM upgrade $RELEASE_NAME $CHART -n $NAMESPACE -f $VALUES_FILE${NC}"
        exit 0
    fi
    
    # Check if values file exists
    if [ ! -f "$VALUES_FILE" ]; then
        print_error "Values file not found: $VALUES_FILE"
    exit 1
fi

    # Create namespace
    print_step "Creating namespace: $NAMESPACE"
    $KUBECTL create namespace "$NAMESPACE" 2>/dev/null || print_warning "Namespace already exists"
    
    # Check if secret exists
    if ! $KUBECTL get secret starrocks-root-pass -n "$NAMESPACE" &>/dev/null; then
        print_warning "Secret 'starrocks-root-pass' not found"
        echo ""
        echo -e "${YELLOW}Creating secret with default password...${NC}"
        $KUBECTL create secret generic starrocks-root-pass \
            --from-literal=password='password' \
            -n "$NAMESPACE"
        print_success "Secret created (password: 'password')"
        print_warning "CHANGE PASSWORD in production!"
        echo ""
    fi
    
    # Add Helm repo
    print_step "Adding StarRocks Helm repository"
    $HELM repo add starrocks https://starrocks.github.io/starrocks-kubernetes-operator 2>/dev/null || true
    $HELM repo update starrocks
    
    # Install
    print_step "Installing StarRocks (this may take 5-10 minutes)..."
    $HELM install "$RELEASE_NAME" "$CHART" \
    -n "$NAMESPACE" \
        -f "$VALUES_FILE"
    
    print_success "StarRocks installation started"
    echo ""
    
    echo ""
    
    # Wait for FE
    if wait_for_pods "fe" 600; then
        print_success "FE pods are ready!"
        
        # Wait for BE
        if wait_for_pods "be" 600; then
            print_success "BE pods are ready!"
            echo ""
            print_success "StarRocks installed successfully!"
        else
            print_warning "BE pods not ready yet"
            echo ""
            print_warning "StarRocks installation started, but not fully ready"
        fi
    else
        print_warning "FE pods not ready yet"
        echo ""
        print_warning "StarRocks installation started, but not fully ready"
        echo -e "${YELLOW}Check status: ./setup_starrocks.sh status${NC}"
        echo -e "${YELLOW}Wait 5-10 minutes, then run: ./setup_starrocks.sh init${NC}"
    fi
    
echo ""

    # Show connection info
    local svc_name=$($KUBECTL get svc -n "$NAMESPACE" -o name 2>/dev/null | grep -E "(kube-starrocks-fe-service|starrocks-fe-service)" | head -1 | cut -d'/' -f2)
    local cluster_ip=$($KUBECTL get svc "$svc_name" -n "$NAMESPACE" -o jsonpath='{.spec.clusterIP}' 2>/dev/null)
    
    echo -e "${CYAN}Connection details:${NC}"
    echo -e "  ${YELLOW}Service type: ClusterIP${NC}"
    echo -e "  ${GREEN}ClusterIP: $cluster_ip${NC}"
    
    # Warn if static IP not applied
    if [ "$cluster_ip" != "10.152.183.10" ]; then
        echo -e "  ${YELLOW}⚠️  Expected static IP 10.152.183.10, got $cluster_ip${NC}"
        echo -e "  ${YELLOW}   Static IP may be in use or not applied${NC}"
    fi
    
    echo ""
    echo -e "  ${GREEN}From inside cluster:${NC}"
    echo -e "    mysql -h $cluster_ip -P 9030 -u root -p"
    echo ""
    echo -e "  ${GREEN}From outside cluster:${NC}"
    echo -e "    ./setup_starrocks.sh port-forward"
    echo -e "    mysql -h 127.0.0.1 -P 9030 -u root -p"
    echo ""
    echo -e "${YELLOW}Next steps:${NC}"
    echo -e "  1. Initialize database: ${CYAN}./setup_starrocks.sh init${NC}"
    echo -e "  2. Check status:        ${CYAN}./setup_starrocks.sh status${NC}"
    echo ""
}

# Command: init
cmd_init() {
    print_header "Initializing StarRocks Database"
    
    check_dependencies
    
    # Check if mysql client is available
    if ! command -v mysql &> /dev/null; then
        print_error "mysql client not found"
        print_warning "Install: sudo apt-get install mysql-client"
        exit 1
    fi
    
    # Check if StarRocks is running
    if ! $KUBECTL get pods -n "$NAMESPACE" -l app.kubernetes.io/component=fe &>/dev/null; then
        print_error "StarRocks not found. Install first: ./setup_starrocks.sh install"
        exit 1
    fi
    
    # Wait for FE to be ready
    wait_for_pods "fe" 300 || {
        print_error "FE pods not ready"
        exit 1
    }
    
    # Check service type and setup connection
    local svc_info=$(get_service_info)
    local mysql_host=""
    local mysql_port="$STARROCKS_PORT"
    local pf_pid=""
    
    if [ "$svc_info" == "ClusterIP" ]; then
        print_step "Using ClusterIP - starting port-forward..."
        pf_pid=$(start_port_forward)
        mysql_host="127.0.0.1"
        mysql_port="9030"
        print_success "Port-forward started (PID: $pf_pid)"
    else
        mysql_host="$svc_info"
        mysql_port="$STARROCKS_PORT"
        print_success "Using external connection: $mysql_host:$mysql_port"
    fi
echo ""
    
    # Check if SQL file exists
    if [ ! -f "create_database.sql" ]; then
        print_error "SQL file not found: create_database.sql"
        exit 1
    fi

# Prompt for password
echo -e "${YELLOW}Enter StarRocks root password:${NC}"
read -s STARROCKS_PASSWORD
echo ""

    # Create database
    print_step "Creating RADIUS database and tables..."
    if mysql -h "$mysql_host" -P "$mysql_port" -u "$STARROCKS_USER" -p"$STARROCKS_PASSWORD" < create_database.sql 2>/dev/null; then
        print_success "Database initialized successfully!"
    else
        print_error "Failed to initialize database"
        [ -n "$pf_pid" ] && kill "$pf_pid" 2>/dev/null
    exit 1
fi

    # Verify
    print_step "Verifying tables..."
    local tables=$(mysql -h "$mysql_host" -P "$mysql_port" -u "$STARROCKS_USER" -p"$STARROCKS_PASSWORD" \
    -e "USE RADIUS; SHOW TABLES;" 2>/dev/null | grep -v Tables_in | wc -l)

    print_success "Created $tables tables in RADIUS database"
    echo ""

# Show table details
    echo -e "${CYAN}Table details:${NC}"
    mysql -h "$mysql_host" -P "$mysql_port" -u "$STARROCKS_USER" -p"$STARROCKS_PASSWORD" \
    -e "USE RADIUS; 
        SELECT 
            TABLE_NAME, 
            TABLE_ROWS as 'Rows',
            ROUND(DATA_LENGTH / 1024 / 1024, 2) as 'Size_MB'
        FROM information_schema.TABLES 
        WHERE TABLE_SCHEMA = 'RADIUS' 
            ORDER BY TABLE_NAME;" 2>/dev/null
    
    # Cleanup port-forward
    if [ -n "$pf_pid" ]; then
        kill "$pf_pid" 2>/dev/null
        print_step "Port-forward stopped"
    fi
    
    echo ""
    print_success "Database ready to use!"
}

# Command: status
cmd_status() {
    print_header "StarRocks Cluster Status"
    
    check_dependencies
    
    # Check if StarRocks is installed
    if ! $HELM list -n "$NAMESPACE" 2>/dev/null | grep -q "$RELEASE_NAME"; then
        print_error "StarRocks not installed"
        exit 1
    fi
    
    echo -e "${CYAN}📦 Helm Release:${NC}"
    $HELM list -n "$NAMESPACE" | grep "$RELEASE_NAME" || true
    echo ""
    
    echo -e "${CYAN}🔧 Pods:${NC}"
    $KUBECTL get pods -n "$NAMESPACE" -o wide
    echo ""
    
    echo -e "${CYAN}💾 PVC (Persistent Volume Claims):${NC}"
    $KUBECTL get pvc -n "$NAMESPACE"
    echo ""
    
    echo -e "${CYAN}🌐 Services:${NC}"
    $KUBECTL get svc -n "$NAMESPACE"
    echo ""
    
    # Check disk usage
    echo -e "${CYAN}💽 Disk Usage (BE):${NC}"
    local be_pods=$($KUBECTL get pods -n "$NAMESPACE" -l app.kubernetes.io/component=be -o name 2>/dev/null)
    if [ -n "$be_pods" ]; then
        for pod in $be_pods; do
            local pod_name=$(basename $pod)
            echo -e "${BLUE}  $pod_name:${NC}"
            $KUBECTL exec -n "$NAMESPACE" "$pod_name" -- df -h /opt/starrocks/be/storage 2>/dev/null | tail -n 1 || echo "    (not available)"
        done
    else
        print_warning "No BE pods found"
    fi
    echo ""
    
    # Connection info
    echo -e "${CYAN}🔗 Connection:${NC}"
    local svc_name=$($KUBECTL get svc -n "$NAMESPACE" -o name 2>/dev/null | grep -E "(kube-starrocks-fe-service|starrocks-fe-service)" | head -1 | cut -d'/' -f2)
    local svc_type=$($KUBECTL get svc "$svc_name" -n "$NAMESPACE" -o jsonpath='{.spec.type}' 2>/dev/null)
    local cluster_ip=$($KUBECTL get svc "$svc_name" -n "$NAMESPACE" -o jsonpath='{.spec.clusterIP}' 2>/dev/null)
    
    echo -e "  ${YELLOW}Service: $svc_name (${svc_type})${NC}"
    echo -e "  ${GREEN}ClusterIP: $cluster_ip${NC}"
    
    # Warn if static IP not applied
    if [ "$cluster_ip" != "10.152.183.10" ] && [ -n "$cluster_ip" ]; then
        echo -e "  ${YELLOW}⚠️  Expected static IP 10.152.183.10, got $cluster_ip${NC}"
        echo -e "  ${YELLOW}   (Static IP may be in use or not supported)${NC}"
    fi

echo ""
    echo -e "  ${GREEN}From inside cluster:${NC}"
    echo -e "    mysql -h $cluster_ip -P 9030 -u root -p"
    echo ""
    echo -e "  ${GREEN}From outside (port-forward):${NC}"
    echo -e "    ./setup_starrocks.sh port-forward"
    echo -e "    mysql -h 127.0.0.1 -P 9030 -u root -p"
echo ""
}

# Command: logs
cmd_logs() {
    local component=${1:-"be"}
    local lines=${2:-100}
    
    print_header "StarRocks Logs: $component"
    
    check_dependencies
    
    local pods=$($KUBECTL get pods -n "$NAMESPACE" -l app.kubernetes.io/component="$component" -o name 2>/dev/null)
    
    if [ -z "$pods" ]; then
        print_error "No $component pods found"
        exit 1
    fi
    
    for pod in $pods; do
        local pod_name=$(basename $pod)
        echo -e "${CYAN}=== $pod_name ===${NC}"
        $KUBECTL logs -n "$NAMESPACE" "$pod_name" --tail="$lines"
echo ""
    done
}

# Command: uninstall
cmd_uninstall() {
    local keep_pvc=false
    
    if [ "$1" == "--keep-pvc" ]; then
        keep_pvc=true
    fi
    
    print_header "Uninstalling StarRocks"
    
    check_dependencies
    
    # Check if installed
    if ! $HELM list -n "$NAMESPACE" 2>/dev/null | grep -q "$RELEASE_NAME"; then
        print_warning "StarRocks not installed"
        exit 0
    fi
    
    # Confirmation
    echo -e "${RED}⚠️  WARNING: This will remove StarRocks${NC}"
    if [ "$keep_pvc" == "false" ]; then
        echo -e "${RED}    and DELETE all data (PVC will be removed)${NC}"
    else
        echo -e "${YELLOW}    PVC will be kept (data preserved)${NC}"
    fi
echo ""
    read -p "Are you sure? (yes/no): " confirm
    
    if [ "$confirm" != "yes" ]; then
        print_warning "Uninstall cancelled"
        exit 0
    fi
    
    # Uninstall
    print_step "Uninstalling Helm release..."
    $HELM uninstall "$RELEASE_NAME" -n "$NAMESPACE"
    
    print_success "Helm release uninstalled"
    
    # Delete PVC if requested
    if [ "$keep_pvc" == "false" ]; then
        print_step "Deleting PVC..."
        $KUBECTL delete pvc -n "$NAMESPACE" --all
        print_success "PVC deleted"
    else
        print_warning "PVC kept (to delete manually: $KUBECTL delete pvc -n $NAMESPACE --all)"
    fi
    
echo ""
    print_success "StarRocks uninstalled"
}

# Command: resize
cmd_resize() {
    local component=$1
    local new_size=$2
    
    if [ -z "$component" ] || [ -z "$new_size" ]; then
        print_error "Usage: ./setup_starrocks.sh resize [be|fe] <size>"
        print_error "Example: ./setup_starrocks.sh resize be 150Gi"
        exit 1
    fi
    
    print_header "Resizing $component PVC to $new_size"
    
    check_dependencies
    
    # Check if StorageClass supports expansion
    print_step "Checking StorageClass capabilities..."
    
    local sc=$($KUBECTL get pvc -n "$NAMESPACE" -o jsonpath='{.items[0].spec.storageClassName}' 2>/dev/null)
    local allow_expansion=$($KUBECTL get storageclass "$sc" -o jsonpath='{.allowVolumeExpansion}' 2>/dev/null)
    
    if [ "$allow_expansion" != "true" ]; then
        print_error "StorageClass '$sc' does not support volume expansion"
        print_warning "You may need to recreate the PVC with a larger size"
        exit 1
    fi
    
    print_success "StorageClass supports expansion"
    
    # Get PVC names
    local pvcs=$($KUBECTL get pvc -n "$NAMESPACE" -o name | grep "$component" 2>/dev/null)
    
    if [ -z "$pvcs" ]; then
        print_error "No PVC found for component: $component"
        exit 1
    fi
    
    # Patch each PVC
    for pvc in $pvcs; do
        local pvc_name=$(basename $pvc)
        print_step "Resizing $pvc_name to $new_size..."
        
        $KUBECTL patch pvc "$pvc_name" -n "$NAMESPACE" \
            -p "{\"spec\":{\"resources\":{\"requests\":{\"storage\":\"$new_size\"}}}}"
        
        print_success "$pvc_name patched"
    done
    
echo ""
    print_warning "Note: Pod restart may be required for changes to take effect"
    echo -e "Run: ${CYAN}$KUBECTL delete pod -n $NAMESPACE -l app.kubernetes.io/component=$component${NC}"
}

# Command: port-forward
cmd_port_forward() {
    print_header "StarRocks Port Forward"
    
    check_dependencies
    
    # Find FE service name
    local svc_name=$($KUBECTL get svc -n "$NAMESPACE" -o name 2>/dev/null | grep -E "(kube-starrocks-fe-service|starrocks-fe-service)" | head -1 | cut -d'/' -f2)
    
    if [ -z "$svc_name" ]; then
        print_error "StarRocks FE service not found"
        exit 1
    fi
    
    print_step "Starting port-forward for StarRocks services..."
    echo -e "${CYAN}MySQL:  localhost:9030 → $svc_name:9030${NC}"
    echo -e "${CYAN}Web UI: localhost:8030 → $svc_name:8030${NC}"
echo ""
    print_warning "Press Ctrl+C to stop port-forward"
echo ""

    $KUBECTL port-forward -n "$NAMESPACE" svc/$svc_name 9030:9030 8030:8030
}

# Main
main() {
    local command=${1:-"help"}
    
    case "$command" in
        all|quick-start)
            cmd_all "$2"
            ;;
        create-secret)
            cmd_create_secret "$2"
            ;;
        install)
            cmd_install
            ;;
        init)
            cmd_init
            ;;
        status)
            cmd_status
            ;;
        logs)
            cmd_logs "$2" "$3"
            ;;
        uninstall)
            cmd_uninstall "$2"
            ;;
        resize)
            cmd_resize "$2" "$3"
            ;;
        port-forward|pf)
            cmd_port_forward
            ;;
        help|--help|-h)
            print_header "StarRocks Setup Script - Help"
            echo -e "${CYAN}Usage:${NC}"
            echo -e "  ${GREEN}./setup_starrocks.sh all [password]${NC}          - Full setup (secret + install + init)"
            echo -e "  ${GREEN}./setup_starrocks.sh create-secret [password]${NC} - Create secret (default: 'password')"
            echo -e "  ${GREEN}./setup_starrocks.sh install${NC}                 - Install StarRocks cluster"
            echo -e "  ${GREEN}./setup_starrocks.sh init${NC}                    - Initialize RADIUS database"
            echo -e "  ${GREEN}./setup_starrocks.sh status${NC}                  - Show cluster status"
            echo -e "  ${GREEN}./setup_starrocks.sh logs [fe|be] [lines]${NC}    - Show logs (default: be, 100 lines)"
            echo -e "  ${GREEN}./setup_starrocks.sh port-forward${NC}            - Start port-forward (ClusterIP only)"
            echo -e "  ${GREEN}./setup_starrocks.sh uninstall [--keep-pvc]${NC}  - Uninstall (optionally keep PVC)"
            echo -e "  ${GREEN}./setup_starrocks.sh resize be 150Gi${NC}        - Resize BE PVC to 150Gi"
            echo ""
            echo -e "${CYAN}Examples:${NC}"
            echo -e "  # Quick start (one command)"
            echo -e "  ${BLUE}./setup_starrocks.sh all 'MyPass123!'${NC}"
            echo ""
            echo -e "  # Step by step"
            echo -e "  ${BLUE}./setup_starrocks.sh create-secret 'MyPass123!'${NC}"
            echo -e "  ${BLUE}./setup_starrocks.sh install${NC}"
            echo -e "  ${BLUE}./setup_starrocks.sh init${NC}"
            echo ""
            echo -e "  # Access from outside cluster (ClusterIP)"
            echo -e "  ${BLUE}./setup_starrocks.sh port-forward${NC}"
            echo -e "  ${BLUE}mysql -h 127.0.0.1 -P 9030 -u root -p${NC}"
            echo ""
            echo -e "  # Monitoring"
            echo -e "  ${BLUE}./setup_starrocks.sh status${NC}"
            echo -e "  ${BLUE}./setup_starrocks.sh logs be 200${NC}"
            echo ""
            echo -e "  # Maintenance"
            echo -e "  ${BLUE}./setup_starrocks.sh resize be 200Gi${NC}"
            echo -e "  ${BLUE}./setup_starrocks.sh uninstall --keep-pvc${NC}"
            echo ""
            ;;
        *)
            print_error "Unknown command: $command"
            echo -e "Run: ${CYAN}./setup_starrocks.sh help${NC}"
            exit 1
            ;;
    esac
}

main "$@"
