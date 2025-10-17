from fastapi import APIRouter, Query, Body
from typing import Optional
from models.models import FirewallProfileIn, ListResponse, ItemResponse, SimpleResponse
import mysql.connector, requests, hashlib, time, logging
from config.env import st
from contextlib import contextmanager

logger = logging.getLogger(__name__)
router = APIRouter()

@contextmanager
def db():
    cnx = mysql.connector.connect(**st.mysql_config)
    cursor = cnx.cursor()
    try:
        yield cnx, cursor
    finally:
        cursor.close()
        cnx.close()

def resp(success=True, data=None, error=None, comment=None, **kwargs):
    r = {"success": success}
    if data is not None: r["data"] = data
    if error: r["error"] = error
    if comment: r["comment"] = comment
    r.update(kwargs)
    return r

# URLs for inner service calls
MHE_AE_URL = f"http://{st.MHE_AE_HOST}:{st.MHE_AE_PORT}/signal"
MHE_APP_URL = f"http://{st.MHE_APP_HOST}:{st.MHE_APP_PORT}/keepalive"

def send_signal(action, data):
    try:
        requests.post(MHE_AE_URL, json={"action": action, "data": data}, timeout=2)
    except Exception as e:
        logger.warning(f"Failed to send signal to MHE_AE: {e}")

def get_columns(cursor):
    return [col[0] for col in cursor.description] if cursor.description else []

def check_radius_with_keepalive(login: str, max_attempts: int = 3, delay: float = 0.5):
    """
    Проверка сообщения в RADIUS, с periodic keepalive и паузой.
    """
    for attempt in range(max_attempts):
        with db() as (cnx, cursor):
            cursor.execute("SELECT * FROM A WHERE User_Name = %s", (login,))
            row = cursor.fetchone()
            if row:
                columns = get_columns(cursor)
                return True, dict(zip(columns, row))
        if attempt < max_attempts - 1:
            try:
                requests.post(MHE_APP_URL, json={"login": login}, timeout=1)
            except Exception:
                pass
            time.sleep(delay)
    return False, None

@router.get("/firewall_profiles", response_model=ListResponse)
def list_firewall_profiles(page: int = 1, page_size: int = 25, login: Optional[str] = None):
    try:
        with db() as (cnx, cursor):
            offset = (page - 1) * page_size
            args = [login, page_size, offset] if login else [page_size, offset]
            if login:
                cursor.execute(
                    "SELECT * FROM firewall_profiles WHERE login = %s LIMIT %s OFFSET %s",
                    args
                )
            else:
                cursor.execute(
                    "SELECT * FROM firewall_profiles LIMIT %s OFFSET %s",
                    args
                )
            columns = get_columns(cursor)
            rows = cursor.fetchall()
            data = [dict(zip(columns, row)) for row in rows] if columns and rows else []
            if login:
                cursor.execute("SELECT COUNT(*) FROM firewall_profiles WHERE login = %s", (login,))
            else:
                cursor.execute("SELECT COUNT(*) FROM firewall_profiles")
            total = cursor.fetchone()[0]
        return resp(data=data, total=total, page=page, page_size=page_size)
    except Exception as e:
        logger.error(f"Failed to list firewall profiles: {e}")
        return resp(False, error=str(e), data=[], total=0, page=page, page_size=page_size)

@router.get("/firewall_profiles/{id}", response_model=ItemResponse)
def get_firewall_profile(id: int):
    try:
        with db() as (cnx, cursor):
            cursor.execute("SELECT * FROM firewall_profiles WHERE id = %s", (id,))
            row = cursor.fetchone()
            if not row:
                return resp(False, error="Not found")
            columns = get_columns(cursor)
        return resp(data=dict(zip(columns, row)))
    except Exception as e:
        logger.error(f"Failed to get firewall profile {id}: {e}")
        return resp(False, error=str(e))

@router.post("/firewall_profiles", response_model=ItemResponse)
def create_firewall_profile(profile: FirewallProfileIn = Body(...)):
    try:
        found, radius_data = check_radius_with_keepalive(profile.login)
        if not found:
            return resp(False, error="RADIUS Accounting-Start не найден после 3 попыток", comment="Ожидание RADIUS Accounting-Start...")
        hash_val = hashlib.md5(f"{profile.tcp_rules}|{profile.udp_rules}".encode()).hexdigest()
        with db() as (cnx, cursor):
            cursor.execute(
                "INSERT INTO firewall_profiles (profile_type, can_delete, profile_name, created_at, updated_at, name, login, ip_pool, ip_v6_pool, region_id, tcp_rules, udp_rules, firewall_profile, hash) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (profile.profile_type, profile.can_delete, profile.profile_name, profile.created_at, profile.updated_at, profile.name, profile.login, profile.ip_pool, profile.ip_v6_pool, profile.region_id, profile.tcp_rules, profile.udp_rules, profile.firewall_profile, hash_val)
            )
            cnx.commit()
            new_id = cursor.lastrowid
            joined = radius_data.copy()
            joined.update({'tcp_rules': profile.tcp_rules, 'udp_rules': profile.udp_rules, 'hash': hash_val})
            send_signal("create", joined)
        logger.info(f"Firewall profile created: id={new_id}, login={profile.login}, hash={hash_val}")
        return resp(data={"id": new_id})
    except Exception as e:
        logger.error(f"Failed to create firewall profile: {e}")
        return resp(False, error=str(e))

@router.put("/firewall_profiles/{id}", response_model=ItemResponse)
def update_firewall_profile(id: int, profile: FirewallProfileIn = Body(...)):
    try:
        found, radius_data = check_radius_with_keepalive(profile.login)
        if not found:
            return resp(False, error="RADIUS Accounting-Start не найден после 3 попыток", comment="Ожидание RADIUS Accounting-Start...")

        with db() as (cnx, cursor):
            cursor.execute("SELECT hash FROM firewall_profiles WHERE id = %s", (id,))
            old_hash_row = cursor.fetchone()
            old_hash = old_hash_row[0] if old_hash_row else None

            hash_val = hashlib.md5(f"{profile.tcp_rules}|{profile.udp_rules}".encode()).hexdigest()
            cursor.execute(
                """INSERT INTO firewall_profiles (id, profile_type, can_delete, profile_name, created_at, updated_at, name, login, ip_pool, ip_v6_pool, region_id, tcp_rules, udp_rules, firewall_profile, hash) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (id, profile.profile_type, profile.can_delete, profile.profile_name, profile.created_at, profile.updated_at, profile.name, profile.login, profile.ip_pool, profile.ip_v6_pool, profile.region_id, profile.tcp_rules, profile.udp_rules, profile.firewall_profile, hash_val)
            )
            cnx.commit()
            joined = radius_data.copy()
            joined.update({'tcp_rules': profile.tcp_rules, 'udp_rules': profile.udp_rules, 'hash': hash_val, 'old_hash': old_hash})
            send_signal("edit", joined)
        logger.info(f"Firewall profile updated: id={id}, login={profile.login}, hash={hash_val}")
        return resp(data={"id": id})
    except Exception as e:
        logger.error(f"Failed to update firewall profile {id}: {e}")
        return resp(False, error=str(e))

@router.delete("/firewall_profiles/{id}", response_model=SimpleResponse)
def delete_firewall_profile(id: int):
    try:
        with db() as (cnx, cursor):
            cursor.execute("SELECT login, tcp_rules, udp_rules, policy_id, hash FROM firewall_profiles WHERE id = %s", (id,))
            row = cursor.fetchone()
            if not row or not row[0]:
                return resp(False, error="Профиль не найден")
            login, tcp_rules, udp_rules, policy_id, hash_val = row

        found, radius_data = check_radius_with_keepalive(login)
        if not found:
            return resp(False, error="RADIUS Accounting-Start не найден после 3 попыток", comment="Ожидание RADIUS Accounting-Start...")

        with db() as (cnx, cursor):
            cursor.execute("DELETE FROM firewall_profiles WHERE id = %s", (id,))
            cnx.commit()
            joined = radius_data.copy()
            joined.update({'tcp_rules': tcp_rules, 'udp_rules': udp_rules, 'policy_id': policy_id, 'hash': hash_val})
            send_signal("delete", joined)
        logger.info(f"Firewall profile deleted: id={id}, login={login}, hash={hash_val}")
        return resp()
    except Exception as e:
        logger.error(f"Failed to delete firewall profile {id}: {e}")
        return resp(False, error=str(e))

@router.get("/radius_check")
def check_radius_message(login: str = Query(...)):
    """
    Проверить наличие RADIUS для логина.
    """
    try:
        with db() as (cnx, cursor):
            cursor.execute("SELECT * FROM A WHERE User_Name = %s", (login,))
            row = cursor.fetchone()
            if row:
                columns = get_columns(cursor)
                data = dict(zip(columns, row))
                return {"found": True, "message": "RADIUS сообщение найдено", "comment": None, "data": data}
            else:
                return {"found": False, "message": "RADIUS сообщение не найдено", "comment": "Ожидание RADIUS Accounting-Start..."}
    except Exception as e:
        logger.error(f"Failed to check RADIUS message for {login}: {e}")
        return {"found": False, "message": f"Ошибка проверки: {str(e)}", "comment": None}

@router.get("/health")
def health_check():
    return {"status": "healthy", "service": "mhe_db"}