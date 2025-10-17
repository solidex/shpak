import logging
from fastapi import APIRouter, Body
from models.models import ItemResponse
import mysql.connector
from config.env import st

logger = logging.getLogger(__name__)
router = APIRouter()

def query_db(query, params):
    try:
        with mysql.connector.connect(**st.mysql_config) as cnx:
            with cnx.cursor() as cursor:
                cursor.execute(query, params)
                return cursor.fetchall()
    except Exception as e:
        raise RuntimeError(str(e))

def resp(success=True, data=None, error=None):
    r = {"success": success}
    if data is not None: r["data"] = data
    if error: r["error"] = error
    return r

@router.post("/policy_id/by_hash", response_model=ItemResponse)
def get_policy_id_by_hash(payload: dict = Body(...)):
    hash_val = payload.get("hash")
    try:
        rows = query_db("SELECT policy_id FROM firewall_profiles WHERE hash = %s LIMIT 1", (hash_val,))
        return resp(data={"policy_id": rows[0][0]} if rows else None)
    except Exception as e:
        logger.error(f"Failed to get policy_id by hash: {e}")
        return resp(False, error=str(e))

@router.put("/policy_id/check", response_model=ItemResponse)
def check_policy_id_and_hash(payload: dict = Body(...)):
    policy_id = payload.get("policy_id")
    hash_val = payload.get("hash")
    try:
        count_rows = query_db("SELECT COUNT(*) FROM firewall_profiles WHERE policy_id = %s", (policy_id,))
        exists = count_rows[0][0] > 0 if count_rows else False
        rows = query_db("SELECT policy_id FROM firewall_profiles WHERE hash = %s LIMIT 1", (hash_val,))
        hash_policy_id = rows[0][0] if rows else None
        return resp(data={"policy_id_exists": exists, "policy_id_by_hash": hash_policy_id})
    except Exception as e:
        logger.error(f"Failed to check policy_id and hash: {e}")
        return resp(False, error=str(e))

@router.delete("/policy_id/check", response_model=ItemResponse)
def check_policy_id_exists(payload: dict = Body(...)):
    policy_id = payload.get("policy_id")
    try:
        count_rows = query_db("SELECT COUNT(*) FROM firewall_profiles WHERE policy_id = %s", (policy_id,))
        exists = count_rows[0][0] > 0 if count_rows else False
        return resp(data={"policy_id_exists": exists})
    except Exception as e:
        logger.error(f"Failed to check policy_id exists: {e}")
        return resp(False, error=str(e))