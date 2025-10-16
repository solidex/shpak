import json
import logging
from fastapi import FastAPI, Request
from config.env import st
import requests


logger = logging.getLogger("mhe_ae")
app = FastAPI()


MHE_DB_URL = f"http://{st.MHE_DB_HOST}:{st.MHE_DB_PORT}"
FG_URL = f"http://{st.MHE_FORTIAPI_HOST}:{st.MHE_FORTIAPI_PORT}"


def _load_ports_matrix():
    with open('config/ports.json') as f:
        data = json.load(f)
    # Универсальный набор всех tcp/udp значений из матрицы
    all_tcp, all_udp = set(), set()
    for item in data:
        for tok in str(item.get('tcp_rules', '')).split(','):
            tok = tok.strip()
            if tok: all_tcp.add(tok)
        for tok in str(item.get('udp_rules', '')).split(','):
            tok = tok.strip()
            if tok: all_udp.add(tok)
    return sorted(all_tcp), sorted(all_udp)


ALL_TCP, ALL_UDP = _load_ports_matrix()


def _invert_rules(selected_tcp: str, selected_udp: str):
    """Вернуть строки правил, инвертированные относительно полной матрицы.
    selected_* форматы: "80,443" или "1024-65535" или смешанные через запятую.
    Возвращаем строки tcp_rules/udp_rules, которые нужно ЗАПРЕТИТЬ."""
    def to_set(rules_str: str, full_list: list[str]) -> set[str]:
        # Мы работаем на уровне токенов (включая диапазоны как токены), чтобы не терять диапазоны
        tokens = [t.strip() for t in str(rules_str or '').split(',') if t.strip()]
        return set(tokens)

    selected_tcp_set = to_set(selected_tcp, ALL_TCP)
    selected_udp_set = to_set(selected_udp, ALL_UDP)

    # Инвертирование: все минус выбранные
    inverted_tcp = [t for t in ALL_TCP if t not in selected_tcp_set]
    inverted_udp = [u for u in ALL_UDP if u not in selected_udp_set]

    return ','.join(inverted_tcp), ','.join(inverted_udp)


def _post(url, **kwargs):
    try:
        return requests.post(url, timeout=5, **kwargs)
    except Exception as e:
        logger.error(f"POST {url} failed: {e}")


def _delete(url, **kwargs):
    try:
        return requests.delete(url, timeout=5, **kwargs)
    except Exception as e:
        logger.error(f"DELETE {url} failed: {e}")


def _put(url, **kwargs):
    try:
        return requests.put(url, timeout=5, **kwargs)
    except Exception as e:
        logger.error(f"PUT {url} failed: {e}")


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
    # Получаем ИНВЕРТИРОВАННЫЕ правила
    inv_tcp, inv_udp = _invert_rules(tcp, udp)

    # Узнаём policy_id, если уже есть
    policy_id = None
    if hash_val:
        resp = _post(f"{MHE_DB_URL}/query/policy_id/by_hash", json={"hash": hash_val})
        if resp is not None:
            try:
                policy_id = resp.json().get("data", {}).get("policy_id")
            except Exception:
                policy_id = None

    for fg in fg_addr:
        _post(f"{FG_URL}/create_ip", json={"fg_addr": fg, "name": user, "ip": ip})
        _post(f"{FG_URL}/create_ipv6", json={"fg_addr": fg, "name": user, "ipv6": ipv6})

        if policy_id:
            # Добавляем пользователя в уже существующую политику (запрещающие правила инвертированы)
            _post(f"{FG_URL}/edit_policy", json={"fg_addr": fg, "action": "add", "policy_id": policy_id, "extra": {"user": user, "ip": ip, "ipv6": ipv6}})
        else:
            # Создаём сервис с ИНВЕРТИРОВАННЫМИ правилами (запретные порты)
            _post(f"{FG_URL}/create_service", json={"fg_addr": fg, "name": hash_val, "tcp": inv_tcp, "udp": inv_udp})
            resp = _post(
                f"{FG_URL}/create_policy",
                json={"fg_addr": fg, "name": hash_val, "username": user}
            )
            new_policy_id = None
            try:
                if resp is not None:
                    new_policy_id = resp.json().get("mkey")
            except Exception:
                new_policy_id = None
            _post(f"{FG_URL}/move_policy_to_top", json={"fg_addr": fg, "policy_id": new_policy_id})
            if new_policy_id:
                # Сохраняем policy_id в БД
                _post(f"{MHE_DB_URL}/policy_logs", json={"user": user, "fg": fg, "response": {"mkey": new_policy_id, "action": "create"}})
                _post(f"{MHE_DB_URL}/firewall_profiles/update_policy_id", json={"login": user, "hash": hash_val, "policy_id": new_policy_id})

    return {"policy_id": policy_id, "inverted_tcp": inv_tcp, "inverted_udp": inv_udp}


def handle_edit(data):
    policy_id = data.get("policy_id")
    old_hash = data.get("old_hash")
    hash_val, user, ip, ipv6, tcp, udp, fg_addr = _get_common(data)

    inv_tcp, inv_udp = _invert_rules(tcp, udp)

    policy_id_exists = False
    policy_id_by_hash = None
    if policy_id and hash_val:
        resp = _put(f"{MHE_DB_URL}/query/policy_id/check", json={"policy_id": policy_id, "hash": hash_val})
        if resp is not None:
            try:
                check = resp.json().get("data", {})
                policy_id_exists = check.get("policy_id_exists", False)
                policy_id_by_hash = check.get("policy_id_by_hash")
            except Exception:
                pass

    for fg in fg_addr:
        if not policy_id_exists and not policy_id_by_hash:
            # Переименование: удаляем старый сервис, создаём новый с ИНВЕРТИРОВАННЫМИ правилами
            _post(f"{FG_URL}/edit_policy", json={"fg_addr": fg, "action": "rename", "old_hash": old_hash, "new_hash": hash_val, "extra": {"user": user}})
            _post(f"{FG_URL}/delete_service", json={"fg_addr": fg, "name": old_hash})
            _post(f"{FG_URL}/create_service", json={"fg_addr": fg, "name": hash_val, "tcp": inv_tcp, "udp": inv_udp})
            return {"renamed_policy_and_service": True}

        elif not policy_id_exists and policy_id_by_hash:
            # Миграция к уже существующей политике по hash
            _post(f"{FG_URL}/delete_policy", json={"fg_addr": fg, "policy_id": policy_id})
            _post(f"{FG_URL}/delete_service", json={"fg_addr": fg, "name": old_hash})
            _post(f"{FG_URL}/edit_policy", json={"fg_addr": fg, "action": "add", "policy_id": policy_id_by_hash, "extra": {"user": user, "ip": ip, "ipv6": ipv6}})
            return {"migrated_to_policy_by_hash": True, "new_policy_id": policy_id_by_hash}

        elif policy_id_exists and not policy_id_by_hash:
            # Удаляем из старой policy, создаём IP/IPv6 объекты, сервис с ИНВЕРТИРОВАННЫМИ правилами и новую policy
            _post(f"{FG_URL}/edit_policy", json={"fg_addr": fg, "action": "remove", "policy_id": policy_id, "extra": {"user": user}})
            # Сначала создаем IP и IPv6 объекты
            _post(f"{FG_URL}/create_ip", json={"fg_addr": fg, "name": user, "ip": ip})
            _post(f"{FG_URL}/create_ipv6", json={"fg_addr": fg, "name": user, "ipv6": ipv6})
            # Затем создаём сервис
            _post(f"{FG_URL}/create_service", json={"fg_addr": fg, "name": hash_val, "tcp": inv_tcp, "udp": inv_udp})
            # И наконец создаем policy, которая ссылается на эти объекты
            new_policy_resp = _post(f"{FG_URL}/create_policy", json={"fg_addr": fg, "name": hash_val, "username": user})
            new_policy_id = None
            try:
                if new_policy_resp is not None:
                    new_policy_id = new_policy_resp.json().get("mkey")
            except Exception:
                pass
            if new_policy_id:
                _post(f"{MHE_DB_URL}/firewall_profiles/update_policy_id", json={"login": user, "hash": hash_val, "policy_id": new_policy_id})
                _post(f"{MHE_DB_URL}/policy_logs", json={"user": user, "fg": fg, "response": {"mkey": new_policy_id, "action": "add"}})
            return {"migrated_to_new_policy": True, "new_policy_id": new_policy_id}

        else:  # policy_id_exists and policy_id_by_hash
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
        if resp is not None:
            try:
                found_policy = resp.json().get("data", {}).get("policy_id_exists")
            except Exception:
                pass

    for fg in fg_addr:
        if policy_id:
            _post(f"{FG_URL}/edit_policy", json={"fg_addr": fg, "action": "remove", "policy_id": policy_id, "extra": {"user": user, "ip": ip, "ipv6": ipv6}})
        if not found_policy:
            _post(f"{FG_URL}/delete_policy", json={"fg_addr": fg, "policy_id": policy_id})
            _post(f"{FG_URL}/delete_service", json={"fg_addr": fg, "name": hash_val})
            _post(f"{FG_URL}/delete_ip", json={"fg_addr": fg, "name": user})
            _post(f"{FG_URL}/delete_ipv6", json={"fg_addr": fg, "name": user})
            _post(f"{MHE_DB_URL}/policy_logs", json={"user": user, "fg": fg, "response": {"mkey": policy_id, "action": "delete"}})
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
    
    # Логируем получение сигнала
    if action in ["create", "edit", "delete"]:
        logger.info(f"Processing {action} signal for user: {data.get('user_name', data.get('login', 'unknown'))}")

    if action == "create":
        result = handle_create(data)
    elif action == "edit":
        result = handle_edit(data)
    elif action == "delete":
        result = handle_delete(data)
    else:
        result = {"error": "Unsupported action"}
        logger.warning(f"Unknown action received: {action}")

    return {"success": True, "result": result}


@app.get("/health")
def health_check():
    return {"status": "ok", "service": "mhe_ae"}


if __name__ == "__main__":
    import uvicorn
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    uvicorn.run(app, host="0.0.0.0", port=80)


