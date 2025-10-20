# shpak-k8s Docker Image

Base Python image with the project structure and all dependencies installed.

## Build

```bash
# From project root (shpak-k8s/)
docker build -f docker/Dockerfile -t shpak-k8s:latest .
```

## Run Examples

### MHE DB Service (Main API)
```bash
docker run --rm -it -p 80:80 \
  shpak-k8s:latest python -m app.core.mhe_db
```

### MHE APP Service
```bash
docker run --rm -it -p 80:80 \
  shpak-k8s:latest python -m app.core.mhe_app
```

### MHE AE Service (Action Engine)
```bash
docker run --rm -it -p 80:80 \
  shpak-k8s:latest python -m app.core.mhe_ae
```

### FortiAPI Service
```bash
docker run --rm -it -p 80:80 \
  shpak-k8s:latest python -m app.core.mhe_fortiapi
```

### With Environment Variables
```bash
docker run --rm -it -p 80:80 \
  -e MHE_DB_HOST=localhost \
  -e MHE_DB_PORT=3306 \
  shpak-k8s:latest python -m app.core.mhe_db
```

## Structure in Container

```
/opt/app/
├── app/
│   ├── config/   (env.py, ports.json)
│   ├── core/     (microservices)
│   ├── models/   (Pydantic models)
│   └── routers/  (FastAPI routers)
└── requirements.txt
```

Mount your config or environment files as needed with `-v`.
