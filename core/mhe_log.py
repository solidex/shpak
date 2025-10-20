import asyncio
import json
import logging
from datetime import datetime

import mysql.connector
from config.env import st

logger = logging.getLogger("mhe_log")


def parse_syslog_payload(raw_text: str) -> dict | None:
    text = raw_text.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        return None

    #"action", "date", "dstcountry", "dstip", "dstport", "eventtype", 
    #"group", "ipaddr", "level", "msg", "srccountry", "srcip", 
    #"subtype", "time", "type", "user", "catdesc", "hostname", "service", 
    #"url", "agent", "crlevel", "threat"

EXTENDED_COLUMNS = [
    "action", "date", "dstcountry", "dstip", "dstport",
    "eventtype", "ipaddr", "msg", "srccountry", "srcip",
    "utmtype", "time", "user", "category", "hostname",
    "service", "url", "httpagent", "level", "threat"
]


def save_utm_log_full(record: dict) -> None:
    # Merge qname + hostname -> hostname
    if "qname" in record and record["qname"]:
        record["hostname"] = record.get("hostname") or record["qname"]
    
    # Merge virus + attack -> threat
    virus = record.get("virus", "")
    attack = record.get("attack", "")
    if virus or attack:
        record["threat"] = virus or attack
    
    # Backward-compatible field renames to match EXTENDED_COLUMNS
    # subtype -> utmtype
    if "subtype" in record:
        record["utmtype"] = record.get("subtype")
    # catdesc -> category
    if "catdesc" in record:
        record["category"] = record.get("catdesc")
    # agent -> httpagent
    if "agent" in record:
        record["httpagent"] = record.get("agent")
    # crlevel -> level
    if "crlevel" in record:
        record["level"] = record.get("crlevel")
    
    # Build values list in the order of EXTENDED_COLUMNS
    values = [str(record.get(col, "")) if record.get(col) is not None else None for col in EXTENDED_COLUMNS]

    # All column identifiers backticked to avoid reserved word conflicts
    cols_sql = ", ".join([f"`{c}`" for c in EXTENDED_COLUMNS])
    placeholders = ", ".join(["%s"] * len(EXTENDED_COLUMNS))

    try:
        cnx = mysql.connector.connect(**st.mysql_config)
        cursor = cnx.cursor()
        cursor.execute(
            f"INSERT INTO UTMLogs ({cols_sql}) VALUES ({placeholders})",
            values,
        )
        cnx.commit()
        cursor.close()
        cnx.close()
    except Exception as e:
        logger.error(f"Failed to insert UTM log (extended): {e}")


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

        fg_addr = addr[0] if isinstance(addr, tuple) else str(addr)
        try:
            # Save extended UTM fields exactly as provided
            save_utm_log_full(record)
            # Логируем ключевые поля для мониторинга
            logger.info(
                f"UTM log saved: user={record.get('user', 'N/A')}, "
                f"action={record.get('action', 'N/A')}, srcip={record.get('srcip', 'N/A')}, "
                f"dstip={record.get('dstip', 'N/A')}"
            )
        except Exception as e:
            logger.error(f"Failed to process UTM log: {e}")


async def run_udp_server(host: str = "0.0.0.0", port: int = 514):
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(SyslogUDP, local_addr=(host, port))
    logger.info(f"Syslog UDP server listening on {host}:{port}")
    return transport


def main():
    try:
        asyncio.run(run_udp_server())
    except PermissionError:
        logger.error("Permission denied binding to UDP/514. Run with elevated privileges or change port.")


if __name__ == "__main__":
    main()
