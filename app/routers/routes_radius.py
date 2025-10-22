from fastapi import APIRouter
from app.models.models import RadiusEvent, SimpleResponse
import mysql.connector
from mysql.connector import pooling
from app.config.env import st
from datetime import datetime
import requests
import logging
import asyncio
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)
router = APIRouter()

# Connection Pool for parallel RADIUS event processing
try:
    db_pool = pooling.MySQLConnectionPool(
        pool_name="radius_pool",
        pool_size=50,  # Handle up to 50 concurrent RADIUS events
        pool_reset_session=True,
        **getattr(st, 'starrocks_config', st.mysql_config)
    )
    logger.info("RADIUS connection pool created (size=50)")
except Exception as e:
    logger.error(f"Failed to create RADIUS connection pool: {e}")
    db_pool = None

# Thread pool for blocking I/O (DB queries, HTTP requests)
executor = ThreadPoolExecutor(max_workers=100, thread_name_prefix="radius_worker")
logger.info("RADIUS thread pool executor created (max_workers=100)")

# StarRocks Stream Load settings
STARROCKS_HOST = st.starrocks_config.get('host', '127.0.0.1')
STARROCKS_PORT = st.starrocks_config.get('port', 9030)
STARROCKS_USER = st.starrocks_config.get('user', 'root')
STARROCKS_PASSWORD = st.starrocks_config.get('password', '')
STARROCKS_DB = st.starrocks_config.get('database', 'RADIUS')

RADIUS_COLUMNS = ["User_Name", "Timestamp", "Acct_Status_Type", "Framed_IP_Address", "Delegated_IPv6_Prefix", "NAS_IP_Address"]

def insert_radius_streamload(user_name: str, timestamp: str, acct_status_type: str, framed_ip: str, ipv6_prefix: str, nas_ip: str) -> bool:
    """Fast INSERT via Stream Load for RADIUS_Sessions"""
    try:
        values = [user_name, timestamp, acct_status_type, framed_ip, ipv6_prefix, nas_ip]
        csv_line = ",".join([f'"{v}"' for v in values])
        
        url = f"http://{STARROCKS_HOST}:{STARROCKS_PORT}/api/{STARROCKS_DB}/RADIUS_Sessions/_stream_load"
        headers = {
            "label": f"radius_{datetime.now().timestamp()}",
            "column_separator": ",",
            "format": "csv",
        }
        
        response = requests.put(
            url,
            auth=(STARROCKS_USER, STARROCKS_PASSWORD),
            headers=headers,
            data=csv_line.encode('utf-8'),
            timeout=5
        )
        
        if response.status_code == 200:
            result = response.json()
            return result.get("Status") == "Success"
        return False
    except Exception as e:
        logger.error(f"Stream Load failed for RADIUS: {e}")
        return False

def resp(success=True, data=None, error=None, **kwargs):
    r = {"success": success}
    if data is not None:
        r["data"] = data
    if error:
        r["error"] = error
    r.update(kwargs)
    return r

MHE_AE_URL = f"http://{st.MHE_AE_HOST}:{st.MHE_AE_PORT}/signal"

def send_signal(action, data):
    try:
        requests.post(MHE_AE_URL, json={"action": action, "data": data}, timeout=2)
    except Exception as e:
        logger.warning(f"Failed to send signal to MHE_AE: {e}")

def process_radius_event_sync(attrs: dict):
    """Process single RADIUS event (thread-safe, for parallel execution)"""
    try:
        acct_status = attrs.get('Acct-Status-Type', '').lower()
        class_val = str(attrs.get('Class', ''))
        user_name = attrs.get('User-Name', '')

        # Only consider classes that matter
        valid_classes = {'2', '00000002', b'2', b'00000002'}
        if class_val not in valid_classes:
            return {"success": True, "skipped": True}

        # Process RADIUS event
        if acct_status == 'start':
            # Fast INSERT via Stream Load
            insert_ok = insert_radius_streamload(
                user_name,
                str(datetime.now()),
                attrs.get('Acct-Status-Type', ''),
                attrs.get('Framed-IP-Address', ''),
                attrs.get('Delegated-IPv6-Prefix', ''),
                attrs.get('NAS-IP-Address', '')
            )
            
            if not insert_ok:
                logger.warning(f"Stream Load failed for RADIUS start: user={user_name}")
            
            # Check if firewall profile exists (use connection pool)
            cnx = db_pool.get_connection() if db_pool else mysql.connector.connect(**getattr(st, 'starrocks_config', st.mysql_config))
            cursor = cnx.cursor()
            try:
                cursor.execute("SELECT tcp_rules, udp_rules FROM FW_Profiles WHERE login = %s", (user_name,))
                profile = cursor.fetchone()
                if profile:
                    joined = dict(attrs)
                    joined['tcp_rules'], joined['udp_rules'] = profile
                    send_signal("create", joined)
            finally:
                cursor.close()
                cnx.close()
            
            logger.info(f"RADIUS start event processed: user={user_name}")

        elif acct_status == 'stop':
            # DELETE and SELECT via SQL (use connection pool)
            cnx = db_pool.get_connection() if db_pool else mysql.connector.connect(**getattr(st, 'starrocks_config', st.mysql_config))
            cursor = cnx.cursor()
            try:
                cursor.execute("DELETE FROM RADIUS_Sessions WHERE User_Name = %s", (user_name,))
                cursor.execute("SELECT tcp_rules, udp_rules FROM FW_Profiles WHERE login = %s", (user_name,))
                profile = cursor.fetchone()
                if profile:
                    joined = dict(attrs)
                    joined['tcp_rules'], joined['udp_rules'] = profile
                    send_signal("delete", joined)
                cnx.commit()
            finally:
                cursor.close()
                cnx.close()
            
            logger.info(f"RADIUS stop event processed: user={user_name}")

        return {"success": True}
    except Exception as e:
        logger.error(f"Failed to process RADIUS event: {e}")
        return {"success": False, "error": str(e)}

@router.post("/event", response_model=SimpleResponse)
async def receive_radius_event(event: RadiusEvent):
    """Receive RADIUS event and process it asynchronously (non-blocking)"""
    try:
        # Process in thread pool (non-blocking for other requests)
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(executor, process_radius_event_sync, event.attrs)
        return resp(**result)
    except Exception as e:
        logger.error(f"Failed to queue RADIUS event: {e}")
        return resp(False, error=str(e))