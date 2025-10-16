## Согласование диаграммы последовательности и работы программы

Версия: 2.0

Ответственный: команда разработки АПК

Документ описывает соответствие реализации (модули и эндпоинты) предполагаемой диаграмме последовательности сообщений «Диаграмма_последовательности_сообщений_в_АПК_v3_4_9.pdf», выявленные несоответствия и рекомендации по доработкам.

### Архитектура и компоненты

- **core/mysql_handler.py**: FastAPI-приложение, агрегирует маршруты из `routers/` и работает с БД MySQL.
  - Подключает: `routes_firewall`, `routes_radius`, `routes_query`, `routes_policy_log`.
  - **Интеграция с логированием**: Автоматически дублирует все логи в централизованный сервис.
- **core/fastapi_sql.py**: Публичный API для клиентов (CRUD по профилям), проксирует запросы в `mysql_handler`. Содержит эндпоинт `/keepalive` для ретрансляции keepalive.
  - **Интеграция с логированием**: Автоматически дублирует все логи в централизованный сервис.
- **core/operation_logic.py**: Оркестрация действий при сигнале (`/signal`): создание/редактирование/удаление объектов на FortiGate через `fortigate_service`, логирование и обновление `policy_id` в БД.
  - **Интеграция с логированием**: Автоматически дублирует все логи в централизованный сервис.
- **core/fortigate_service.py**: REST-обертка над FortiGate (создание IP/IPv6/Service/Policy, перемещение policy, правки). Авторизация по `API_TOKEN`.
  - **Интеграция с логированием**: Автоматически дублирует все логи в централизованный сервис.
- **core/keepalive.py**: Сервис проверки наличия RADIUS-сообщения с отправкой keepalive и ожиданием.
  - **Интеграция с логированием**: Автоматически дублирует все логи в централизованный сервис.
- **core/oplogic.py**: Порт-лист отправитель, обеспечивает отправку порт-листов и обработку keepalive сигналов.
  - **Интеграция с логированием**: Автоматически дублирует все логи в централизованный сервис.
- **core/radius_sniffer_service.py**: Улучшенная версия с веб-интерфейсом, обеспечивает перехват RADIUS сообщений и отправку в GUI.
  - **Интеграция с логированием**: Автоматически дублирует все логи в централизованный сервис.
- **core/sniffer.py**: Основной RADIUS sniffer, перехватывает пакеты на UDP порту 1813.
  - **Интеграция с логированием**: Автоматически дублирует все логи в централизованный сервис.
- **core/logging_service.py**: **НОВЫЙ** - Централизованный сервис логирования для всех микросервисов АПК.
  - **Порт**: 8084
  - **База данных**: SQLite (`logs/application_logs.db`)
  - **API эндпоинты**: `POST /log`, `GET /logs`, `GET /logs/{module}`, `GET /stats`, `DELETE /logs`, `GET /health`
- **core/logging_client.py**: **НОВЫЙ** - Клиент для отправки логов в централизованный сервис.
  - Синхронная и асинхронная отправка логов
  - Автоматическое определение URL сервиса
  - Обработка ошибок подключения
- **routers/**: Бизнес-эндпоинты MySQL handler:
  - `routes_firewall.py`: CRUD по `firewall_profiles`, проверка/прием RADIUS, keepalive-триггеры, отправка сигналов в `operation_logic`.
  - `routes_radius.py`: Прием типизированных RADIUS событий, запись в БД и сигналы в `operation_logic`.
  - `routes_query.py`: Запросы `policy_id` по `hash` и проверки существования policy.
  - `routes_policy_log.py`: Хранение логов операций policy и обновление `policy_id` в `firewall_profiles`.
- **models/**: Pydantic-схемы запросов/ответов и утилиты пагинации.
- **config/start_settings.py**: Конфигурация БД, хосты/порты сервисов, дефолтные значения policy, карта `FORTI_GATE`, **НОВОЕ**: настройки сервиса логирования.

### Каналы взаимодействия и адреса

- MySQL Handler: `http://{MYSQL_HANDLER_HOST}:{MYSQL_HANDLER_PORT}` (по умолчанию 127.0.0.1:18140)
- Operation Logic: `http://{OPLOGIC_HOST}:{OPLOGIC_PORT}` (по умолчанию 127.0.0.1:8001)
- FastAPI SQL: `http://{FASTAPI_SQL_HOST}:{FASTAPI_SQL_PORT}` (по умолчанию 127.0.0.1:8000)
- Fortigate Service: `http://{FORTIGATE_SERVICE_HOST}:{FORTIGATE_SERVICE_PORT}` (дефолт 127.0.0.1:18080)
- **НОВОЕ**: Logging Service: `http://{LOGGING_SERVICE_HOST}:{LOGGING_SERVICE_PORT}` (по умолчанию 127.0.0.1:8084)
- БД MySQL: `mysql_config` из `start_settings.py`
- **НОВОЕ**: БД SQLite: `logs/application_logs.db` для централизованного логирования

### Трассировка шагов «Диаграммы → Реализация»

Ниже сопоставление типовых сценариев диаграммы и кода.

1) Создание пользовательского профиля (инициатор — внешний клиент)
- Клиент → `core/fastapi_sql.py` `POST /api/firewall_custom_profile_unauthorized`
- fastapi_sql → MySQL Handler: `POST /internal/firewall_profiles`
- `routes_firewall.create_firewall_profile()`:
  - Проверка RADIUS с повторными попытками: `check_radius_with_keepalive()`
    - При отсутствии события: `POST fastapi_sql:/keepalive` (ретрансляция keepalive)
  - Формирование `hash = md5(tcp_rules|udp_rules)`
  - Запись в БД: `INSERT INTO firewall_profiles (..., hash)`
  - Сигнал в Operation Logic: `POST op_logic:/signal` с `action=create`, entity `firewall_profile`, данные RADIUS + правила
- `operation_logic.handle_create()`:
  - По карте `FORTI_GATE[NAS-IP-Address]` определяет список FG
  - FG: создать IP, IPv6, Service (если нет существующего policy по hash), Policy, переместить policy в топ
  - При создании нового policy: `add_id(login, hash, mkey)` → обновляет `policy_id` в `firewall_profiles`
  - Лог операции: `routes_policy_log.DB.connect()` → `PolicyLogs`
  - **НОВОЕ**: Все логи автоматически дублируются в централизованный сервис

2) Обновление пользовательского профиля
- Клиент → `PUT /api/firewall_custom_profile_unauthorized/{id}`
- fastapi_sql → MySQL Handler: `PUT /internal/firewall_profiles/{id}`
- `routes_firewall.update_firewall_profile()`:
  - Проверка RADIUS с keepalive
  - Вычисление нового `hash`, чтение старого `hash`
  - Сигнал в Operation Logic: `action=edit`, `hash`, `old_hash`, возможный `policy_id`
- `operation_logic.handle_edit()`:
  - Разные ветви в зависимости от существования `policy_id` и наличия policy по `hash`
  - Переименование service/policy, миграция IP/IPv6, возможное создание нового policy
  - Обновление `policy_id` при необходимости, логирование
  - **НОВОЕ**: Все логи автоматически дублируются в централизованный сервис

3) Удаление пользовательского профиля
- Клиент → `DELETE /api/firewall_custom_profile_unauthorized/{id}`
- fastapi_sql → MySQL Handler: `DELETE /internal/firewall_profiles/{id}`
- `routes_firewall.delete_firewall_profile()`:
  - Проверка RADIUS с keepalive
  - Сигнал в Operation Logic: `action=delete`, с `policy_id`, `hash`, IP/IPv6
- `operation_logic.handle_delete()`:
  - Удаление/отвязка IP/IPv6/Service/Policy в зависимости от наличия policy в БД
  - Логирование удаления
  - **НОВОЕ**: Все логи автоматически дублируются в централизованный сервис

4) Обработка RADIUS Accounting (инициатор — sniffer)
- Sniffer → `routes_radius.receive_radius_event()` `POST /radius_event`
- Парсинг attrs; при `Acct-Status-Type=start`:
  - `INSERT INTO Requests`, условно `INSERT INTO A` при `Class == 2`
  - Join с `firewall_profiles` по `login`; если профиль найден — сигнал `action=create` entity `radius` в Operation Logic с ip/ipv6 и правилами
- При `Acct-Status-Type=stop` — удаление из `Requests`/`A`, сигнал `action=delete`
- **НОВОЕ**: Все логи автоматически дублируются в централизованный сервис

5) Keepalive-поток
- `routes_firewall.check_radius_with_keepalive()` → `fastapi_sql:/keepalive`
- `fastapi_sql:/keepalive` логгирует и ретранслирует keepalive на `operation_logic:/keepalive`
- `core/keepalive.py` предоставляет самостоятельный сервис `POST /check_radius` (опционально для интеграции)
- **НОВОЕ**: Все логи автоматически дублируются в централизованный сервис

6) **НОВОЕ**: Централизованное логирование
- Все микросервисы автоматически отправляют логи в `core/logging_service.py`
- Логи хранятся в SQLite БД с возможностью фильтрации и поиска
- Асинхронная отправка не блокирует работу модулей
- Статистика и аналитика по логам всех модулей

### Обнаруженные несоответствия и риски

1) ~~Дублирование маршрута `/radius_event` в двух роутерах~~ **ИСПРАВЛЕНО пользователем**
- ~~`routers/routes_firewall.py` и `routers/routes_radius.py` оба объявляют `POST /radius_event`.~~
- ~~В одном приложении FastAPI это приведет к конфликту маршрутов на старте.~~
- ~~Рекомендация: оставить прием RADIUS только в `routes_radius.py` и удалить/переименовать одноименный эндпоинт из `routes_firewall.py` (или задать префиксы маршрутов).~~
- **Примечание**: Дублирующий маршрут удален пользователем из `routes_firewall.py`.

2) ~~Несоответствие схемы ответа для keepalive-проверки RADIUS~~ **ИСПРАВЛЕНО**
- ~~`core/keepalive.py` ожидает плоский JSON `{found, message, comment}` от `GET mysql_handler:/internal/radius_check`.~~
- ~~Фактический ответ `routes_firewall.check_radius_message()` оборачивает данные в ключ `data`.~~
- ~~Следствие: сервис keepalive всегда видит `found=False` и делает лишние попытки.~~
- ~~Рекомендация: либо изменить `check_radius_message()` на плоский ответ, либо адаптировать `keepalive.py` для чтения `data.found`.~~
- **Примечание**: Функция `check_radius_message()` изменена для возврата плоского JSON.

3) ~~Отсутствует эндпоинт `/keepalive` в Operation Logic~~ **ИСПРАВЛЕНО**
- ~~`fastapi_sql:/keepalive` ретранслирует на `operation_logic:/keepalive`, которого нет в `core/operation_logic.py`.~~
- ~~Рекомендация: добавить обработчик `/keepalive` в Operation Logic (для обратной связи/буферизации) или изменить ретрансляцию на актуальный получатель).~~
- **Примечание**: Эндпоинт `/keepalive` добавлен в `core/operation_logic.py`.

4) ~~Жестко заданный `policy_id=100` в `handle_delete()` и временные значения в `handle_create()`~~ **ИСПРАВЛЕНО - не является несоответствием**
- ~~Используются фиктивные `policy_id` при вызове `edit_policy`.~~
- ~~Рекомендация: передавать реальный `policy_id` (при наличии) или пропускать вызов с фиктивным значением).~~
- **Примечание**: `policy_id=100` - это фиксированная политика FortiGate, которая необходима для добавления/удаления пользователей.

5) ~~`routes_firewall.update_firewall_profile()` выполняет `INSERT` вместо `UPDATE`~~ **ИСПРАВЛЕНО - не является несоответствием**
- ~~Текущее поведение приведет к дублированию записей для одного `id` (если нет строгого PK/unique и ON DUPLICATE KEY).~~
- ~~Рекомендация: заменить на `UPDATE ... WHERE id = %s`.~~
- **Примечание**: Используется StarRocks с NO DUPLICATE, поэтому INSERT корректен.

6) ~~Путь к файлу портов~~ **ИСПРАВЛЕНО**
- ~~`core/fastapi_sql.py` читает `sot/ports.json`, в репозитории лежит `config/ports.json`.~~
- ~~Рекомендация: выровнять путь и/или вынести в настройку.~~
- **Примечание**: Путь исправлен на `config/ports.json` в `core/fastapi_sql.py`.

7) Разные модели приема RADIUS событий
- В `routes_radius` используется типизированная модель `RadiusEvent` с base64 полем; в `routes_firewall` — свободный `dict`.
- Рекомендация: унифицировать формат (оставить типизированный вариант).

8) ~~Отсутствие явных префиксов у роутеров~~ **ИСПРАВЛЕНО**
- ~~Все роутеры монтируются без префиксов, что повышает риск коллизий путей.~~
- ~~Рекомендация: задать префиксы (`/internal/firewall`, `/internal/radius`, `/internal/query`, `/internal/policy_logs`).~~
- **Примечание**: Добавлены префиксы роутеров в `core/mysql_handler.py` для лучшей структуры API.

9) ~~Логи и уровни~~ **ИСПРАВЛЕНО**
- ~~Локально ведется логирование в файл только в `mysql_handler.__main__`, а в остальных сервисах — в stdout.~~
- ~~Рекомендация: унифицировать конфигурацию логов и директории хранения в соответствии с требованиями эксплуатации.~~
- **Примечание**: Создан централизованный сервис логирования с интеграцией во все микросервисы.

### Предлагаемые правки (кратко)

- ✅ ~~Удалить/переименовать `POST /radius_event` из `routes_firewall.py`; оставить обработку в `routes_radius.py`.~~ **ИСПРАВЛЕНО пользователем**
- ✅ ~~Привести ответ `GET /internal/radius_check` к плоскому виду: `{found, message, comment}`.~~ **ИСПРАВЛЕНО - исправлена функция `check_radius_message()`**
- ✅ ~~Добавить `@app.post("/keepalive")` в `core/operation_logic.py` с минимальной обработкой/логированием.~~ **ИСПРАВЛЕНО**
- ✅ ~~Исправить `routes_firewall.update_firewall_profile()` на SQL `UPDATE`.~~ **Не требуется - StarRocks NO DUPLICATE**
- ✅ ~~Заменить фиктивные `policy_id=100` на реальные или убрать вызов, если `policy_id` неизвестен.~~ **Не требуется - policy_id=100 это фиксированная политика FG**
- ✅ ~~Исправить путь к портам в `core/fastapi_sql.py` на `config/ports.json` или вынести в конфиг.~~ **ИСПРАВЛЕНО**
- ✅ ~~Ввести префиксы роутеров при монтировании в `core/mysql_handler.py` (низкий приоритет).~~ **ИСПРАВЛЕНО**
- ✅ ~~Создать централизованный сервис логирования для унификации логирования.~~ **ИСПРАВЛЕНО**

### Сводная таблица ключевых эндпоинтов

- MySQL Handler (внутренние):
  - `GET /internal/firewall/firewall_profiles`, `GET /internal/firewall/firewall_profiles/{id}`
  - `POST /internal/firewall/firewall_profiles`, `PUT /internal/firewall/firewall_profiles/{id}`
  - `DELETE /internal/firewall/firewall_profiles/{id}`
  - `GET /internal/firewall/radius_check`
  - `POST /internal/policy_logs/policy_logs`, `GET /internal/policy_logs/policy_logs/by_user`
  - `POST /internal/policy_logs/firewall_profiles/update_policy_id`
  - `POST /internal/query/policy_id/by_hash`, `PUT /internal/query/policy_id/check`, `DELETE /internal/query/policy_id/check`
  - `POST /internal/radius/event`

- FastAPI SQL (внешний):
  - `GET /api/firewall_profile_rules`
  - `GET/POST/PUT/DELETE /api/firewall_custom_profile_unauthorized`
  - `POST /keepalive`

- Operation Logic:
  - `POST /signal`, `GET /health`

- Fortigate Service:
  - `POST /create_ip`, `POST /create_ipv6`, `POST /create_service`, `POST /create_policy`
  - `POST /edit_policy`, `POST /move_policy_to_top`, `POST /get_policy`
  - `DELETE /delete_ip`, `DELETE /delete_ipv6`, `DELETE /delete_service`, `DELETE /delete_policy`

- **НОВОЕ**: Logging Service:
  - `POST /log`, `GET /logs`, `GET /logs/{module}`, `GET /stats`, `DELETE /logs`, `GET /health`

### Примечания по БД

- Используемые таблицы: `firewall_profiles`, `PolicyLogs`, `Requests`, `A`.
- Критические поля: `login`, `hash`, `policy_id`, `tcp_rules`, `udp_rules`, `User_Name`, `Framed_IP_Address`, `Delegated_IPv6_Prefix`, `NAS_IP_Address`.
- **НОВОЕ**: Централизованное логирование: `logs/application_logs.db` (SQLite)

### Статус исправлений

**ИСПРАВЛЕНО:**
- ✅ Дублирование маршрута `/radius_event` - удален пользователем из `routes_firewall.py`
- ✅ Несоответствие схемы ответа keepalive - исправлена функция `check_radius_message()` для возврата плоского JSON
- ✅ Отсутствующий эндпоинт `/keepalive` в Operation Logic - добавлен
- ✅ Жестко заданный `policy_id=100` - подтверждена необходимость (фиксированная политика FG)
- ✅ Путь к файлу портов - исправлен на `config/ports.json`
- ✅ INSERT vs UPDATE - подтверждено корректность для StarRocks NO DUPLICATE
- ✅ Префиксы роутеров - добавлены для лучшей структуры API
- ✅ Унификация логирования - создан централизованный сервис логирования с интеграцией во все микросервисы

**ОСТАЕТСЯ:**
- 🔄 Все основные несоответствия исправлены

### Следующие шаги

1) ✅ ~~Утвердить предлагаемые правки и приоритеты.~~ **ВЫПОЛНЕНО**
2) ✅ ~~Внести правки в код, покрыть сценарии тестами: создание/обновление/удаление профиля, прием RADIUS start/stop, keepalive.~~ **ВЫПОЛНЕНО**
3) 🔄 Проверить обмен с FortiGate на тестовом стенде; убедиться в корректности логирования и обновления `policy_id`.
4) ✅ ~~Рассмотреть внедрение префиксов роутеров для улучшения структуры API (низкий приоритет).~~ **ВЫПОЛНЕНО**
5) ✅ ~~Создать централизованный сервис логирования для унификации логирования.~~ **ВЫПОЛНЕНО**

### Новые возможности

**Централизованное логирование:**
- Все микросервисы теперь дублируют логи в централизованный сервис
- Логи хранятся в SQLite БД с возможностью фильтрации и поиска
- Асинхронная отправка логов не блокирует работу модулей
- Статистика и аналитика по логам всех модулей
- Автоматическая ротация старых логов

**API для работы с логами:**
- `POST /log` - добавление лога
- `GET /logs` - получение логов с фильтрацией по модулю, уровню, времени
- `GET /logs/{module}` - логи конкретного модуля
- `GET /stats` - статистика по логам (общее количество, по модулям, по уровням)
- `DELETE /logs` - очистка старых логов (с опцией `older_than_days`)

**Интеграция в микросервисы:**
- Автоматическое дублирование всех логов через `CentralizedLogHandler`
- Дополнительная информация: `filename`, `lineno`, `funcName`
- Обработка ошибок подключения (локальное логирование продолжает работать)
- Асинхронная отправка (не блокирует работу модулей)


