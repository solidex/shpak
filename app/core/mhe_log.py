import asyncio
import json
import logging
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

import mysql.connector
import requests
from app.config.env import st

logger = logging.getLogger("mhe_log")
if not logger.handlers:
    Path("logs").mkdir(exist_ok=True)
    handler = RotatingFileHandler("logs/mhe_log.log", maxBytes=10*1024*1024, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

EXTENDED_COLUMNS = [
    "action", "date", "dstcountry", "dstip", "dstport",
    "eventtype", "ipaddr", "msg", "srccountry", "srcip",
    "utmtype", "time", "user", "category", "hostname",
    "service", "url", "httpagent", "level", "threat"
]

# StarRocks settings
STARROCKS_HOST = st.starrocks_config.get('host', '127.0.0.1')
STARROCKS_PORT = st.starrocks_config.get('port', 9030)
STARROCKS_USER = st.starrocks_config.get('user', 'root')
STARROCKS_PASSWORD = st.starrocks_config.get('password', '')
STARROCKS_DB = st.starrocks_config.get('database', 'RADIUS')

def parse_syslog_payload(raw_text: str) -> dict | None:
    text = raw_text.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        return None

def _normalize_record(record: dict) -> dict:
    """Normalize FortiGate syslog fields"""
    # Merge qname + hostname -> hostname
    if "qname" in record and record["qname"]:
        record["hostname"] = record.get("hostname") or record["qname"]
    
    # Merge virus + attack -> threat
    virus = record.get("virus", "")
    attack = record.get("attack", "")
    if virus or attack:
        record["threat"] = virus or attack
    
    # Field renames
    if "subtype" in record:
        record["utmtype"] = record.get("subtype")
    if "catdesc" in record:
        record["category"] = record.get("catdesc")
    if "agent" in record:
        record["httpagent"] = record.get("agent")
    if "crlevel" in record:
        record["level"] = record.get("crlevel")
    
    return record

def save_to_starrocks(record: dict) -> bool:
    """Save to StarRocks (analytical storage - unlimited history)"""
    try:
        # Prepare CSV line for Stream Load
        values = [str(record.get(col, "")) if record.get(col) is not None else "" 
                  for col in EXTENDED_COLUMNS]
        csv_line = ",".join([f'"{v}"' for v in values])
        
        # Use Stream Load API (fast bulk insert)
        url = f"http://{STARROCKS_HOST}:{STARROCKS_PORT}/api/{STARROCKS_DB}/UTMLogs/_stream_load"
        
        headers = {
            "label": f"utm_{datetime.now().timestamp()}",
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
            if result.get("Status") == "Success":
                return True
            else:
                logger.warning(f"StarRocks load status: {result.get('Status')}")
                return False
        else:
            logger.error(f"StarRocks HTTP error: {response.status_code}")
            return False
            
    except Exception as e:
        logger.error(f"Failed to insert to StarRocks: {e}")
        return False

def save_utm_log(record: dict) -> None:
    """Save UTM log to StarRocks (unlimited retention, fast analytics)"""
    record = _normalize_record(record)
    if save_to_starrocks(record):
        logger.info(f"UTM log saved: user={record.get('user')}, action={record.get('action')}")
    else:
        logger.error(f"Failed to save UTM log: user={record.get('user')}")

class SyslogUDP(asyncio.DatagramProtocol):
    def datagram_received(self, data: bytes, addr):
        try:
            record = parse_syslog_payload(data.decode(errors="ignore").strip())
        except Exception:
            record = None

        if not isinstance(record, dict):
            logger.warning("Received non-JSON syslog payload; skipped")
            return

        if str(record.get("type", "")).lower() != "utm":
            return

        try:
            # Save to StarRocks only
            save_utm_log(record)
        except Exception as e:
            logger.error(f"Failed to process UTM log: {e}")

async def run_udp_server(host: str = "0.0.0.0", port: int = 514):
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(SyslogUDP, local_addr=(host, port))
    logger.info(f"Syslog UDP server (StarRocks) listening on {host}:{port}")
    return transport

def main():
    try:
        asyncio.run(run_udp_server())
    except PermissionError:
        logger.error("Permission denied binding to UDP/514. Run with elevated privileges or change port.")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    main()
