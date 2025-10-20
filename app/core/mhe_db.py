import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from fastapi import FastAPI
from app.routers.routes_firewall import router as firewall_router
from app.routers.routes_radius import router as radius_router
from app.routers.routes_query import router as query_router
from app.routers.routes_policy_log import router as policy_log_router

log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)
handler = RotatingFileHandler(log_dir / "mhe_db.log", maxBytes=10*1024*1024, backupCount=5, encoding="utf-8")
handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
logging.basicConfig(level=logging.INFO, handlers=[handler])
logging.getLogger("uvicorn.access").handlers = []

app = FastAPI()
app.include_router(firewall_router, prefix="/firewall")
app.include_router(radius_router, prefix="/radius")
app.include_router(query_router, prefix="/query")
app.include_router(policy_log_router, prefix="/policy_logs")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=80, log_config=None)
