import logging
import mysql.connector
from config.env import st
from fastapi import APIRouter, Body, Query
from datetime import datetime

logger = logging.getLogger(__name__)
router = APIRouter()

def db():
    return mysql.connector.connect(**st.mysql_config)

def resp(success=True, data=None, error=None):
    r = {"success": success}
    if data is not None:
        r["data"] = data
    if error:
        r["error"] = error
    return r

@router.post("/policy_logs")
def api_connect_policy_log(payload: dict = Body(...)):
    user = payload.get("user")
    fg = payload.get("fg")
    response = payload.get("response")
    if not (user and fg and response):
        return resp(False, error="Missing required fields")
    try:
        cnx = db()
        cursor = cnx.cursor()
        cursor.execute(
            "INSERT INTO PolicyLogs (User_Name, Timestamp, Policy_ID, Result, HTTP_Status, FG_Address) VALUES (%s, %s, %s, %s, %s, %s)",
            (user, datetime.now(), response.get("mkey", 'NULL'), response.get("status"), response.get("http_status"), fg)
        )
        cnx.commit()
        cursor.close()
        cnx.close()
        logger.info(f"Policy log saved: user={user}, fg={fg}, policy_id={response.get('mkey')}")
        return resp(success=True)
    except Exception as e:
        logger.error(f"Failed to save policy log: {e}")
        return resp(False, error=str(e))

@router.get("/policy_logs/by_user")
def api_get_policy_log(user: str = Query(...), fg: str = Query(...)):
    try:
        cnx = db()
        cursor = cnx.cursor()
        cursor.execute(
            "SELECT User_Name, Policy_ID FROM PolicyLogs WHERE User_Name=%s AND Result='success' AND FG_Address=%s ORDER BY Timestamp DESC LIMIT 1",
            (user, fg)
        )
        rows = cursor.fetchall()
        cursor.close()
        cnx.close()
        return resp(data=rows)
    except Exception as e:
        logger.error(f"Failed to get policy log: {e}")
        return resp(False, error=str(e))

@router.post("/firewall_profiles/update_policy_id")
def update_policy_id(payload: dict = Body(...)):
    login = payload.get("login")
    hash_val = payload.get("hash")
    policy_id = payload.get("policy_id")
    if not (login and hash_val and policy_id):
        return resp(False, error="Missing required fields")
    try:
        cnx = db()
        cursor = cnx.cursor()
        cursor.execute(
            "UPDATE firewall_profiles SET policy_id = %s WHERE login = %s AND hash = %s",
            (policy_id, login, hash_val)
        )
        cnx.commit()
        cursor.close()
        cnx.close()
        logger.info(f"Policy ID updated: login={login}, hash={hash_val}, policy_id={policy_id}")
        return resp(data={"updated": True})
    except Exception as e:
        logger.error(f"Failed to update policy ID: {e}")
        return resp(False, error=str(e))