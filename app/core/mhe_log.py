import asyncio
import json
import logging
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

import requests
from app.config.env import st

logger = logging.getLogger("mhe_log")
if not logger.handlers:
    Path("logs").mkdir(exist_ok=True)
    handler = RotatingFileHandler("logs/mhe_log.log", maxBytes=10*1024*1024, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

# Оптимизированные колонки (12 полей вместо 23)
# Убрано: date, time (→ event_time), eventtype, ipaddr, httpagent, srccountry, dstcountry
# Объединено: srcip+srcport → source, dstip+dstport → destination, hostname+url → target
CORE_COLUMNS = [
    "event_time",   # DATETIME (объединено date + time)
    "user",
    "action",
    "utmtype",
    "source",       # srcip:srcport
    "destination",  # dstip:dstport
    "service",
    "target",       # hostname или url
    "category",
    "threat",
    "level",
    "msg"
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
    """Normalize FortiGate syslog fields to optimized schema"""
    normalized = {}
    
    # 1. event_time - объединить date + time
    date_str = record.get("date", "")
    time_str = record.get("time", "")
    if date_str and time_str:
        normalized["event_time"] = f"{date_str} {time_str}"
    else:
        normalized["event_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # 2. Основные поля
    normalized["user"] = record.get("user", "")
    normalized["action"] = record.get("action", "")
    
    # utmtype
    normalized["utmtype"] = record.get("subtype") or record.get("utmtype", "")
    
    # 3. Источник и назначение (IP:port)
    srcip = record.get("srcip", "")
    srcport = record.get("srcport", "")
    if srcip:
        normalized["source"] = f"{srcip}:{srcport}" if srcport else srcip
    else:
        normalized["source"] = ""
    
    dstip = record.get("dstip", "")
    dstport = record.get("dstport", "")
    if dstip:
        normalized["destination"] = f"{dstip}:{dstport}" if dstport else dstip
    else:
        normalized["destination"] = ""
    
    # 4. Web фильтрация
    # Объединить hostname/qname + url → target (приоритет URL)
    url = record.get("url", "")
    hostname = record.get("hostname") or record.get("qname", "")
    normalized["target"] = hostname if hostname else url
    
    # Category
    normalized["category"] = record.get("catdesc") or record.get("category", "")
    
    # 5. Безопасность
    # Merge virus + attack -> threat
    virus = record.get("virus", "")
    attack = record.get("attack", "")
    normalized["threat"] = virus or attack or record.get("threat", "")
    
    # Level
    normalized["level"] = record.get("crlevel") or record.get("level", "")
    
    # 6. Дополнительная информация
    normalized["service"] = record.get("service", "")
    normalized["msg"] = record.get("msg", "")
    
    return normalized

def save_to_starrocks(record: dict) -> bool:
    """Save to StarRocks using Stream Load API"""
    try:
        # Prepare CSV line
        values = []
        for col in CORE_COLUMNS:
            val = record.get(col)
            if val is None or val == "":
                values.append("")
            elif isinstance(val, (int, float)):
                values.append(str(val))
            else:
                # Escape quotes in strings
                values.append(str(val).replace('"', '""'))
        
        csv_line = ",".join([f'"{v}"' if v != "" else "" for v in values])
        
        # Stream Load API (порт 9060 для BE, но можно использовать FE)
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
                logger.warning(f"StarRocks load failed: {result.get('Status')}, {result.get('Message')}")
                return False
        else:
            logger.error(f"StarRocks HTTP {response.status_code}: {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"Failed to insert to StarRocks: {e}")
        return False

def save_utm_log(record: dict) -> None:
    """Save UTM log to StarRocks (optimized schema)"""
    normalized = _normalize_record(record)
    if save_to_starrocks(normalized):
        logger.info(f"UTM log saved: user={normalized.get('user')}, action={normalized.get('action')}")
    else:
        logger.error(f"Failed to save UTM log: user={normalized.get('user')}")

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
            save_utm_log(record)
        except Exception as e:
            logger.error(f"Failed to process UTM log: {e}")

async def run_udp_server(host: str = "0.0.0.0", port: int = 514):
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(SyslogUDP, local_addr=(host, port))
    logger.info(f"Syslog UDP server (StarRocks optimized) listening on {host}:{port}")
    return transport

def main():
    try:
        asyncio.run(run_udp_server())
    except PermissionError:
        logger.error("Permission denied binding to UDP/514. Run with elevated privileges or change port.")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    main()

