import json
import logging
from fastapi import FastAPI, Request
from app.config.env import st
import requests
from pathlib import Path
from logging.handlers import RotatingFileHandler

logger = logging.getLogger("mhe_ae")
# Ensure file-based rotating logs (no console spam)
if not logger.handlers:
    Path("logs").mkdir(exist_ok=True)
    handler = RotatingFileHandler("logs/mhe_ae.log", maxBytes=10*1024*1024, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
app = FastAPI()

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

_SESSION = requests.Session()

def _req(method, url, **kwargs):
    try:
        timeout = kwargs.pop("timeout", 3)
        return _SESSION.request(method.upper(), url, timeout=timeout, **kwargs)
    except Exception as e:
        logger.error(f"{method.upper()} {url} failed: {e}")

def _post(url, **kwargs):    return _req('post', url, **kwargs)
def _delete(url, **kwargs):  return _req('delete', url, **kwargs)
def _put(url, **kwargs):     return _req('put', url, **kwargs)

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

def handle_create(data):
    hash_val, user, ip, ipv6, tcp, udp, fg_addr = _get_common(data)
    inv_tcp, inv_udp = _invert_rules(tcp, udp)

    # Получаем policy_id, если уже есть
    policy_id = None
    if hash_val:
        resp = _post(f"{MHE_DB_URL}/query/policy_id/by_hash", json={"hash": hash_val})
        if resp:
            policy_id = resp.json().get("data", {}).get("policy_id")

    for fg in fg_addr:
        _post(f"{FG_URL}/create_ip", json={"fg_addr": fg, "name": user, "ip": ip})
        _post(f"{FG_URL}/create_ipv6", json={"fg_addr": fg, "name": user, "ipv6": ipv6})

        if policy_id:
            _post(f"{FG_URL}/edit_policy", json={"fg_addr": fg, "action": "add", "policy_id": policy_id, "extra": {"user": user, "ip": ip, "ipv6": ipv6}})
        else:
            _post(f"{FG_URL}/create_service", json={"fg_addr": fg, "name": hash_val, "tcp": inv_tcp, "udp": inv_udp})
            resp = _post(f"{FG_URL}/create_policy", json={"fg_addr": fg, "name": hash_val, "username": user})
            new_policy_id = resp.json().get("mkey") if resp else None
            _post(f"{FG_URL}/move_policy_to_top", json={"fg_addr": fg, "policy_id": new_policy_id})
            if new_policy_id:
                _post(f"{MHE_DB_URL}/policy_logs", json={"user": user, "fg": fg, "response": {"mkey": new_policy_id, "action": "create"}})
                _post(f"{MHE_DB_URL}/firewall_profiles/update_policy_id", json={"login": user, "hash": hash_val, "policy_id": new_policy_id})

    return {"policy_id": policy_id, "inverted_tcp": inv_tcp, "inverted_udp": inv_udp}

def handle_edit(data):
    policy_id = data.get("policy_id")
    old_hash = data.get("old_hash")
    hash_val, user, ip, ipv6, tcp, udp, fg_addr = _get_common(data)
    inv_tcp, inv_udp = _invert_rules(tcp, udp)

    policy_id_exists, policy_id_by_hash = False, None
    if policy_id and hash_val:
        resp = _put(f"{MHE_DB_URL}/query/policy_id/check", json={"policy_id": policy_id, "hash": hash_val})
        if resp:
            chk = resp.json().get("data", {})
            policy_id_exists = chk.get("policy_id_exists", False)
            policy_id_by_hash = chk.get("policy_id_by_hash")

    for fg in fg_addr:
        # Вся логика по сути один if-elif блок
        if not policy_id_exists and not policy_id_by_hash:
            _post(f"{FG_URL}/edit_policy", json={"fg_addr": fg, "action": "rename", "old_hash": old_hash, "new_hash": hash_val, "extra": {"user": user}})
            _post(f"{FG_URL}/delete_service", json={"fg_addr": fg, "name": old_hash})
            _post(f"{FG_URL}/create_service", json={"fg_addr": fg, "name": hash_val, "tcp": inv_tcp, "udp": inv_udp})
            return {"renamed_policy_and_service": True}
        elif not policy_id_exists and policy_id_by_hash:
            _post(f"{FG_URL}/delete_policy", json={"fg_addr": fg, "policy_id": policy_id})
            _post(f"{FG_URL}/delete_service", json={"fg_addr": fg, "name": old_hash})
            _post(f"{FG_URL}/edit_policy", json={"fg_addr": fg, "action": "add", "policy_id": policy_id_by_hash, "extra": {"user": user, "ip": ip, "ipv6": ipv6}})
            return {"migrated_to_policy_by_hash": True, "new_policy_id": policy_id_by_hash}
        elif policy_id_exists and not policy_id_by_hash:
            _post(f"{FG_URL}/edit_policy", json={"fg_addr": fg, "action": "remove", "policy_id": policy_id, "extra": {"user": user}})
            _post(f"{FG_URL}/create_ip", json={"fg_addr": fg, "name": user, "ip": ip})
            _post(f"{FG_URL}/create_ipv6", json={"fg_addr": fg, "name": user, "ipv6": ipv6})
            _post(f"{FG_URL}/create_service", json={"fg_addr": fg, "name": hash_val, "tcp": inv_tcp, "udp": inv_udp})
            resp = _post(f"{FG_URL}/create_policy", json={"fg_addr": fg, "name": hash_val, "username": user})
            new_policy_id = resp.json().get("mkey") if resp else None
            if new_policy_id:
                _post(f"{MHE_DB_URL}/firewall_profiles/update_policy_id", json={"login": user, "hash": hash_val, "policy_id": new_policy_id})
            return {"migrated_to_new_policy": True, "new_policy_id": new_policy_id}
        else:  # оба True
            _post(f"{FG_URL}/edit_policy", json={"fg_addr": fg, "action": "remove", "policy_id": policy_id, "extra": {"user": user}})
            _post(f"{FG_URL}/edit_policy", json={"fg_addr": fg, "action": "add", "policy_id": policy_id_by_hash, "extra": {"user": user, "ip": ip, "ipv6": ipv6}})
            return {"moved_to_policy_by_hash": True, "old_policy_id": policy_id, "new_policy_id": policy_id_by_hash}

def handle_delete(data):
    policy_id = data.get("policy_id")
    user = data.get("user_name") or data.get("login")
    hash_val = data.get("hash")
    fg_addr = st.FORTI_GATE.get(data.get("NAS-IP-Address", ""), [])
    ip = data.get("Framed-IP-Address") or data.get("ip")
    ipv6 = data.get("Delegated-IPv6-Prefix") or data.get("ipv6")

    found_policy = None
    if policy_id:
        resp = _delete(f"{MHE_DB_URL}/query/policy_id/check", json={"policy_id": policy_id})
        if resp:
            found_policy = resp.json().get("data", {}).get("policy_id_exists")

    for fg in fg_addr:
        if policy_id:
            _post(f"{FG_URL}/edit_policy", json={"fg_addr": fg, "action": "remove", "policy_id": policy_id, "extra": {"user": user, "ip": ip, "ipv6": ipv6}})
        if not found_policy:
            _post(f"{FG_URL}/delete_policy", json={"fg_addr": fg, "policy_id": policy_id})
            _post(f"{FG_URL}/delete_service", json={"fg_addr": fg, "name": hash_val})
            _post(f"{FG_URL}/delete_ip", json={"fg_addr": fg, "name": user})
            _post(f"{FG_URL}/delete_ipv6", json={"fg_addr": fg, "name": user})
            return {"deleted_policy": True}
        else:
            _post(f"{FG_URL}/edit_policy", json={"fg_addr": fg, "action": "remove", "policy_id": policy_id, "extra": {"user": user}})
            _post(f"{FG_URL}/delete_service", json={"fg_addr": fg, "name": hash_val})
            _post(f"{FG_URL}/delete_ip", json={"fg_addr": fg, "name": user})
            _post(f"{FG_URL}/delete_ipv6", json={"fg_addr": fg, "name": user})
            return {"removed_user_from_policy": True, "policy_id": policy_id}

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
        result = handle_create(data)
    elif action == "edit":
        result = handle_edit(data)
    elif action == "delete":
        result = handle_delete(data)
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
