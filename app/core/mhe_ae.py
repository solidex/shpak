import json
import logging
import asyncio
from fastapi import FastAPI, Request
from app.config.env import st
import httpx
from pathlib import Path
from logging.handlers import RotatingFileHandler
from contextlib import asynccontextmanager

logger = logging.getLogger("mhe_ae")
# Ensure file-based rotating logs (no console spam)
if not logger.handlers:
    Path("logs").mkdir(exist_ok=True)
    handler = RotatingFileHandler("logs/mhe_ae.log", maxBytes=10*1024*1024, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

# Async HTTP client for non-blocking I/O
async_client = httpx.AsyncClient(timeout=3.0)
logger.info("AE async HTTP client created (httpx)")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: client already initialized
    yield
    # Shutdown: cleanup
    logger.info("Shutting down: closing httpx client")
    await async_client.aclose()
    logger.info("AE httpx client closed")

app = FastAPI(lifespan=lifespan)

MHE_DB_URL = f"http://{st.MHE_DB_HOST}:{st.MHE_DB_PORT}"
FG_URL = f"http://{st.MHE_FORTIAPI_HOST}:{st.MHE_FORTIAPI_PORT}"

# Загружаем и кэшируем порты один раз
def _load_ports_matrix():
    with open('app/config/ports.json') as f:
        data = json.load(f)
    tcp = {tok.strip() for item in data for tok in str(item.get('tcp_rules', '')).split(',') if tok.strip()}
    udp = {tok.strip() for item in data for tok in str(item.get('udp_rules', '')).split(',') if tok.strip()}
    return sorted(tcp), sorted(udp)

ALL_TCP, ALL_UDP = _load_ports_matrix()

def _invert_rules(selected_tcp, selected_udp):
    """Вернуть строки правил, инвертированные относительно полной матрицы."""
    def select(rules, ref): return set([t.strip() for t in str(rules or '').split(',') if t.strip()])
    return (
        ','.join([p for p in ALL_TCP if p not in select(selected_tcp, ALL_TCP)]),
        ','.join([p for p in ALL_UDP if p not in select(selected_udp, ALL_UDP)]),
    )

async def _req(method, url, **kwargs):
    """Async HTTP request wrapper"""
    try:
        timeout = kwargs.pop("timeout", 3)
        resp = await async_client.request(method.upper(), url, timeout=timeout, **kwargs)
        if resp.is_success:
            return resp
        logger.error(f"{method.upper()} {url} failed: {resp.status_code}")
        return None
    except Exception as e:
        logger.error(f"{method.upper()} {url} failed: {e}")
        return None

async def _post(url, **kwargs):    return await _req('post', url, **kwargs)
async def _delete(url, **kwargs):  return await _req('delete', url, **kwargs)
async def _put(url, **kwargs):     return await _req('put', url, **kwargs)

def _get_common(data):
    return (
        data.get("hash"),
        data.get("user_name") or data.get("login"),
        data.get("Framed-IP-Address") or data.get("ip"),
        data.get("Delegated-IPv6-Prefix") or data.get("ipv6"),
        data.get("tcp_rules"),
        data.get("udp_rules"),
        st.FORTI_GATE.get(data.get("NAS-IP-Address", ""), [])
    )

async def handle_create(data):
    """Create firewall policy (failover: try first FG, if unavailable → second)"""
    hash_val, user, ip, ipv6, tcp, udp, fg_addr = _get_common(data)
    inv_tcp, inv_udp = _invert_rules(tcp, udp)

    # Получаем policy_id, если уже есть
    policy_id = None
    if hash_val:
        resp = await _post(f"{MHE_DB_URL}/query/policy_id/by_hash", json={"hash": hash_val})
        if resp:
            policy_id = resp.json().get("data", {}).get("policy_id")

    # Failover: try first FG, if fail → second, etc.
    for fg in fg_addr:
        logger.info(f"Attempting create on FG: {fg}")
        
        # Sequential requests to maintain order (important!)
        r1 = await _post(f"{FG_URL}/create_ip", json={"fg_addr": fg, "name": user, "ip": ip})
        if r1 is None:
            logger.warning(f"FG {fg} unavailable (create_ip failed), trying next...")
            continue
        await asyncio.sleep(0)  # Yield control for responsiveness
        
        r2 = await _post(f"{FG_URL}/create_ipv6", json={"fg_addr": fg, "name": user, "ipv6": ipv6})
        if r2 is None:
            logger.warning(f"FG {fg} unavailable (create_ipv6 failed), trying next...")
            continue
        await asyncio.sleep(0)

        if policy_id:
            r3 = await _post(f"{FG_URL}/edit_policy", json={"fg_addr": fg, "action": "add", "policy_id": policy_id, "extra": {"user": user, "ip": ip, "ipv6": ipv6}})
            if r3 is None:
                logger.warning(f"FG {fg} unavailable (edit_policy failed), trying next...")
                continue
        else:
            r3 = await _post(f"{FG_URL}/create_service", json={"fg_addr": fg, "name": hash_val, "tcp": inv_tcp, "udp": inv_udp})
            if r3 is None:
                logger.warning(f"FG {fg} unavailable (create_service failed), trying next...")
                continue
            await asyncio.sleep(0)
            
            resp = await _post(f"{FG_URL}/create_policy", json={"fg_addr": fg, "name": hash_val, "username": user})
            if resp is None:
                logger.warning(f"FG {fg} unavailable (create_policy failed), trying next...")
                continue
            new_policy_id = resp.json().get("mkey") if resp else None
            await asyncio.sleep(0)
            
            r4 = await _post(f"{FG_URL}/move_policy_to_top", json={"fg_addr": fg, "policy_id": new_policy_id})
            if new_policy_id:
                await _post(f"{MHE_DB_URL}/policy_logs", json={"user": user, "fg": fg, "response": {"mkey": new_policy_id, "action": "create"}})
                await _post(f"{MHE_DB_URL}/firewall_profiles/update_policy_id", json={"login": user, "hash": hash_val, "policy_id": new_policy_id})
        
        logger.info(f"Successfully created on FG: {fg}")
        return {"policy_id": policy_id, "inverted_tcp": inv_tcp, "inverted_udp": inv_udp, "fg_used": fg}
    
    logger.error(f"All FortiGates unavailable for user {user}")
    return {"error": "All FortiGates unavailable", "inverted_tcp": inv_tcp, "inverted_udp": inv_udp}

async def handle_edit(data):
    """Edit firewall policy (failover: try first FG, if unavailable → second)"""
    policy_id = data.get("policy_id")
    old_hash = data.get("old_hash")
    hash_val, user, ip, ipv6, tcp, udp, fg_addr = _get_common(data)
    inv_tcp, inv_udp = _invert_rules(tcp, udp)

    policy_id_exists, policy_id_by_hash = False, None
    if policy_id and hash_val:
        resp = await _put(f"{MHE_DB_URL}/query/policy_id/check", json={"policy_id": policy_id, "hash": hash_val})
        if resp:
            chk = resp.json().get("data", {})
            policy_id_exists = chk.get("policy_id_exists", False)
            policy_id_by_hash = chk.get("policy_id_by_hash")

    # Failover: try first FG, if fail → second, etc.
    for fg in fg_addr:
        logger.info(f"Attempting edit on FG: {fg}")
        success = False
        
        # Вся логика по сути один if-elif блок
        if not policy_id_exists and not policy_id_by_hash:
            r1 = await _post(f"{FG_URL}/edit_policy", json={"fg_addr": fg, "action": "rename", "old_hash": old_hash, "new_hash": hash_val, "extra": {"user": user}})
            if r1 is None:
                continue
            await asyncio.sleep(0)
            r2 = await _post(f"{FG_URL}/delete_service", json={"fg_addr": fg, "name": old_hash})
            if r2 is None:
                continue
            await asyncio.sleep(0)
            r3 = await _post(f"{FG_URL}/create_service", json={"fg_addr": fg, "name": hash_val, "tcp": inv_tcp, "udp": inv_udp})
            if r3 is not None:
                success = True
                result = {"renamed_policy_and_service": True, "fg_used": fg}
        elif not policy_id_exists and policy_id_by_hash:
            r1 = await _post(f"{FG_URL}/delete_policy", json={"fg_addr": fg, "policy_id": policy_id})
            if r1 is None:
                continue
            await asyncio.sleep(0)
            r2 = await _post(f"{FG_URL}/delete_service", json={"fg_addr": fg, "name": old_hash})
            if r2 is None:
                continue
            await asyncio.sleep(0)
            r3 = await _post(f"{FG_URL}/edit_policy", json={"fg_addr": fg, "action": "add", "policy_id": policy_id_by_hash, "extra": {"user": user, "ip": ip, "ipv6": ipv6}})
            if r3 is not None:
                success = True
                result = {"migrated_to_policy_by_hash": True, "new_policy_id": policy_id_by_hash, "fg_used": fg}
        elif policy_id_exists and not policy_id_by_hash:
            r1 = await _post(f"{FG_URL}/edit_policy", json={"fg_addr": fg, "action": "remove", "policy_id": policy_id, "extra": {"user": user}})
            if r1 is None:
                continue
            await asyncio.sleep(0)
            r2 = await _post(f"{FG_URL}/create_ip", json={"fg_addr": fg, "name": user, "ip": ip})
            if r2 is None:
                continue
            await asyncio.sleep(0)
            r3 = await _post(f"{FG_URL}/create_ipv6", json={"fg_addr": fg, "name": user, "ipv6": ipv6})
            if r3 is None:
                continue
            await asyncio.sleep(0)
            r4 = await _post(f"{FG_URL}/create_service", json={"fg_addr": fg, "name": hash_val, "tcp": inv_tcp, "udp": inv_udp})
            if r4 is None:
                continue
            await asyncio.sleep(0)
            resp = await _post(f"{FG_URL}/create_policy", json={"fg_addr": fg, "name": hash_val, "username": user})
            new_policy_id = resp.json().get("mkey") if resp else None
            if new_policy_id:
                await _post(f"{MHE_DB_URL}/firewall_profiles/update_policy_id", json={"login": user, "hash": hash_val, "policy_id": new_policy_id})
                success = True
                result = {"migrated_to_new_policy": True, "new_policy_id": new_policy_id, "fg_used": fg}
        else:  # оба True
            r1 = await _post(f"{FG_URL}/edit_policy", json={"fg_addr": fg, "action": "remove", "policy_id": policy_id, "extra": {"user": user}})
            if r1 is None:
                continue
            await asyncio.sleep(0)
            r2 = await _post(f"{FG_URL}/edit_policy", json={"fg_addr": fg, "action": "add", "policy_id": policy_id_by_hash, "extra": {"user": user, "ip": ip, "ipv6": ipv6}})
            if r2 is not None:
                success = True
                result = {"moved_to_policy_by_hash": True, "old_policy_id": policy_id, "new_policy_id": policy_id_by_hash, "fg_used": fg}
        
        if success:
            logger.info(f"Successfully edited on FG: {fg}")
            return result
        else:
            logger.warning(f"FG {fg} unavailable, trying next...")
    
    logger.error(f"All FortiGates unavailable for user {user}")
    return {"error": "All FortiGates unavailable"}

async def handle_delete(data):
    """Delete firewall policy (failover: try first FG, if unavailable → second)"""
    policy_id = data.get("policy_id")
    user = data.get("user_name") or data.get("login")
    hash_val = data.get("hash")
    fg_addr = st.FORTI_GATE.get(data.get("NAS-IP-Address", ""), [])
    ip = data.get("Framed-IP-Address") or data.get("ip")
    ipv6 = data.get("Delegated-IPv6-Prefix") or data.get("ipv6")

    found_policy = None
    if policy_id:
        resp = await _delete(f"{MHE_DB_URL}/query/policy_id/check", json={"policy_id": policy_id})
        if resp:
            found_policy = resp.json().get("data", {}).get("policy_id_exists")

    # Failover: try first FG, if fail → second, etc.
    for fg in fg_addr:
        logger.info(f"Attempting delete on FG: {fg}")
        
        if policy_id:
            r1 = await _post(f"{FG_URL}/edit_policy", json={"fg_addr": fg, "action": "remove", "policy_id": policy_id, "extra": {"user": user, "ip": ip, "ipv6": ipv6}})
            if r1 is None:
                logger.warning(f"FG {fg} unavailable, trying next...")
                continue
            await asyncio.sleep(0)
        
        if not found_policy:
            r2 = await _post(f"{FG_URL}/delete_policy", json={"fg_addr": fg, "policy_id": policy_id})
            if r2 is None:
                continue
            await asyncio.sleep(0)
            r3 = await _post(f"{FG_URL}/delete_service", json={"fg_addr": fg, "name": hash_val})
            if r3 is None:
                continue
            await asyncio.sleep(0)
            r4 = await _post(f"{FG_URL}/delete_ip", json={"fg_addr": fg, "name": user})
            if r4 is None:
                continue
            await asyncio.sleep(0)
            r5 = await _post(f"{FG_URL}/delete_ipv6", json={"fg_addr": fg, "name": user})
            if r5 is not None:
                logger.info(f"Successfully deleted on FG: {fg}")
                return {"deleted_policy": True, "fg_used": fg}
        else:
            r2 = await _post(f"{FG_URL}/edit_policy", json={"fg_addr": fg, "action": "remove", "policy_id": policy_id, "extra": {"user": user}})
            if r2 is None:
                continue
            await asyncio.sleep(0)
            r3 = await _post(f"{FG_URL}/delete_service", json={"fg_addr": fg, "name": hash_val})
            if r3 is None:
                continue
            await asyncio.sleep(0)
            r4 = await _post(f"{FG_URL}/delete_ip", json={"fg_addr": fg, "name": user})
            if r4 is None:
                continue
            await asyncio.sleep(0)
            r5 = await _post(f"{FG_URL}/delete_ipv6", json={"fg_addr": fg, "name": user})
            if r5 is not None:
                logger.info(f"Successfully deleted on FG: {fg}")
                return {"removed_user_from_policy": True, "policy_id": policy_id, "fg_used": fg}
        
        logger.warning(f"FG {fg} unavailable, trying next...")
    
    logger.error(f"All FortiGates unavailable for user {user}")
    return {"error": "All FortiGates unavailable"}

@app.post("/keepalive")
def receive_keepalive(payload: dict):
    try:
        login = payload.get("login")
        logger.info(f"Keepalive received for login={login}")
        return {"success": True}
    except Exception as e:
        logger.error(f"Keepalive error: {e}")
        return {"success": False, "error": str(e)}

@app.post("/signal")
async def receive_signal(request: Request):
    payload = await request.json()
    logger.info(f"Received signal: {payload}")
    action = payload.get("action")
    data = payload.get("data", {})
    if action in ["create", "edit", "delete"]:
        logger.info(f"Processing {action} signal for user: {data.get('user_name', data.get('login', 'unknown'))}")

    result = {"error": "Unsupported action"}
    if action == "create":
        result = await handle_create(data)
    elif action == "edit":
        result = await handle_edit(data)
    elif action == "delete":
        result = await handle_delete(data)
    else:
        logger.warning(f"Unknown action received: {action}")

    return {"success": True, "result": result}

@app.get("/health")
def health_check():
    return {"status": "ok", "service": "mhe_ae"}

if __name__ == "__main__":
    import uvicorn
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    uvicorn.run(app, host="0.0.0.0", port=80)
