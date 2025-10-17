import logging
from hashlib import md5
from socket import socket, AF_INET, SOCK_DGRAM
from scapy.all import sniff
from scapy.layers.radius import Radius
from scapy.layers.inet import IP
from pyrad.packet import Packet
from config.env import st
import requests

logger = logging.getLogger("mhe_radius")

server_socket = socket(AF_INET, SOCK_DGRAM)
server_socket.bind(('0.0.0.0', 1813))

RADIUS_ATTRS = {
    1: "User-Name",
    25: "Class",
    8: "Framed-IP-Address",
    123: "Delegated-IPv6-Prefix",
    4: "NAS-IP-Address",
}

MHE_DB_HOST = st.MHE_DB_HOST
MHE_DB_PORT = st.MHE_DB_PORT

def build_radius_response(req, secret):
    s = secret.encode() if isinstance(secret, str) else secret
    resp = Radius(
        code=5,
        id=req.id,
        len=req.len,
        authenticator=req.authenticator,
        attributes=req.attributes,
    )
    resp.authenticator = md5(resp.build() + s).digest()
    return resp

def extract_attributes(radius_dict):
    attrs = {RADIUS_ATTRS[n]: v[0] if isinstance(v, (list, tuple)) and v else v
             for n, v in radius_dict.items() if n in RADIUS_ATTRS}
    nas_ip = attrs.get('NAS-IP-Address')
    return attrs, nas_ip

def send_radius_response(packet, secret):
    try:
        host, port = str(packet[2]).split(" ")[1].split(":")
        resp = build_radius_response(packet[Radius], secret)
        server_socket.sendto(bytes(resp), (host, int(port)))
        logger.info(f"Sent RADIUS Accounting-Response to {host}:{port}")
        return True
    except Exception:
        logger.warning("Failed to send RADIUS response")
        return False

def forward_to_fortigate(data, nas_ip):
    for fg in st.FORTI_GATE.get(nas_ip, []):
        try:
            server_socket.sendto(data, (str(fg), 1813))
            logger.info(f"Forwarded RADIUS packet to FortiGate {fg}")
            return
        except Exception as e:
            logger.warning(f"Failed to forward to FortiGate {fg}: {e}")
    logger.error(f"No FortiGate configured or all failed for NAS-IP {nas_ip}")

def send_to_mysql_handler(attrs):
    try:
        url = f"http://{MHE_DB_HOST}:{MHE_DB_PORT}/radius_event"
        resp = requests.post(url, json={"attrs": attrs}, timeout=2)
        if resp.status_code == 200:
            logger.info(f"Sent RADIUS attributes to MHE_DB: {attrs}")
        else:
            logger.info(f"HTTP POST failed: {resp.status_code} {resp.text}")
    except Exception as e:
        logger.error(f"Failed to send to MHE_DB: {e}")

def parse_packet(pkt):
    try:
        if not getattr(pkt, "haslayer", None) or not pkt.haslayer(Radius):
            return
        r = pkt[Radius]

        if r.code == 4:
            radius_bytes = bytes(r)
            pyrad_packet = Packet(packet=radius_bytes)
            if send_radius_response(pkt, st.RADIUS_SHARED_SECRET):
                attrs, nas_ip = extract_attributes(pyrad_packet)
                forward_to_fortigate(radius_bytes, nas_ip)
                send_to_mysql_handler(attrs)

        elif r.code == 5:
            try:
                src_ip = pkt[IP].src
            except Exception:
                try:
                    src_ip = str(pkt[1]).split(" ")[0]
                except Exception:
                    src_ip = "unknown"
            logger.info(f"Received RADIUS Accounting-Response (Code=5) from FG {src_ip}")

    except Exception as e:
        logger.error(f"Packet processing error: {e}")

def main():
    logging.basicConfig(filename='mhe_radius.log', level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    logger.info("Starting MHE RADIUS sniffer on UDP port 1813...")
    try:
        sniff(prn=parse_packet, filter="udp and port 1813", store=0)
    except KeyboardInterrupt:
        logger.info("MHE RADIUS sniffer stopped by user.")

if __name__ == "__main__":
    main()
