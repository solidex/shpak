import mysql.connector
from config.env import st
import logging
from datetime import datetime
from fastapi import APIRouter, Body, Query
from fastapi.responses import JSONResponse
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

def save_policy_log(user, fg, response):
    try:
        with db() as (cnx, cursor):
            cursor.execute(
                "INSERT INTO PolicyLogs (User_Name, Timestamp, Policy_ID, Result, HTTP_Status, FG_Address) VALUES (%s, %s, %s, %s, %s, %s)",
                (user, str(datetime.now()), response.get("mkey", 'NULL'), response.get("status"), response.get("http_status"), fg)
            )
            cnx.commit()
        return True
    except Exception as e:
        logger.error("Failed to save policy log: %s", e)
        return False

def get_policy_log(user, fg):
    try:
        with db() as (cnx, cursor):
            cursor.execute(
                "SELECT User_Name, Policy_ID FROM PolicyLogs WHERE User_Name=%s AND Result='success' AND FG_Address=%s ORDER BY Timestamp DESC LIMIT 1",
                (user, fg)
            )
            return cursor.fetchall()
    except Exception as e:
        logger.error("Failed to get policy log: %s", e)
        return []

def resp(success=True, data=None, error=None):
    r = {"success": success}
    if data is not None: r["data"] = data
    if error: r["error"] = error
    return r

@router.post("/policy_logs")
def api_connect_policy_log(payload: dict = Body(...)):
    user = payload.get("user")
    fg = payload.get("fg")
    response = payload.get("response")
    if not (user and fg and response):
        return resp(False, error="Missing required fields")
    ok = save_policy_log(user, fg, response)
    return resp(success=ok)

@router.get("/policy_logs/by_user")
def api_get_policy_log(user: str = Query(...), fg: str = Query(...)):
    rows = get_policy_log(user, fg)
    return resp(data=rows)

@router.post("/firewall_profiles/update_policy_id")
def update_policy_id(payload: dict = Body(...)):
    login = payload.get("login")
    hash_val = payload.get("hash")
    policy_id = payload.get("policy_id")
    if not (login and hash_val and policy_id):
        return resp(False, error="Missing required fields")
    try:
        with db() as (cnx, cursor):
            cursor.execute(
                "UPDATE firewall_profiles SET policy_id = %s WHERE login = %s AND hash = %s",
                (policy_id, login, hash_val)
            )
            cnx.commit()
        return resp(data={"updated": True})
    except Exception as e:
        return resp(False, error=str(e)) 