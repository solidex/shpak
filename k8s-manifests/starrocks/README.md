# StarRocks для shpak-k8s

## Быстрый старт

**Одной командой:**
```bash
./setup_starrocks.sh all 'YourPassword123!'
```

**Или пошагово:**
```bash
./setup_starrocks.sh create-secret 'YourPassword123!'
./setup_starrocks.sh install
./setup_starrocks.sh init
```

## Команды

```bash
./setup_starrocks.sh all 'pass'           # Всё одной командой (secret + install + init)
./setup_starrocks.sh create-secret 'pass' # Создать секрет (default: 'password')
./setup_starrocks.sh install              # Установить
./setup_starrocks.sh init                 # Создать БД RADIUS
./setup_starrocks.sh status               # Статус
./setup_starrocks.sh port-forward         # Port-forward (для доступа снаружи)
./setup_starrocks.sh logs [fe|be]         # Логи
./setup_starrocks.sh resize be 150Gi      # Расширить диск
./setup_starrocks.sh uninstall            # Удалить (сохранить PVC)
```

## Подключение

**Изнутри кластера (статические IP):**
```python
host = '10.152.183.10'
port = 9030
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
| `starrocks-values.yaml` | Helm конфигурация |
| `create_database.sql` | SQL схема RADIUS (12 полей, retention 365 дней) |
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

```bash
# Pod не запускается
kubectl describe pod starrocks-be-0 -n starrocks
kubectl logs starrocks-be-0 -n starrocks --tail=100

# Изменить retention (если диск заполнился)
# Уменьшить с 365 до 180 дней
mysql -h 127.0.0.1 -P 9030 -u root -p -e "
ALTER TABLE RADIUS.UTMLogs SET ('dynamic_partition.start' = '-180');
"

# Увеличить retention до 2 лет
mysql -h 127.0.0.1 -P 9030 -u root -p -e "
ALTER TABLE RADIUS.UTMLogs SET ('dynamic_partition.start' = '-730');
"

# Расширить PVC (если нужно больше места)
./setup_starrocks.sh resize be 150Gi
```

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
