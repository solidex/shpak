# 🚀 MicroK8s + Cilium + Egress Gateway - Полная установка

Пошаговая инструкция по развертыванию MicroK8s кластера с Cilium CNI и Egress Gateway для статических внешних IP.

---

## 📋 Содержание

1. [Установка MicroK8s](#1-установка-microk8s)
2. [Настройка кластера](#2-настройка-кластера)
3. [Установка Cilium с Egress Gateway](#3-установка-cilium)
4. [Настройка узлов](#4-настройка-узлов)
5. [Применение конфигураций](#5-применение-конфигураций)
6. [Проверка и тестирование](#6-проверка)
7. [Troubleshooting](#7-troubleshooting)

---

## 1. Установка MicroK8s

### 📦 На каждом узле кластера

```bash
# Установка MicroK8s (latest/edge для новейших функций)
sudo snap install microk8s --classic --channel=latest/edge

# Создание алиаса для удобства
sudo snap alias microk8s.kubectl kubectl

# Добавление текущего пользователя в группу microk8s
sudo usermod -a -G microk8s $USER
sudo newgrp microk8s

# Создание директории для kubeconfig
mkdir -p ~/.kube
sudo chown -R $USER ~/.kube

# Проверка установки
microk8s status --wait-ready
```

**✅ Проверка:**

```bash
microk8s kubectl get nodes
# Должен показать локальный узел в статусе Ready
```

---

## 2. Настройка кластера

### 🔗 На master-узле (первый узел)

```bash
# Включить community addon репозиторий
microk8s enable community
microk8s enable storage
microk8s enable helm

# Обновить Helm репозитории
microk8s helm repo update

# Создать backup базы данных (рекомендуется)
sudo microk8s dbctl backup

# Получить команду для добавления узлов
microk8s add-node
```

**Сохраните** вывод `add-node` - это команда для подключения worker-узлов!

### 🔗 На каждом worker-узле

```bash
# Выполните команду, полученную от add-node на master
# Пример:
microk8s join 192.168.1.100:25000/abc123def456...

# Дождитесь завершения присоединения (1-2 минуты)
```

### ✅ Проверка кластера

```bash
# На master-узле
microk8s kubectl get nodes -o wide

# Ожидается:
# NAME          STATUS   ROLES    AGE   VERSION
# lenovo-204    Ready    <none>   10m   v1.29.x
# lenovo-205    Ready    <none>   5m    v1.29.x
# lenovo-206    Ready    <none>   5m    v1.29.x
```

---

## 3. Установка Cilium

### 🧹 Подготовка

```bash
# Включить Cilium addon (только для получения CLI)
microk8s enable cilium

# Удалить дефолтную установку (если была)
microk8s cilium uninstall
```

### 🔧 Установка Cilium 1.14.5 с Egress Gateway

```bash
microk8s cilium install --version 1.14.5 \
  --namespace=kube-system \
  --set egressGateway.enabled=true \
  --set enableIPv4Masquerade=true \
  --set bpf.masquerade=true \
  --set l7Proxy=false \
  --set envoy.enabled=false \
  --set kubeProxyReplacement=partial \
  --set bgpControlPlane.enabled=true \
  --set externalIPs.enabled=true \
  --set loadBalancer.enabled=true \
  --set nodePort.enabled=true \
  --set l2announcements.enabled=true \
  --set l2announcements.leaseDuration=3s \
  --set l2announcements.leaseRenewDeadline=1s \
  --set l2announcements.leaseRetryPeriod=500ms \
  --set operator.replicas=3
```

**⏳ Дождитесь готовности (2-3 минуты):**

```bash
microk8s cilium status --wait
```

### ✅ Проверка Cilium

```bash
# Статус Cilium
microk8s cilium status

# Должно быть:
#   Cilium:             OK
#   Operator:           OK
#   DaemonSet cilium:   Desired: 3, Ready: 3/3

# Проверить поды
microk8s kubectl get pods -n kube-system -l k8s-app=cilium

# Проверить наличие CRD для Egress Gateway
microk8s kubectl get crds | grep ciliumegressgateway
# Ожидается: ciliumegressgatewaypolicies.cilium.io
```

### 📊 Проверка конфигурации

```bash
# Убедиться, что нужные параметры установлены
microk8s kubectl get cm cilium-config -n kube-system -o yaml | \
  egrep 'enable-ipv4-masquerade|bpf-masquerade|enable-l7-proxy|kube-proxy-replacement'

# Ожидается:
#   enable-ipv4-masquerade: "true"
#   bpf-masquerade: "true"
#   enable-l7-proxy: "false"
#   kube-proxy-replacement: "partial"
```

---

## 4. Настройка узлов

### 🏷️ Применение labels

```bash
# BGP policy label (для всех узлов, которые будут peer-ами BGP)
kubectl label nodes lenovo-204 bgp-policy=a
kubectl label nodes lenovo-205 bgp-policy=a
kubectl label nodes lenovo-206 bgp-policy=a

# Egress gateway label (узлы, через которые пойдет egress трафик)
kubectl label node lenovo-204 egress-gateway=true
kubectl label node lenovo-205 egress-gateway=true
kubectl label node lenovo-206 egress-gateway=true
```

**💡 Примечание:**

- `bgp-policy=a` - узлы, которые будут устанавливать BGP peering
- `egress-gateway=true` - узлы, которые будут SNAT-ить egress трафик

### ✅ Проверка labels

```bash
kubectl get nodes --show-labels | grep -E 'bgp-policy|egress-gateway'
```

---

## 5. Применение конфигураций

### 📁 Структура файлов

Убедитесь, что у вас есть:

```
cilium_settings/
├── cilium-ippool.yaml               # LoadBalancer IP pool
├── cilium-egress-ippool.yaml        # Egress IP pool
├── cilium-bgp-policy.yaml           # BGP peering config
└── cilium-egress-gateway-policy.yaml # Egress policies
```

### 🌐 1. IP Pools

```bash
# LoadBalancer IP pool (10.3.11.0/24)
kubectl apply -f cilium-ippool.yaml

# Egress Gateway IP pool (10.3.11.200-207)
kubectl apply -f cilium-egress-ippool.yaml

# Проверка
kubectl get ciliumpools
```

**Ожидаемый вывод:**

```
NAME          DISABLED   CONFLICTING   IPS AVAILABLE   AGE
lb-pool       false      False         254             10s
egress-pool   false      False         8               5s
```

### 🔀 2. BGP Peering

```bash
# Применить BGP peering policy
kubectl apply -f cilium-bgp-policy.yaml

# Проверка
kubectl get ciliumbgppeeringpolicies
```

**⚠️ Warning о v2alpha1 - это нормально!**

```
Warning: cilium.io/v2alpha1 CiliumBGPPeeringPolicy is deprecated
```

Игнорируйте - это работает. Миграция на BGPv2 - опционально.

### 🚪 3. Egress Gateway Policies

```bash
# Применить egress policies для 3 сервисов
kubectl apply -f cilium-egress-gateway-policy.yaml

# Проверка
kubectl get ciliumegressgatewaypolicies
```

**Ожидаемый вывод:**

```
NAME                   AGE
mhe-fortiapi-egress    10s
mhe-ldap-egress        10s
mhe-email-egress       10s
```

---

## 6. Проверка

### 🔍 BGP Status

```bash
# Проверить BGP peers (на любом узле с label bgp-policy=a)
microk8s kubectl exec -n kube-system ds/cilium -- cilium bgp peers

# Или детально на конкретном узле:
POD=$(kubectl get pods -n kube-system -l k8s-app=cilium --field-selector spec.nodeName=lenovo-204 -o name | head -1)
kubectl exec -n kube-system $POD -- cilium bgp peers
```

**Ожидается:**

```
Local AS   Peer AS   Peer Address      State
65017      6697      93.85.81.201      Established
65017      6697      93.85.81.202      Established
```

### 📊 IP Pool Allocation

```bash
# Посмотреть детали IP pools
kubectl get ciliumpools -o yaml

# Посмотреть, какие IP выделены
kubectl get svc -A -o wide | grep LoadBalancer
```

### 🚪 Egress Gateway Status

```bash
# Проверить, что egress policies применены
kubectl describe ciliumegressgatewaypolicies mhe-fortiapi-egress

# Проверить узлы egress gateway
kubectl get nodes -l egress-gateway=true
```

---

## 7. Troubleshooting

### ❌ Cilium pods в CrashLoopBackOff

**Проблема**: `egress gateway requires --enable-ipv4-masquerade="true" and --enable-bpf-masquerade="true"`

**Решение**: Переустановите с правильными флагами (см. раздел 3)

**Проверка конфигурации:**

```bash
kubectl get cm cilium-config -n kube-system -o yaml | grep masquerade
```

---

### ❌ BGP peers не устанавливаются

**Проверка:**

```bash
# Логи BGP Control Plane
kubectl logs -n kube-system ds/cilium | grep -i bgp

# Убедиться, что узлы имеют label
kubectl get nodes -l bgp-policy=a
```

**Возможные причины:**

- Узлы не помечены `bgp-policy=a`
- Неправильные BGP peer адреса в `cilium-bgp-policy.yaml`
- Firewall блокирует TCP 179 (BGP)
- FortiGate не настроен на прием BGP от ASN 65017

---

### ❌ CRD "unknown field spec.cidrs"

**Проблема**: IP pool использует неправильный формат

**Решение**: Используйте `blocks` вместо `cidrs`:

```yaml
spec:
  blocks:
  - start: "10.3.11.1"
    stop: "10.3.11.254"
```

**Проверка поддерживаемых полей:**

```bash
kubectl explain ciliumloadbalancerippool.spec --api-version=cilium.io/v2alpha1
```

---

### 🔧 Полный рестарт Cilium

```bash
# Если нужен чистый рестарт
microk8s cilium uninstall
kubectl delete ds cilium -n kube-system --force --grace-period=0
kubectl delete deploy cilium-operator -n kube-system --force --grace-period=0

# На каждом узле очистить eBPF maps
sudo rm -rf /sys/fs/bpf/cilium
sudo systemctl restart containerd

# Переустановить (см. раздел 3)
```

---

## 📚 Дополнительные ресурсы

- **Cilium Docs**: https://docs.cilium.io/
- **Egress Gateway**: https://docs.cilium.io/en/stable/network/egress-gateway/
- **BGP Control Plane**: https://docs.cilium.io/en/stable/network/bgp-control-plane/
- **MicroK8s Docs**: https://microk8s.io/docs

---

## 📊 Следующие шаги

После успешной настройки:

1. **Развернуть сервисы**:

   ```bash
   kubectl apply -f deployments/mhe-fortiapi-deployment.yaml
   kubectl apply -f deployments/mhe-ldap-deployment.yaml
   kubectl apply -f deployments/mhe-email-deployment.yaml
   ```
2. **Проверить egress IP**:

   ```bash
   kubectl exec -it deployment/mhe-fortiapi -- curl -s ifconfig.me
   # Должно вернуть: 10.3.11.201
   ```
3. **Настроить FortiGate** для приема BGP и маршрутизации egress трафика

---

**Создано**: 2025-10-21
**Версия Cilium**: 1.14.5
**Версия MicroK8s**: latest/edge
**Проект**: shpak-k8s
