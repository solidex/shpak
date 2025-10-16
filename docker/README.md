# shpak-k8s base image

Build a local Python image with the project copied inside and dependencies installed.

## Build

```bash
# from shpak-k8s/
docker build -t shpak-k8s:local .
```

## Run example (override CMD)

```bash
docker run --rm -it -p 8000:8000 \
  -e PYTHONPATH=/opt/app/shpak-k8s \
  shpak-k8s:local python -m shpak-k8s.core.fastapi_sql
```

Mount your config or code as needed with -v.
