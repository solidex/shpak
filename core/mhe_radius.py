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

# UDP socket used for sending RADIUS packets (responses/forwarding)
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


def build_radius_response(request_packet, shared_secret):
    s = shared_secret.encode() if isinstance(shared_secret, str) else shared_secret
    resp = Radius(
        code=5,  # Accounting-Response
        id=request_packet.id,
        len=request_packet.len,
        authenticator=request_packet.authenticator,
        attributes=request_packet.attributes,
    )
    resp.authenticator = md5(resp.build() + s).digest()
    return resp


def extract_attributes(radius_dict):
    attributes, nas_ip = {}, None
    for number, value in radius_dict.items():
        if number in RADIUS_ATTRS:
            name = RADIUS_ATTRS[number]
            attributes[name] = value[0] if isinstance(value, (list, tuple)) and value else value
            if name == 'NAS-IP-Address':
                nas_ip = attributes[name]
    return attributes, nas_ip


def send_radius_response(scapy_packet, secret):
    try:
        # destination host:port is embedded in the scapy packet repr at index 2
        host, port = str(scapy_packet[2]).split(" ")[1].split(":")
        response = build_radius_response(scapy_packet[Radius], secret)
        server_socket.sendto(bytes(response), (host, int(port)))
        logger.info(f"Sent RADIUS Accounting-Response to {host}:{port}")
        return True
    except Exception:
        logger.warning("Failed to send RADIUS response")
        return False


def forward_to_fortigate(radius_packet_bytes, nas_ip):
    """Forward RADIUS packet to FortiGate with fallback support"""
    fg_list = st.FORTI_GATE.get(nas_ip, [])
    if not fg_list:
        logger.warning(f"No FortiGate configured for NAS-IP {nas_ip}")
        return
    
    success = False
    for fg_addr in fg_list:
        try:
            server_socket.sendto(radius_packet_bytes, (str(fg_addr), 1813))
            logger.info(f"Forwarded RADIUS packet to FortiGate {fg_addr}")
            success = True
            break  # Success, no need to try next FG
        except Exception as e:
            logger.warning(f"Failed to forward to FortiGate {fg_addr}: {e}")
            continue  # Try next FG in the list
    
    if not success:
        logger.error(f"Failed to forward RADIUS packet to any FortiGate for NAS-IP {nas_ip}")


def send_to_mysql_handler(attributes):
    """Send RADIUS attributes to MHE_DB without storing the packet"""
    try:
        payload = {
            "attrs": attributes,
        }
        url = f"http://{MHE_DB_HOST}:{MHE_DB_PORT}/radius_event"
        resp = requests.post(url, json=payload, timeout=2)
        if resp.status_code == 200:
            logger.info(f"Sent RADIUS attributes to MHE_DB: {attributes}")
        else:
            logger.info(f"HTTP POST failed: {resp.status_code} {resp.text}")
    except Exception as e:
        logger.error(f"Failed to send to MHE_DB: {e}")


def parse_packet(packet):
    try:
        if not (hasattr(packet, 'haslayer') and packet.haslayer(Radius)):
            return

        radius_layer = packet[Radius]

        # Accounting-Request (Code=4): process packet
        if radius_layer.code == 4:
            radius_bytes = bytes(radius_layer)
            pyrad_packet = Packet(packet=radius_bytes)

            if not send_radius_response(packet, st.RADIUS_SHARED_SECRET):
                return

            attributes, nas_ip = extract_attributes(pyrad_packet)
            forward_to_fortigate(radius_bytes, nas_ip)
            send_to_mysql_handler(attributes)  # Send only attributes, no packet
            return

        # Accounting-Response (Code=5): log the FortiGate source IP
        if radius_layer.code == 5:
            src_ip = None
            try:
                src_ip = packet[IP].src
            except Exception:
                pass

            if not src_ip:
                # best-effort fallback using scapy layer repr
                try:
                    src_ip = str(packet[1]).split(" ")[0]
                except Exception:
                    src_ip = "unknown"

            logger.info(f"Received RADIUS Accounting-Response (Code=5) from FG {src_ip}")
            return

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


