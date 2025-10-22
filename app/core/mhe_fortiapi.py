import logging
import json
import httpx
from pathlib import Path
from logging.handlers import RotatingFileHandler
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.config.env import st
from app.models.fortigate_models import (
    CreateIPRequest, CreateIPv6Request, CreateServiceRequest, CreatePolicyRequest,
    DeleteObjectRequest, DeletePolicyRequest, MovePolicyRequest, GetPolicyRequest, EditPolicyRequest
)

logger = logging.getLogger("mhe_fortiapi")
if not logger.handlers:
    Path("logs").mkdir(exist_ok=True)
    handler = RotatingFileHandler("logs/mhe_fortiapi.log", maxBytes=10*1024*1024, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

API_TOKEN = st.API_TOKEN

# Async HTTP client for non-blocking I/O
async_client = httpx.AsyncClient(verify=False, timeout=3.0)
logger.info("FortiAPI async HTTP client created (httpx)")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: client already initialized
    yield
    # Shutdown: cleanup
    logger.info("Shutting down: closing httpx client")
    await async_client.aclose()
    logger.info("FortiAPI httpx client closed")

app = FastAPI(lifespan=lifespan)

def _headers():
    return {
        'Authorization': f'Bearer {API_TOKEN}',
        'Content-Type': 'application/json'
    }

async def _req(method, url, data=None):
    """Async HTTP request to FortiGate API"""
    try:
        payload = json.dumps(data) if data is not None and not isinstance(data, str) else data
        resp = await async_client.request(
            method.upper(), 
            url, 
            headers=_headers(), 
            content=payload.encode() if payload else None
        )
        if resp.is_success:
            try:
                return resp.json()
            except Exception:
                return resp.text
        logger.error(f"[FG] {method} {url} failed: {resp.status_code} {resp.text}")
        return None
    except Exception as e:
        logger.error(f"[FG] {method} {url} exception: {e}")
        return None

@app.post("/create_ip")
async def create_ip(req: CreateIPRequest):
    url = f"https://{req.fg_addr}/api/v2/cmdb/firewall/address"
    payload = {"name": req.name, "subnet": f"{req.ip} 255.255.255.255"}
    logger.info(f"[FG] Create IP {req.ip} for {req.name} on {req.fg_addr}")
    return await _req("POST", url, payload)

@app.post("/create_ipv6")
async def create_ipv6(req: CreateIPv6Request):
    url = f"https://{req.fg_addr}/api/v2/cmdb/firewall/address6"
    payload = {"name": f"{req.name}v6", "ip6": req.ipv6}
    logger.info(f"[FG] Create IPv6 {req.ipv6} for {req.name} on {req.fg_addr}")
    return await _req("POST", url, payload)

@app.post("/create_service")
async def create_service(req: CreateServiceRequest):
    url = f"https://{req.fg_addr}/api/v2/cmdb/firewall.service/custom"
    payload = {"name": req.name, "tcp-portrange": req.tcp, "udp-portrange": req.udp}
    logger.info(f"[FG] Create service {req.name} (tcp={req.tcp}, udp={req.udp}) on {req.fg_addr}")
    return await _req("POST", url, payload)

@app.post("/create_policy")
async def create_policy(req: CreatePolicyRequest):
    url = f"https://{req.fg_addr}/api/v2/cmdb/firewall/policy?datasource=true&with_meta=true&vdom=transparent"
    payload = {
        "name": req.name,
        "action": "deny",
        "srcintf": [{"name": "PPPoE_vlan"}],
        "dstintf": [{"name": "Core_vlan"}],
        "srcaddr": [{"name": req.username}],
        "dstaddr": [{"name": "ns4.belpak.by_ipv4"}, {"name": "ns3.belpak.by_ipv4"}],
        "srcaddr6": [{"name": f"{req.username}v6"}],
        "dstaddr6": [{"name": "ns3.belpak.by_ipv6"}, {"name": "ns4.belpak.by_ipv6"}],
        "schedule": "always",
        "service": [{"name": req.name}],
        "ssl-ssh-profile": "",
        "logtraffic": "disable",
        "groups": [{"name": "class2"}],
        "dstaddr-negate": "enable",
        "dstaddr6-negate": "enable"
    }
    logger.info(f"[FG] Create policy {req.name} for user {req.username} on {req.fg_addr}")
    resp = await _req("POST", url, payload)
    return {"mkey": resp.get("mkey") if isinstance(resp, dict) else None}

@app.delete("/delete_ip")
async def delete_ip(req: DeleteObjectRequest):
    url = f"https://{req.fg_addr}/api/v2/cmdb/firewall/address/{req.name}"
    logger.info(f"[FG] Delete IP {req.name} on {req.fg_addr}")
    return await _req("DELETE", url)

@app.delete("/delete_ipv6")
async def delete_ipv6(req: DeleteObjectRequest):
    url = f"https://{req.fg_addr}/api/v2/cmdb/firewall/address6/{req.name}v6"
    logger.info(f"[FG] Delete IPv6 {req.name}v6 on {req.fg_addr}")
    return await _req("DELETE", url)

@app.delete("/delete_service")
async def delete_service(req: DeleteObjectRequest):
    url = f"https://{req.fg_addr}/api/v2/cmdb/firewall.service/custom/{req.name}"
    logger.info(f"[FG] Delete service {req.name} on {req.fg_addr}")
    return await _req("DELETE", url)

@app.delete("/delete_policy")
async def delete_policy(req: DeletePolicyRequest):
    url = f"https://{req.fg_addr}/api/v2/cmdb/firewall/policy/{req.policy_id}"
    logger.info(f"[FG] Delete policy {req.policy_id} on {req.fg_addr}")
    return await _req("DELETE", url)

@app.post("/move_policy_to_top")
async def move_policy_to_top(req: MovePolicyRequest):
    url = f"https://{req.fg_addr}/api/v2/cmdb/firewall/policy/{req.policy_id}?action=move&before=1"
    logger.info(f"[FG] Move policy {req.policy_id} to top on {req.fg_addr}")
    return await _req("PUT", url)

@app.post("/get_policy")
async def get_policy(req: GetPolicyRequest):
    url = f"https://{req.fg_addr}/api/v2/cmdb/firewall/policy/{req.policy_id}"
    logger.info(f"[FG] Get policy {req.policy_id} from {req.fg_addr}")
    return await _req("GET", url)

@app.post("/edit_policy")
async def edit_policy(req: EditPolicyRequest):
    policy = await get_policy(GetPolicyRequest(fg_addr=req.fg_addr, policy_id=req.policy_id))
    if not policy or not isinstance(policy, dict):
        logger.error(f"[FG] Policy {req.policy_id} not found on {req.fg_addr}")
        return {"mkey": None}
    logger.info(f"[FG] Edit policy {req.policy_id} action={req.action} on {req.fg_addr} with payload: {req.extra}")
    if req.action in ("add", "rename"):
        resp = await _req("POST", f"https://{req.fg_addr}/api/v2/cmdb/firewall/policy", policy)
        return {"mkey": resp.get("mkey") if isinstance(resp, dict) else None}
    elif req.action == "remove":
        await _req("PUT", f"https://{req.fg_addr}/api/v2/cmdb/firewall/policy/{req.policy_id}", policy)
    return {"mkey": None}

@app.get("/health")
def health_check():
    return {"status": "ok", "service": "mhe_fortiapi"}

if __name__ == "__main__":
    import uvicorn
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    uvicorn.run(app, host="0.0.0.0", port=80)

