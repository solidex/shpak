# Миграция структуры проекта в app/

## ✅ Выполненные изменения

### Новая структура проекта:
```
shpak-k8s/
├── app/
│   ├── __init__.py
│   ├── config/          # Конфигурация (env.py, ports.json)
│   ├── core/            # Микросервисы (mhe_*.py)
│   ├── models/          # Модели данных (Pydantic)
│   └── routers/         # API роутеры (FastAPI)
├── docker/
├── k8s-manifests/
├── requirements.txt
└── README.md
```

### Изменения в коде:

1. **Все импорты обновлены** (19 импортов в 11 файлах):
   - `from config.env import st` → `from app.config.env import st`
   - `from models.X import Y` → `from app.models.X import Y`
   - `from routers.X import Y` → `from app.routers.X import Y`

2. **Относительные пути к файлам обновлены** (2 файла):
   - `config/ports.json` → `app/config/ports.json`
   - Файлы: `mhe_ae.py`, `mhe_app.py`

3. **Dockerfile обновлен**:
   - Объединены 4 `COPY` команды в одну: `COPY app/ /opt/app/app/`

## 🚀 Запуск приложения

### Локальный запуск микросервисов:

**До миграции:**
```bash
python core/mhe_db.py
python core/mhe_app.py
```

**После миграции:**
```bash
python -m app.core.mhe_db
python -m app.core.mhe_app
python -m app.core.mhe_ae
python -m app.core.mhe_fortiapi
python -m app.core.mhe_email
python -m app.core.mhe_radius
python -m app.core.mhe_log
python -m app.core.mhe_ldap
```

### Docker:
```bash
# Build образ
docker build -f docker/Dockerfile -t shpak-k8s:latest .

# Запуск конкретного сервиса
docker run --rm -p 80:80 shpak-k8s:latest python -m app.core.mhe_db
docker run --rm -p 80:80 shpak-k8s:latest python -m app.core.mhe_app
docker run --rm -p 80:80 shpak-k8s:latest python -m app.core.mhe_ae

# Быстрый тест (PowerShell)
./docker/test_build.ps1

# Быстрый тест (Bash)
bash docker/test_build.sh
```

**Структура в контейнере:**
```
/opt/app/              ← WORKDIR
├── app/               ← Ваш код
│   ├── config/
│   ├── core/
│   ├── models/
│   └── routers/
└── requirements.txt
```

### Kubernetes:
Никаких изменений не требуется - манифесты используют Docker образ.

## ✅ Проверено:

- ✅ Структура папок создана
- ✅ Все файлы перемещены
- ✅ __init__.py файлы созданы (4 файла)
- ✅ Импорты обновлены в core/ (8 файлов)
- ✅ Импорты обновлены в routers/ (4 файла)
- ✅ Относительные пути исправлены (2 файла)
- ✅ Dockerfile обновлен
- ✅ Старые папки удалены

## 📝 Примечания:

1. **PYTHONPATH**: В Docker `/opt/app` является рабочей директорией, поэтому импорты `from app.` работают автоматически.

2. **Локальная разработка**: При запуске локально убедитесь, что находитесь в корневой директории проекта `shpak-k8s/`.

3. **Тесты**: Если есть тесты, их импорты тоже нужно обновить на `from app.X import Y`.

4. **Обратная совместимость**: Старые импорты (`from config.env`) больше не работают - все должны использовать новые (`from app.config.env`).

## 🔄 Если нужно откатить изменения:

Используйте git:
```bash
git checkout HEAD -- .
git clean -fd
```

---

**Дата миграции**: 2025-10-20  
**Версия Python**: 3.11+  
**FastAPI совместимость**: ✅ Полная

