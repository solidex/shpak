from fastapi import APIRouter, Body
from models.models import ItemResponse
import mysql.connector
from config.env import st
from contextlib import contextmanager

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

def resp(success=True, data=None, error=None):
    r = {"success": success}
    if data is not None: r["data"] = data
    if error: r["error"] = error
    return r

@router.post("/policy_id/by_hash", response_model=ItemResponse)
def get_policy_id_by_hash(payload: dict = Body(...)):
    hash_val = payload.get("hash")
    try:
        with db() as (cnx, cursor):
            cursor.execute("SELECT policy_id FROM firewall_profiles WHERE hash = %s LIMIT 1", (hash_val,))
            row = cursor.fetchone()
            if row:
                return resp(data={"policy_id": row[0]})
            return resp(data=None)
    except Exception as e:
        return resp(False, error=str(e))

@router.put("/policy_id/check", response_model=ItemResponse)
def check_policy_id_and_hash(payload: dict = Body(...)):
    policy_id = payload.get("policy_id")
    hash_val = payload.get("hash")
    try:
        with db() as (cnx, cursor):
            cursor.execute("SELECT COUNT(*) FROM firewall_profiles WHERE policy_id = %s", (policy_id,))
            count_row = cursor.fetchone()
            exists = count_row[0] > 0 if count_row else False
            cursor.execute("SELECT policy_id FROM firewall_profiles WHERE hash = %s LIMIT 1", (hash_val,))
            row = cursor.fetchone()
            hash_policy_id = row[0] if row else None
        return resp(data={"policy_id_exists": exists, "policy_id_by_hash": hash_policy_id})
    except Exception as e:
        return resp(False, error=str(e))

@router.delete("/policy_id/check", response_model=ItemResponse)
def check_policy_id_exists(payload: dict = Body(...)):
    policy_id = payload.get("policy_id")
    try:
        with db() as (cnx, cursor):
            cursor.execute("SELECT COUNT(*) FROM firewall_profiles WHERE policy_id = %s", (policy_id,))
            count_row = cursor.fetchone()
            exists = count_row[0] > 0 if count_row else False
        return resp(data={"policy_id_exists": exists})
    except Exception as e:
        return resp(False, error=str(e)) 