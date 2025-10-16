#start_settings.py

#db.py:
API_TOKEN = '1234567890'

mysql_config = {
    'user': 'root',
    'password': '',
    'host': '172.17.17.118',
    'database': 'Radius',
    'port': '30930',
    'use_pure':'True'
}

default_policy = {
    "srcintf": "PPoE",
    "dstintf": "Ethernet",
    "dstaddr": "all",
    "dstaddr6": "all",
    "schedule": "always",
    "utm-status": "enable",
    "av-profile": "g-default",
    "ips-sensor": "g-default",
    "ssl-ssh-profile": "no-inspect",
    "nat": "disable"
}

#sniffer.py

FORTI_GATE = {
    '172.26.203.254': ['172.20.10.107']
}
RADIUS_SERVER_IP = ['172.26.201.20', '172.26.201.30', '172.20.15.2']
RADIUS_SHARED_SECRET = b'testing123'

mail = '172.20.13.101'
config = '172.20.13.101'

# Host and port for mysql_handler FastAPI service
MYSQL_HANDLER_HOST = '127.0.0.1'
MYSQL_HANDLER_PORT = 18140

# Host and port for operation_logic FastAPI service (signals)
OPLOGIC_HOST = '127.0.0.1'
OPLOGIC_PORT = 8001

# Host and port for FastAPI SQL service
FASTAPI_SQL_HOST = '127.0.0.1'
FASTAPI_SQL_PORT = 8000

# Host and port for GUI service
GUI_HOST = '127.0.0.1'
GUI_PORT = 8080

# Host and port for Logging Service
LOGGING_SERVICE_HOST = '127.0.0.1'
LOGGING_SERVICE_PORT = 8084

# Host and port for MSG Restore Service (HTTP)
MSG_RESTORE_HOST = '0.0.0.0'
MSG_RESTORE_PORT = 8085

# Host and port for MSG Restore Telnet listener
MSG_RESTORE_TELNET_HOST = '0.0.0.0'
MSG_RESTORE_TELNET_PORT = 10023
