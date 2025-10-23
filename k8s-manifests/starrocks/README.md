# StarRocks для shpak-k8s

## Быстрый старт

**MicroK8s (включить нужные аддоны):**
```bash
microk8s enable dns storage helm3
```

**Добавить права на выполнение:**
```bash
chmod +x setup_starrocks.sh uninstall_starrocks.sh
```

**Одной командой:**
```bash
./setup_starrocks.sh all 'YourPassword123!'
```

> **Примечание:** Скрипт автоматически определяет MicroK8s и использует `microk8s kubectl` / `microk8s helm3`

**Или пошагово:**
```bash
./setup_starrocks.sh create-secret 'YourPassword123!'
./setup_starrocks.sh install
./setup_starrocks.sh init
```

## Команды

**Установка:**
```bash
./setup_starrocks.sh all 'pass'           # Всё одной командой (secret + install + init)
./setup_starrocks.sh create-secret 'pass' # Создать секрет (default: 'password')
./setup_starrocks.sh install              # Установить
./setup_starrocks.sh init                 # Создать БД RADIUS
```

**Управление:**
```bash
./setup_starrocks.sh status               # Статус
./setup_starrocks.sh port-forward         # Port-forward (для доступа снаружи)
./setup_starrocks.sh logs [fe|be]         # Логи
./setup_starrocks.sh resize be 150Gi      # Расширить диск
```

**Удаление:**
```bash
./uninstall_starrocks.sh                  # Удалить (сохранить PVC)
./uninstall_starrocks.sh --delete-all     # Удалить всё (включая PVC и namespace)
./uninstall_starrocks.sh --delete-repo    # Также удалить Helm репозиторий
./uninstall_starrocks.sh --delete-all --delete-repo  # Полное удаление
```

## Подключение

**Изнутри кластера:**
```python
# Используйте фактический ClusterIP (узнать: ./setup_starrocks.sh status)
host = '10.152.183.118'  # Или DNS имя
port = 9030

# Или через DNS (рекомендуется):
host = 'kube-starrocks-fe-service.starrocks.svc.cluster.local'
```

**Снаружи (port-forward):**
```bash
./setup_starrocks.sh port-forward
mysql -h 127.0.0.1 -P 9030 -u root -p
```

## Конфигурация

```yaml
Service:    ClusterIP (10.152.183.10, 10.152.183.11)
FE:         3 реплики × 20Gi = 60 GB
BE:         3 реплики × 100Gi = 300 GB
Репликация: 3
Retention:  365 дней (12 месяцев)
```

**Расчёт для 50k пользователей:**
- За 12 месяцев: ~152M записей
- Размер данных: ~84 GB (12 полей)
- **Рекомендуется:** 100Gi на BE достаточно

## Схема данных

**12 полей:**
- event_time, user, action, utmtype
- source (IP:port), destination (IP:port), service
- target (hostname или url), category
- threat, level, msg

## Файлы

| Файл | Назначение |
|------|------------|
| `setup_starrocks.sh` | Установка и управление |
| `uninstall_starrocks.sh` | Удаление StarRocks |
| `reinstall.sh` | Быстрая переустановка |
| `starrocks-values.yaml` | Helm конфигурация |
| `create_database.sql` | SQL схема RADIUS (12 полей, retention 365 дней) |
| `troubleshooting.txt` | Диагностика проблем |
| `README.md` | Документация |

## Мониторинг

```bash
# Статус кластера
./setup_starrocks.sh status

# Размер таблиц (SQL)
mysql -h 127.0.0.1 -P 9030 -u root -p -e "
SELECT TABLE_NAME, 
       ROUND((DATA_LENGTH + INDEX_LENGTH) / 1024 / 1024 / 1024, 2) AS GB
FROM information_schema.TABLES 
WHERE TABLE_SCHEMA = 'RADIUS'
ORDER BY GB DESC;
"

# Статус узлов BE
mysql -h 127.0.0.1 -P 9030 -u root -p -e "SHOW BACKENDS\G"
```

## Troubleshooting

**PVC в статусе Pending:**
```bash
# Удалить всё и переустановить
chmod +x uninstall_starrocks.sh
./uninstall_starrocks.sh --delete-all
./setup_starrocks.sh all 'password'
```

**Проверка подов:**
```bash
./setup_starrocks.sh status
microk8s kubectl describe pod kube-starrocks-fe-0 -n starrocks
microk8s kubectl logs kube-starrocks-fe-0 -n starrocks
```

**Изменить retention:**
```bash
# Уменьшить с 365 до 180 дней
mysql -h 127.0.0.1 -P 9030 -u root -p -e "
ALTER TABLE RADIUS.UTMLogs SET ('dynamic_partition.start' = '-180');
"
```

📖 См. `troubleshooting.txt` для деталей

## PV и отказоустойчивость

- **replication_num = 3** → данные реплицируются на 3 узла
- При отказе 1 узла → кластер работает ✅
- При отказе 2 узлов → Read-Only режим ⚠️
- Используйте cloud StorageClass (AWS EBS, GCP PD) для production

## Production checklist

- [ ] Cloud StorageClass (не hostPath)
- [ ] Регулярные бэкапы
- [ ] Prometheus alerts (disk usage > 70%)
- [ ] Pod Anti-Affinity (поды на разных узлах)
- [ ] Firewall для ограничения доступа

---

**Готово к работе!** ✅
