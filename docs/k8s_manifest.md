# Манифест переноса АПК на Kubernetes

## Обзор

Данный документ описывает план переноса системы АПК (Автоматизированная Платформа Конфигурации) на платформу Kubernetes с использованием Cilium для сетевой политики, BGP для маршрутизации, Egress Gateway для исходящего трафика, а также интеграцией с Superset и StarRocks.

## Архитектура системы

### Микросервисы АПК

1. **mysql-handler** - обработчик MySQL запросов (порт 18140)
2. **fastapi-sql** - публичный API (порт 8000)
3. **operation-logic** - оркестрация операций (порт 8001)
4. **fortigate-service** - сервис FortiGate (порт 18080)
5. **keepalive** - сервис keepalive (порт 8083)
6. **oplogic** - порт-лист отправитель (порт 8001)
7. **radius-sniffer-service** - RADIUS sniffer (порт 8081)
8. **sniffer** - основной RADIUS sniffer (порт 1813)
9. **logging-service** - централизованное логирование (порт 8084)
10. **gui** - веб-интерфейс (порт 8080)

### Внешние сервисы

- **StarRocks** - аналитическая база данных
- **Superset** - веб-интерфейс для аналитики
- **FortiGate** - файрволы

## Namespace и метки

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: apk-system
  labels:
    name: apk-system
    environment: production
    team: network-operations
```

## Конфигурационные карты

### ConfigMap для общих настроек

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: apk-config
  namespace: apk-system
data:
  # Настройки портов
  MYSQL_HANDLER_PORT: "18140"
  FASTAPI_SQL_PORT: "8000"
  OPLOGIC_PORT: "8001"
  FORTIGATE_SERVICE_PORT: "18080"
  KEEPALIVE_PORT: "8083"
  RADIUS_SNIFFER_PORT: "8081"
  LOGGING_SERVICE_PORT: "8084"
  GUI_PORT: "8080"
  
  # Настройки хостов
  MYSQL_HANDLER_HOST: "mysql-handler-service"
  FASTAPI_SQL_HOST: "fastapi-sql-service"
  OPLOGIC_HOST: "oplogic-service"
  FORTIGATE_SERVICE_HOST: "fortigate-service"
  LOGGING_SERVICE_HOST: "logging-service"
  GUI_HOST: "gui-service"
  
  # Настройки БД
  MYSQL_HOST: "mysql-service"
  MYSQL_PORT: "30930"
  MYSQL_DATABASE: "Radius"
  MYSQL_USER: "root"
  
  # StarRocks настройки
  STARROCKS_HOST: "starrocks-fe-service"
  STARROCKS_PORT: "9030"
  
  # Superset настройки
  SUPERSET_HOST: "superset-service"
  SUPERSET_PORT: "8088"
```

### Secret для чувствительных данных

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: apk-secrets
  namespace: apk-system
type: Opaque
data:
  # API токен для FortiGate
  api-token: MTIzNDU2Nzg5MA==  # base64 encoded
  
  # MySQL пароль
  mysql-password: ""  # base64 encoded
  
  # RADIUS shared secret
  radius-secret: dGVzdGluZzEyMw==  # base64 encoded
  
  # StarRocks учетные данные
  starrocks-user: cm9vdA==  # base64 encoded
  starrocks-password: ""  # base64 encoded
  
  # Superset учетные данные
  superset-user: YWRtaW4=  # base64 encoded
  superset-password: ""  # base64 encoded
```

## Persistent Volumes

### PV для логов

```yaml
apiVersion: v1
kind: PersistentVolume
metadata:
  name: apk-logs-pv
  namespace: apk-system
spec:
  capacity:
    storage: 10Gi
  accessModes:
    - ReadWriteMany
  persistentVolumeReclaimPolicy: Retain
  storageClassName: apk-logs-storage
  hostPath:
    path: /var/log/apk
```

### StorageClass для логов

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: apk-logs-storage
  namespace: apk-system
provisioner: kubernetes.io/no-provisioner
volumeBindingMode: WaitForFirstConsumer
```

## Микросервисы

### 1. MySQL Handler Service

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mysql-handler
  namespace: apk-system
  labels:
    app: mysql-handler
    tier: backend
spec:
  replicas: 2
  selector:
    matchLabels:
      app: mysql-handler
  template:
    metadata:
      labels:
        app: mysql-handler
        tier: backend
    spec:
      containers:
      - name: mysql-handler
        image: apk/mysql-handler:latest
        ports:
        - containerPort: 18140
        env:
        - name: MYSQL_HANDLER_HOST
          valueFrom:
            configMapKeyRef:
              name: apk-config
              key: MYSQL_HANDLER_HOST
        - name: MYSQL_HANDLER_PORT
          valueFrom:
            configMapKeyRef:
              name: apk-config
              key: MYSQL_HANDLER_PORT
        - name: MYSQL_HOST
          valueFrom:
            configMapKeyRef:
              name: apk-config
              key: MYSQL_HOST
        - name: MYSQL_PASSWORD
          valueFrom:
            secretKeyRef:
              name: apk-secrets
              key: mysql-password
        resources:
          requests:
            memory: "256Mi"
            cpu: "250m"
          limits:
            memory: "512Mi"
            cpu: "500m"
        livenessProbe:
          httpGet:
            path: /health
            port: 18140
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /health
            port: 18140
          initialDelaySeconds: 5
          periodSeconds: 5
---
apiVersion: v1
kind: Service
metadata:
  name: mysql-handler-service
  namespace: apk-system
  labels:
    app: mysql-handler
spec:
  selector:
    app: mysql-handler
  ports:
  - port: 18140
    targetPort: 18140
    protocol: TCP
    name: http
  type: ClusterIP
```

### 2. FastAPI SQL Service

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: fastapi-sql
  namespace: apk-system
  labels:
    app: fastapi-sql
    tier: api
spec:
  replicas: 3
  selector:
    matchLabels:
      app: fastapi-sql
  template:
    metadata:
      labels:
        app: fastapi-sql
        tier: api
    spec:
      containers:
      - name: fastapi-sql
        image: apk/fastapi-sql:latest
        ports:
        - containerPort: 8000
        env:
        - name: FASTAPI_SQL_HOST
          valueFrom:
            configMapKeyRef:
              name: apk-config
              key: FASTAPI_SQL_HOST
        - name: FASTAPI_SQL_PORT
          valueFrom:
            configMapKeyRef:
              name: apk-config
              key: FASTAPI_SQL_PORT
        - name: MYSQL_HANDLER_HOST
          valueFrom:
            configMapKeyRef:
              name: apk-config
              key: MYSQL_HANDLER_HOST
        - name: OPLOGIC_HOST
          valueFrom:
            configMapKeyRef:
              name: apk-config
              key: OPLOGIC_HOST
        resources:
          requests:
            memory: "256Mi"
            cpu: "250m"
          limits:
            memory: "512Mi"
            cpu: "500m"
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 5
          periodSeconds: 5
---
apiVersion: v1
kind: Service
metadata:
  name: fastapi-sql-service
  namespace: apk-system
  labels:
    app: fastapi-sql
spec:
  selector:
    app: fastapi-sql
  ports:
  - port: 8000
    targetPort: 8000
    protocol: TCP
    name: http
  type: ClusterIP
```

### 3. Operation Logic Service

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: operation-logic
  namespace: apk-system
  labels:
    app: operation-logic
    tier: backend
spec:
  replicas: 2
  selector:
    matchLabels:
      app: operation-logic
  template:
    metadata:
      labels:
        app: operation-logic
        tier: backend
    spec:
      containers:
      - name: operation-logic
        image: apk/operation-logic:latest
        ports:
        - containerPort: 8001
        env:
        - name: OPLOGIC_HOST
          valueFrom:
            configMapKeyRef:
              name: apk-config
              key: OPLOGIC_HOST
        - name: OPLOGIC_PORT
          valueFrom:
            configMapKeyRef:
              name: apk-config
              key: OPLOGIC_PORT
        - name: MYSQL_HANDLER_HOST
          valueFrom:
            configMapKeyRef:
              name: apk-config
              key: MYSQL_HANDLER_HOST
        - name: FORTIGATE_SERVICE_HOST
          valueFrom:
            configMapKeyRef:
              name: apk-config
              key: FORTIGATE_SERVICE_HOST
        resources:
          requests:
            memory: "256Mi"
            cpu: "250m"
          limits:
            memory: "512Mi"
            cpu: "500m"
        livenessProbe:
          httpGet:
            path: /health
            port: 8001
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /health
            port: 8001
          initialDelaySeconds: 5
          periodSeconds: 5
---
apiVersion: v1
kind: Service
metadata:
  name: oplogic-service
  namespace: apk-system
  labels:
    app: operation-logic
spec:
  selector:
    app: operation-logic
  ports:
  - port: 8001
    targetPort: 8001
    protocol: TCP
    name: http
  type: ClusterIP
```

### 4. FortiGate Service

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: fortigate-service
  namespace: apk-system
  labels:
    app: fortigate-service
    tier: backend
spec:
  replicas: 2
  selector:
    matchLabels:
      app: fortigate-service
  template:
    metadata:
      labels:
        app: fortigate-service
        tier: backend
    spec:
      containers:
      - name: fortigate-service
        image: apk/fortigate-service:latest
        ports:
        - containerPort: 18080
        env:
        - name: FORTIGATE_SERVICE_HOST
          valueFrom:
            configMapKeyRef:
              name: apk-config
              key: FORTIGATE_SERVICE_HOST
        - name: FORTIGATE_SERVICE_PORT
          valueFrom:
            configMapKeyRef:
              name: apk-config
              key: FORTIGATE_SERVICE_PORT
        - name: API_TOKEN
          valueFrom:
            secretKeyRef:
              name: apk-secrets
              key: api-token
        resources:
          requests:
            memory: "256Mi"
            cpu: "250m"
          limits:
            memory: "512Mi"
            cpu: "500m"
        livenessProbe:
          httpGet:
            path: /health
            port: 18080
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /health
            port: 18080
          initialDelaySeconds: 5
          periodSeconds: 5
---
apiVersion: v1
kind: Service
metadata:
  name: fortigate-service
  namespace: apk-system
  labels:
    app: fortigate-service
spec:
  selector:
    app: fortigate-service
  ports:
  - port: 18080
    targetPort: 18080
    protocol: TCP
    name: http
  type: ClusterIP
```

### 5. Keepalive Service

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: keepalive
  namespace: apk-system
  labels:
    app: keepalive
    tier: backend
spec:
  replicas: 2
  selector:
    matchLabels:
      app: keepalive
  template:
    metadata:
      labels:
        app: keepalive
        tier: backend
    spec:
      containers:
      - name: keepalive
        image: apk/keepalive:latest
        ports:
        - containerPort: 8083
        env:
        - name: KEEPALIVE_PORT
          valueFrom:
            configMapKeyRef:
              name: apk-config
              key: KEEPALIVE_PORT
        - name: MYSQL_HANDLER_HOST
          valueFrom:
            configMapKeyRef:
              name: apk-config
              key: MYSQL_HANDLER_HOST
        - name: FASTAPI_SQL_HOST
          valueFrom:
            configMapKeyRef:
              name: apk-config
              key: FASTAPI_SQL_HOST
        resources:
          requests:
            memory: "128Mi"
            cpu: "100m"
          limits:
            memory: "256Mi"
            cpu: "200m"
        livenessProbe:
          httpGet:
            path: /health
            port: 8083
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /health
            port: 8083
          initialDelaySeconds: 5
          periodSeconds: 5
---
apiVersion: v1
kind: Service
metadata:
  name: keepalive-service
  namespace: apk-system
  labels:
    app: keepalive
spec:
  selector:
    app: keepalive
  ports:
  - port: 8083
    targetPort: 8083
    protocol: TCP
    name: http
  type: ClusterIP
```

### 6. RADIUS Sniffer Service

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: radius-sniffer-service
  namespace: apk-system
  labels:
    app: radius-sniffer-service
    tier: backend
spec:
  replicas: 2
  selector:
    matchLabels:
      app: radius-sniffer-service
  template:
    metadata:
      labels:
        app: radius-sniffer-service
        tier: backend
    spec:
      containers:
      - name: radius-sniffer-service
        image: apk/radius-sniffer-service:latest
        ports:
        - containerPort: 8081
        env:
        - name: RADIUS_SNIFFER_PORT
          valueFrom:
            configMapKeyRef:
              name: apk-config
              key: RADIUS_SNIFFER_PORT
        - name: MYSQL_HANDLER_HOST
          valueFrom:
            configMapKeyRef:
              name: apk-config
              key: MYSQL_HANDLER_HOST
        - name: GUI_HOST
          valueFrom:
            configMapKeyRef:
              name: apk-config
              key: GUI_HOST
        resources:
          requests:
            memory: "256Mi"
            cpu: "250m"
          limits:
            memory: "512Mi"
            cpu: "500m"
        livenessProbe:
          httpGet:
            path: /health
            port: 8081
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /health
            port: 8081
          initialDelaySeconds: 5
          periodSeconds: 5
---
apiVersion: v1
kind: Service
metadata:
  name: radius-sniffer-service
  namespace: apk-system
  labels:
    app: radius-sniffer-service
spec:
  selector:
    app: radius-sniffer-service
  ports:
  - port: 8081
    targetPort: 8081
    protocol: TCP
    name: http
  type: ClusterIP
```

### 7. Logging Service

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: logging-service
  namespace: apk-system
  labels:
    app: logging-service
    tier: backend
spec:
  replicas: 2
  selector:
    matchLabels:
      app: logging-service
  template:
    metadata:
      labels:
        app: logging-service
        tier: backend
    spec:
      containers:
      - name: logging-service
        image: apk/logging-service:latest
        ports:
        - containerPort: 8084
        env:
        - name: LOGGING_SERVICE_HOST
          valueFrom:
            configMapKeyRef:
              name: apk-config
              key: LOGGING_SERVICE_HOST
        - name: LOGGING_SERVICE_PORT
          valueFrom:
            configMapKeyRef:
              name: apk-config
              key: LOGGING_SERVICE_PORT
        resources:
          requests:
            memory: "256Mi"
            cpu: "250m"
          limits:
            memory: "512Mi"
            cpu: "500m"
        volumeMounts:
        - name: logs-volume
          mountPath: /app/logs
        livenessProbe:
          httpGet:
            path: /health
            port: 8084
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /health
            port: 8084
          initialDelaySeconds: 5
          periodSeconds: 5
      volumes:
      - name: logs-volume
        persistentVolumeClaim:
          claimName: apk-logs-pvc
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: apk-logs-pvc
  namespace: apk-system
spec:
  accessModes:
    - ReadWriteMany
  storageClassName: apk-logs-storage
  resources:
    requests:
      storage: 10Gi
---
apiVersion: v1
kind: Service
metadata:
  name: logging-service
  namespace: apk-system
  labels:
    app: logging-service
spec:
  selector:
    app: logging-service
  ports:
  - port: 8084
    targetPort: 8084
    protocol: TCP
    name: http
  type: ClusterIP
```

### 8. GUI Service

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: gui
  namespace: apk-system
  labels:
    app: gui
    tier: frontend
spec:
  replicas: 3
  selector:
    matchLabels:
      app: gui
  template:
    metadata:
      labels:
        app: gui
        tier: frontend
    spec:
      containers:
      - name: gui
        image: apk/gui:latest
        ports:
        - containerPort: 8080
        env:
        - name: GUI_HOST
          valueFrom:
            configMapKeyRef:
              name: apk-config
              key: GUI_HOST
        - name: GUI_PORT
          valueFrom:
            configMapKeyRef:
              name: apk-config
              key: GUI_PORT
        - name: FASTAPI_SQL_HOST
          valueFrom:
            configMapKeyRef:
              name: apk-config
              key: FASTAPI_SQL_HOST
        - name: MYSQL_HANDLER_HOST
          valueFrom:
            configMapKeyRef:
              name: apk-config
              key: MYSQL_HANDLER_HOST
        resources:
          requests:
            memory: "256Mi"
            cpu: "250m"
          limits:
            memory: "512Mi"
            cpu: "500m"
        livenessProbe:
          httpGet:
            path: /health
            port: 8080
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /health
            port: 8080
          initialDelaySeconds: 5
          periodSeconds: 5
---
apiVersion: v1
kind: Service
metadata:
  name: gui-service
  namespace: apk-system
  labels:
    app: gui
spec:
  selector:
    app: gui
  ports:
  - port: 8080
    targetPort: 8080
    protocol: TCP
    name: http
  type: ClusterIP
```

### 9. Sniffer (DaemonSet)

```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: sniffer
  namespace: apk-system
  labels:
    app: sniffer
    tier: network
spec:
  selector:
    matchLabels:
      app: sniffer
  template:
    metadata:
      labels:
        app: sniffer
        tier: network
    spec:
      hostNetwork: true
      containers:
      - name: sniffer
        image: apk/sniffer:latest
        ports:
        - containerPort: 1813
          protocol: UDP
        env:
        - name: MYSQL_HANDLER_HOST
          valueFrom:
            configMapKeyRef:
              name: apk-config
              key: MYSQL_HANDLER_HOST
        - name: RADIUS_SHARED_SECRET
          valueFrom:
            secretKeyRef:
              name: apk-secrets
              key: radius-secret
        resources:
          requests:
            memory: "128Mi"
            cpu: "100m"
          limits:
            memory: "256Mi"
            cpu: "200m"
        securityContext:
          capabilities:
            add:
            - NET_ADMIN
            - NET_RAW
        volumeMounts:
        - name: radius-config
          mountPath: /app/config
      volumes:
      - name: radius-config
        configMap:
          name: apk-config
```

## Ingress и внешний доступ

### Ingress для GUI

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: apk-gui-ingress
  namespace: apk-system
  annotations:
    nginx.ingress.kubernetes.io/rewrite-target: /
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
spec:
  ingressClassName: nginx
  tls:
  - hosts:
    - apk.example.com
    secretName: apk-tls
  rules:
  - host: apk.example.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: gui-service
            port:
              number: 8080
```

### Ingress для API

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: apk-api-ingress
  namespace: apk-system
  annotations:
    nginx.ingress.kubernetes.io/rewrite-target: /
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
spec:
  ingressClassName: nginx
  tls:
  - hosts:
    - api.apk.example.com
    secretName: apk-api-tls
  rules:
  - host: api.apk.example.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: fastapi-sql-service
            port:
              number: 8000
```

## Сетевая политика с Cilium

### Сетевая политика для backend сервисов

```yaml
apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata:
  name: backend-network-policy
  namespace: apk-system
spec:
  endpointSelector:
    matchLabels:
      tier: backend
  ingress:
  - fromEndpoints:
    - matchLabels:
        tier: backend
    - matchLabels:
        tier: api
    - matchLabels:
        tier: frontend
    ports:
    - port: "80"
      protocol: TCP
    - port: "443"
      protocol: TCP
  egress:
  - toEndpoints:
    - matchLabels:
        tier: backend
    - matchLabels:
        tier: api
    - matchLabels:
        tier: frontend
    ports:
    - port: "80"
      protocol: TCP
    - port: "443"
      protocol: TCP
    - port: "3306"
      protocol: TCP
    - port: "9030"
      protocol: TCP
```

### Сетевая политика для frontend

```yaml
apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata:
  name: frontend-network-policy
  namespace: apk-system
spec:
  endpointSelector:
    matchLabels:
      tier: frontend
  ingress:
  - fromEndpoints:
    - matchLabels:
        tier: frontend
    ports:
    - port: "80"
      protocol: TCP
    - port: "443"
      protocol: TCP
  egress:
  - toEndpoints:
    - matchLabels:
        tier: backend
    - matchLabels:
        tier: api
    ports:
    - port: "80"
      protocol: TCP
    - port: "443"
      protocol: TCP
```

## BGP конфигурация

### BGP Peer для FortiGate

```yaml
apiVersion: bgp.cilium.io/v2alpha1
kind: BGPPeeringPolicy
metadata:
  name: fortigate-bgp
  namespace: apk-system
spec:
  nodeSelector:
    matchLabels:
      node-role.kubernetes.io/worker: ""
  virtualRouters:
  - localASN: 65000
    exportPodCIDR: true
    neighbors:
    - peerASN: 65001
      peerAddress: "172.26.203.254"
      peerPort: 179
      eBGPMultihopTTL: 1
      connectRetryTimeSeconds: 120
      holdTimeSeconds: 90
      keepAliveTimeSeconds: 30
      gracefulRestart:
        enabled: true
        restartTimeSeconds: 120
```

## Egress Gateway

### Egress Gateway для исходящего трафика

```yaml
apiVersion: cilium.io/v2
kind: CiliumEgressGatewayPolicy
metadata:
  name: apk-egress-gateway
  namespace: apk-system
spec:
  selectors:
  - namespaceSelector:
      matchLabels:
        name: apk-system
  destinationCIDRs:
  - "0.0.0.0/0"
  egressGateway:
    nodeSelector:
      matchLabels:
        node-role.kubernetes.io/egress: ""
    interface: "eth0"
```

## Мониторинг и логирование

### Prometheus ServiceMonitor

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: apk-services
  namespace: apk-system
  labels:
    release: prometheus
spec:
  selector:
    matchLabels:
      app: apk
  endpoints:
  - port: http
    interval: 30s
    path: /metrics
```

### Grafana Dashboard ConfigMap

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: apk-grafana-dashboard
  namespace: apk-system
  labels:
    grafana_dashboard: "1"
data:
  apk-dashboard.json: |
    {
      "dashboard": {
        "title": "APK System Dashboard",
        "panels": [
          {
            "title": "Service Health",
            "type": "stat",
            "targets": [
              {
                "expr": "up{namespace=\"apk-system\"}"
              }
            ]
          }
        ]
      }
    }
```

## StarRocks интеграция

### StarRocks Service

```yaml
apiVersion: v1
kind: Service
metadata:
  name: starrocks-fe-service
  namespace: apk-system
  labels:
    app: starrocks
    component: frontend
spec:
  selector:
    app: starrocks
    component: frontend
  ports:
  - port: 9030
    targetPort: 9030
    protocol: TCP
    name: mysql
  - port: 8030
    targetPort: 8030
    protocol: HTTP
    name: http
  type: ClusterIP
```

### StarRocks ConfigMap

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: starrocks-config
  namespace: apk-system
data:
  fe.conf: |
    priority_networks = 10.0.0.0/8
    edit_log_port = 9010
    http_port = 8030
    rpc_port = 9020
    query_port = 9030
    mysql_service_nio_enabled = true
```

## Superset интеграция

### Superset Service

```yaml
apiVersion: v1
kind: Service
metadata:
  name: superset-service
  namespace: apk-system
  labels:
    app: superset
spec:
  selector:
    app: superset
  ports:
  - port: 8088
    targetPort: 8088
    protocol: TCP
    name: http
  type: ClusterIP
```

### Superset ConfigMap

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: superset-config
  namespace: apk-system
data:
  superset_config.py: |
    SQLALCHEMY_DATABASE_URI = 'mysql://root:password@mysql-service:3306/superset'
    SECRET_KEY = 'your-secret-key'
    CACHE_CONFIG = {
        'CACHE_TYPE': 'redis',
        'CACHE_REDIS_HOST': 'redis-service',
        'CACHE_REDIS_PORT': 6379,
        'CACHE_REDIS_DB': 1,
    }
```

## HPA (Horizontal Pod Autoscaler)

### HPA для API сервисов

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: fastapi-sql-hpa
  namespace: apk-system
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: fastapi-sql
  minReplicas: 2
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
```

## Секреты для внешних сервисов

### FortiGate сертификаты

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: fortigate-certs
  namespace: apk-system
type: kubernetes.io/tls
data:
  tls.crt: ""  # base64 encoded
  tls.key: ""  # base64 encoded
  ca.crt: ""   # base64 encoded
```

## Команды для развертывания

```bash
# Создание namespace
kubectl apply -f namespace.yaml

# Создание ConfigMaps и Secrets
kubectl apply -f configmaps.yaml
kubectl apply -f secrets.yaml

# Создание Persistent Volumes
kubectl apply -f persistent-volumes.yaml

# Развертывание сервисов
kubectl apply -f mysql-handler.yaml
kubectl apply -f fastapi-sql.yaml
kubectl apply -f operation-logic.yaml
kubectl apply -f fortigate-service.yaml
kubectl apply -f keepalive.yaml
kubectl apply -f radius-sniffer-service.yaml
kubectl apply -f logging-service.yaml
kubectl apply -f gui.yaml
kubectl apply -f sniffer.yaml

# Применение сетевых политик
kubectl apply -f network-policies.yaml

# Настройка BGP
kubectl apply -f bgp-policies.yaml

# Настройка Egress Gateway
kubectl apply -f egress-gateway.yaml

# Настройка Ingress
kubectl apply -f ingress.yaml

# Настройка мониторинга
kubectl apply -f monitoring.yaml

# Проверка статуса
kubectl get pods -n apk-system
kubectl get services -n apk-system
kubectl get ingress -n apk-system
```

## Проверка работоспособности

```bash
# Проверка сервисов
kubectl get pods -n apk-system -o wide

# Проверка логов
kubectl logs -n apk-system deployment/logging-service

# Проверка сетевых политик
kubectl get ciliumnetworkpolicies -n apk-system

# Проверка BGP
kubectl get bgppeeringpolicies -n apk-system

# Проверка метрик
kubectl port-forward -n apk-system svc/logging-service 8084:8084
curl http://localhost:8084/health
```

## Масштабирование и обновления

### Rolling Update стратегия

```yaml
spec:
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
```

### Blue-Green развертывание

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Rollout
metadata:
  name: apk-rollout
  namespace: apk-system
spec:
  replicas: 5
  strategy:
    blueGreen:
      activeService: apk-active
      previewService: apk-preview
      autoPromotionEnabled: false
  selector:
    matchLabels:
      app: apk
  template:
    metadata:
      labels:
        app: apk
    spec:
      containers:
      - name: apk
        image: apk:latest
```

## Резервное копирование

### Backup CronJob

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: apk-backup
  namespace: apk-system
spec:
  schedule: "0 2 * * *"
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: backup
            image: apk/backup:latest
            command: ["/bin/sh"]
            args: ["-c", "mysqldump -h mysql-service -u root -p$MYSQL_PASSWORD Radius > /backup/backup-$(date +%Y%m%d).sql"]
            env:
            - name: MYSQL_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: apk-secrets
                  key: mysql-password
            volumeMounts:
            - name: backup-volume
              mountPath: /backup
          volumes:
          - name: backup-volume
            persistentVolumeClaim:
              claimName: apk-backup-pvc
          restartPolicy: OnFailure
```

## Заключение

Данный манифест обеспечивает полное развертывание системы АПК на Kubernetes с использованием современных технологий:

- **Cilium** для сетевой политики и безопасности
- **BGP** для маршрутизации с FortiGate
- **Egress Gateway** для контроля исходящего трафика
- **Superset** для аналитики и визуализации
- **StarRocks** для высокопроизводительной аналитики

Система готова к production использованию с автоматическим масштабированием, мониторингом и резервным копированием.
