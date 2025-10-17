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


def save_security_log(record: dict, fg_addr: str) -> None:
    timestamp_val = (f"{record.get('date', '')} {record.get('time', '')}".strip()
                     if record.get('date') and record.get('time')
                     else record.get('timestamp') or datetime.now().isoformat())

    def first_of(*keys):
        for k in keys:
            val = record.get(k)
            if val:
                return val
        return None

    user_name = first_of("user", "srcuser", "usr")
    devname = first_of("devname", "device")
    type_val = first_of("subtype", "type")
    event_val = first_of("eventtype", "event")
    level_val = record.get("level")
    src_ip = first_of("srcip", "src")
    src_port = first_of("srcport", "sport")
    dst_ip = first_of("dstip", "dst")
    dst_port = first_of("dstport", "dport")
    source_val = f"{src_ip or ''}:{src_port or ''}".strip(":") if src_ip or src_port else None
    destination_val = f"{dst_ip or ''}:{dst_port or ''}".strip(":") if dst_ip or dst_port else None
    message_val = first_of("msg", "message")
    syslog_json = json.dumps(record, ensure_ascii=False)

    try:
        cnx = mysql.connector.connect(**st.mysql_config)
        cursor = cnx.cursor()
        cursor.execute(
            """
            INSERT INTO SecurityLog
            (user, timestamp, devname, type, event, level, source, destination, message, syslog)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                user_name, timestamp_val, devname, type_val, event_val,
                level_val, source_val, destination_val, message_val, syslog_json,
            ),
        )
        cnx.commit()
        cursor.close()
        cnx.close()
    except Exception as e:
        logger.error(f"Failed to insert SecurityLog: {e}")


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
            save_security_log(record, fg_addr)
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
