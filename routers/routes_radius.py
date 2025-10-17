from fastapi import APIRouter
from models.models import RadiusEvent, SimpleResponse
import mysql.connector
from config.env import st
from datetime import datetime
import requests
import logging

logger = logging.getLogger(__name__)
router = APIRouter()

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

@router.post("/event", response_model=SimpleResponse)
def receive_radius_event(event: RadiusEvent):
    try:
        attrs = event.attrs
        acct_status = attrs.get('Acct-Status-Type', '').lower()
        class_val = str(attrs.get('Class', ''))
        user_name = attrs.get('User-Name', '')

        # Only consider classes that matter
        valid_classes = {'2', '00000002', b'2', b'00000002'}
        if class_val not in valid_classes:
            return resp()  # Ignored event (nothing to do)

        # Minimal DB interaction, only open when required
        cnx = mysql.connector.connect(**st.mysql_config)
        cursor = cnx.cursor()
        try:
            if acct_status == 'start':
                cursor.execute(
                    "INSERT INTO A (User_Name, Timestamp, Acct_Status_Type, Framed_IP_Address, Delegated_IPv6_Prefix, NAS_IP_Address) VALUES (%s, %s, %s, %s, %s, %s)",
                    (user_name, str(datetime.now()), attrs.get('Acct-Status-Type', ''), attrs.get('Framed-IP-Address', ''), attrs.get('Delegated-IPv6-Prefix', ''), attrs.get('NAS-IP-Address', ''))
                )

                cursor.execute("SELECT tcp_rules, udp_rules FROM firewall_profiles WHERE login = %s", (user_name,))
                profile = cursor.fetchone()
                if profile:
                    joined = dict(attrs)
                    joined['tcp_rules'], joined['udp_rules'] = profile
                    send_signal("create", joined)
                logger.info(f"RADIUS start event processed: user={user_name}")

            elif acct_status == 'stop':
                cursor.execute("DELETE FROM A WHERE User_Name = %s", (user_name,))
                cursor.execute("SELECT tcp_rules, udp_rules FROM firewall_profiles WHERE login = %s", (user_name,))
                profile = cursor.fetchone()
                if profile:
                    joined = dict(attrs)
                    joined['tcp_rules'], joined['udp_rules'] = profile
                    send_signal("delete", joined)
                logger.info(f"RADIUS stop event processed: user={user_name}")
            cnx.commit()
        finally:
            cursor.close()
            cnx.close()

        return resp()
    except Exception as e:
        logger.error(f"Failed to process RADIUS event: {e}")
        return resp(False, error=str(e))