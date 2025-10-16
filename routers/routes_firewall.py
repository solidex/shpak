from fastapi import APIRouter, Query, Body
from typing import Optional
from models.models import FirewallProfileIn, ListResponse, ItemResponse, SimpleResponse
import mysql.connector, requests, hashlib
from contextlib import contextmanager
import time
import logging
from config.env import st

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

MHE_AE_URL = f"http://{st.MHE_AE_HOST}:{st.MHE_AE_PORT}/signal"
MHE_APP_URL = f"http://{st.MHE_APP_HOST}:{st.MHE_APP_PORT}/keepalive"

def send_signal(action, data):
    try: 
        requests.post(MHE_AE_URL, json={"action": action, "data": data}, timeout=2)
    except Exception as e:
        logger.warning(f"Failed to send signal to MHE_AE: {e}")

def get_columns(cursor): return [col[0] for col in cursor.description] if cursor.description else []

def check_radius_with_keepalive(login: str, max_attempts: int = 3, delay: float = 0.5):
    """
    Проверяет наличие RADIUS сообщения с keepalive и повторными попытками
    """
    for attempt in range(max_attempts):
        with db() as (cnx, cursor):
            cursor.execute("SELECT * FROM A WHERE User_Name = %s", (login,))
            row = cursor.fetchone()
            columns = get_columns(cursor)
            
            if row and columns:
                return True, dict(zip(columns, row))
        
        # Если RADIUS не найден и это не последняя попытка
        if attempt < max_attempts - 1:
            # Отправляем keepalive на MHE_APP
            try:
                requests.post(MHE_APP_URL, json={"login": login}, timeout=1)
            except:
                pass  # Игнорируем ошибки keepalive
            
            time.sleep(delay)
    
    # Если RADIUS не найден после всех попыток
    return False, None

@router.get("/firewall_profiles", response_model=ListResponse)
def list_firewall_profiles(page: int = Query(1), page_size: int = Query(25), login: Optional[str] = Query(None)):
    try:
        with db() as (cnx, cursor):
            offset = (page - 1) * page_size
            if login:
                cursor.execute("SELECT * FROM firewall_profiles WHERE login = %s LIMIT %s OFFSET %s", (login, page_size, offset))
            else:
                cursor.execute("SELECT * FROM firewall_profiles LIMIT %s OFFSET %s", (page_size, offset))
            columns = get_columns(cursor)
            rows = cursor.fetchall()
            data = [dict(zip(columns, row)) for row in rows] if columns and rows else []
            if login:
                cursor.execute("SELECT COUNT(*) FROM firewall_profiles WHERE login = %s", (login,))
            else:
                cursor.execute("SELECT COUNT(*) FROM firewall_profiles")
            count_row = cursor.fetchone()
            total = count_row[0] if count_row is not None else 0
        return resp(data=data, total=total, page=page, page_size=page_size)
    except Exception as e:
        return resp(False, error=str(e), data=[], total=0, page=page, page_size=page_size)

@router.get("/firewall_profiles/{id}", response_model=ItemResponse)
def get_firewall_profile(id: int):
    try:
        with db() as (cnx, cursor):
            cursor.execute("SELECT * FROM firewall_profiles WHERE id = %s", (id,))
            row = cursor.fetchone()
            columns = get_columns(cursor)
            if not row or not columns: return resp(False, error="Not found")
        return resp(data=dict(zip(columns, row)))
    except Exception as e:
        return resp(False, error=str(e))

@router.post("/firewall_profiles", response_model=ItemResponse)
def create_firewall_profile(profile: FirewallProfileIn = Body(...)):
    try:
        # Проверяем наличие RADIUS сообщения с keepalive и повторными попытками
        radius_found, radius_data = check_radius_with_keepalive(profile.login)
        
        if not radius_found:
            return resp(False, error="RADIUS Accounting-Start не найден после 3 попыток", comment="Ожидание RADIUS Accounting-Start...")
        
        # Если RADIUS сообщение найдено, создаем профиль файрвола
        hash_val = hashlib.md5(f"{profile.tcp_rules}|{profile.udp_rules}".encode()).hexdigest()
        with db() as (cnx, cursor):
            cursor.execute(
                "INSERT INTO firewall_profiles (profile_type, can_delete, profile_name, created_at, updated_at, name, login, ip_pool, ip_v6_pool, region_id, tcp_rules, udp_rules, firewall_profile, hash) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (profile.profile_type, profile.can_delete, profile.profile_name, profile.created_at, profile.updated_at, profile.name, profile.login, profile.ip_pool, profile.ip_v6_pool, profile.region_id, profile.tcp_rules, profile.udp_rules, profile.firewall_profile, hash_val)
            )
            cnx.commit()
            new_id = cursor.lastrowid
            
            # Отправляем сигнал для создания конфигурации на FortiGate
            joined = radius_data.copy()
            joined.update({'tcp_rules': profile.tcp_rules, 'udp_rules': profile.udp_rules, 'hash': hash_val})
            send_signal("create", joined)
            
        return resp(data={"id": new_id})
    except Exception as e:
        return resp(False, error=str(e))

@router.put("/firewall_profiles/{id}", response_model=ItemResponse)
def update_firewall_profile(id: int, profile: FirewallProfileIn = Body(...)):
    try:
        # Проверяем наличие RADIUS сообщения с keepalive и повторными попытками
        radius_found, radius_data = check_radius_with_keepalive(profile.login)
        
        if not radius_found:
            return resp(False, error="RADIUS Accounting-Start не найден после 3 попыток", comment="Ожидание RADIUS Accounting-Start...")
        
        # Если RADIUS сообщение найдено, обновляем профиль файрвола
        with db() as (cnx, cursor):
            cursor.execute("SELECT hash FROM firewall_profiles WHERE id = %s", (id,))
            old_hash = cursor.fetchone()
            old_hash = old_hash[0] if old_hash else None
            
            hash_val = hashlib.md5(f"{profile.tcp_rules}|{profile.udp_rules}".encode()).hexdigest()
            cursor.execute(
                """INSERT INTO firewall_profiles (id, profile_type, can_delete, profile_name, created_at, updated_at, name, login, ip_pool, ip_v6_pool, region_id, tcp_rules, udp_rules, firewall_profile, hash) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (id, profile.profile_type, profile.can_delete, profile.profile_name, profile.created_at, profile.updated_at, profile.name, profile.login, profile.ip_pool, profile.ip_v6_pool, profile.region_id, profile.tcp_rules, profile.udp_rules, profile.firewall_profile, hash_val)
            )
            cnx.commit()

            # Отправляем сигнал для обновления конфигурации на FortiGate
            joined = radius_data.copy()
            joined.update({'tcp_rules': profile.tcp_rules, 'udp_rules': profile.udp_rules, 'hash': hash_val, 'old_hash': old_hash})
            send_signal("edit", joined)
            
        return resp(data={"id": id})
    except Exception as e:
        return resp(False, error=str(e))

@router.delete("/firewall_profiles/{id}", response_model=SimpleResponse)
def delete_firewall_profile(id: int):
    try:
        with db() as (cnx, cursor):
            cursor.execute("SELECT login, tcp_rules, udp_rules, policy_id, hash FROM firewall_profiles WHERE id = %s", (id,))
            row = cursor.fetchone()
            login, tcp_rules, udp_rules, policy_id, hash_val = row if row else (None, None, None, None, None)
            
            if not login:
                return resp(False, error="Профиль не найден")
        
        # Проверяем наличие RADIUS сообщения с keepalive и повторными попытками
        radius_found, radius_data = check_radius_with_keepalive(login)
        
        if not radius_found:
            return resp(False, error="RADIUS Accounting-Start не найден после 3 попыток", comment="Ожидание RADIUS Accounting-Start...")
        
        # Если RADIUS сообщение найдено, удаляем профиль файрвола
        with db() as (cnx, cursor):
            cursor.execute("DELETE FROM firewall_profiles WHERE id = %s", (id,))
            cnx.commit()
            
            # Отправляем сигнал для удаления конфигурации на FortiGate
            joined = radius_data.copy()
            joined.update({'tcp_rules': tcp_rules, 'udp_rules': udp_rules, 'policy_id': policy_id, 'hash': hash_val})
            send_signal("delete", joined)
            
        return resp()
    except Exception as e:
        return resp(False, error=str(e))

@router.get("/radius_check")
def check_radius_message(login: str = Query(...)):
    """
    Проверяет наличие RADIUS сообщения для указанного логина
    """
    try:
        with db() as (cnx, cursor):
            cursor.execute("SELECT * FROM A WHERE User_Name = %s", (login,))
            row = cursor.fetchone()
            columns = get_columns(cursor)
            
            if row and columns:
                radius_data = dict(zip(columns, row))
                return {
                    "found": True,
                    "message": "RADIUS сообщение найдено",
                    "comment": None,
                    "data": radius_data
                }
            else:
                return {
                    "found": False,
                    "message": "RADIUS сообщение не найдено",
                    "comment": "Ожидание RADIUS Accounting-Start..."
                }
    except Exception as e:
        return {
            "found": False,
            "message": f"Ошибка проверки: {str(e)}",
            "comment": None
        }

@router.get("/health")
def health_check():
    """
    Проверка здоровья сервиса
    """
    return {"status": "healthy", "service": "mhe_db"}