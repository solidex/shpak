from fastapi import FastAPI
from routers.routes_firewall import router as firewall_router
from routers.routes_radius import router as radius_router
from routers.routes_query import router as query_router
from routers.routes_policy_log import router as policy_log_router
import logging
from config.env import st

app = FastAPI()

# Include routers without /internal prefix for direct MHE_DB access
app.include_router(firewall_router, prefix="/firewall")
app.include_router(radius_router, prefix="/radius")
app.include_router(query_router, prefix="/query")
app.include_router(policy_log_router, prefix="/policy_logs")

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mhe_db")

if __name__ == "__main__":
    import uvicorn
    logging.basicConfig(filename='mhe_db.log', level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    uvicorn.run(app, host="0.0.0.0", port=80)
