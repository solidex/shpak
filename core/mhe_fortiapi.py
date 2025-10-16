import logging, json, requests
from fastapi import FastAPI
from config.env import st
from models.fortigate_models import (
    CreateIPRequest, CreateIPv6Request, CreateServiceRequest, CreatePolicyRequest,
    DeleteObjectRequest, DeletePolicyRequest, MovePolicyRequest, GetPolicyRequest, EditPolicyRequest
)

logger = logging.getLogger("mhe_fortiapi")
app = FastAPI()

API_TOKEN = st.API_TOKEN
DEFAULT_POLICY = st.default_policy

def _headers():
    return {'Authorization': f'Bearer {API_TOKEN}', 'Content-Type': 'application/json'}

def _request(method, url, payload=None, timeout=5):
    try:
        data = json.dumps(payload) if payload is not None and not isinstance(payload, str) else payload
        r = requests.request(method, url, headers=_headers(), data=data, verify=False, timeout=timeout)
        if 200 <= r.status_code < 300:
            try: return r.json()
            except: return r.text
        logger.error(f"[FG] {method} {url} failed: {r.status_code} {r.text}")
        return None
    except requests.exceptions.Timeout:
        logger.error(f"[FG] Request timeout to {url}")
        return None
    except requests.exceptions.ConnectionError:
        logger.error(f"[FG] Connection error to {url}")
        return None
    except Exception as e:
        logger.error(f"[FG] REST request error: {e}")
        return None

def _request_with_fallback(method, url_template, fg_addr, payload=None, logmsg=None):
    """Make request with fallback to other FortiGate IPs if primary fails.
    
    Tries FG_IP_1 first, then FG_IP_2 if first fails based on FORTI_GATE mapping.
    """
    # Extract NAS-IP from the request if available
    nas_ip = None
    if payload and isinstance(payload, dict):
        nas_ip = payload.get('nas_ip') or payload.get('NAS-IP-Address')
    
    # Get FortiGate list for this NAS-IP
    fg_list = [fg_addr]  # Start with the requested FG
    if nas_ip and nas_ip in st.FORTI_GATE:
        fg_list = st.FORTI_GATE[nas_ip]
    
    last_error = None
    for fg_ip in fg_list:
        url = url_template.format(fg_addr=fg_ip)
        if logmsg and nas_ip:
            logger.info(logmsg.format(fg_addr=fg_ip, nas_ip=nas_ip))
        
        result = _request(method, url, payload)
        if result is not None:
            if fg_ip != fg_addr:
                logger.info(f"[FG] Successfully failed over to {fg_ip}")
            return result
        
        last_error = f"Failed to connect to {fg_ip}"
    
    logger.error(f"[FG] All FortiGate IPs failed for NAS-IP {nas_ip}: {last_error}")
    return None

def _endpoint(path, method, url_func, payload_func=None, logmsg=None, resp_key=None):
    def decorator(func):
        def wrapper(req):
            url = url_func(req)
            payload = payload_func(req) if payload_func else None
            if logmsg: logger.info(logmsg.format(**req.dict()))
            resp = _request(method, url, payload)
            if resp_key: return {resp_key: resp.get(resp_key) if isinstance(resp, dict) else None}
            return resp
        wrapper.__name__ = func.__name__
        app.post(path)(wrapper)
        return wrapper
    return decorator

_endpoint("/create_ip", "POST",
    lambda r: f"https://{r.fg_addr}/api/v2/cmdb/firewall/address",
    lambda r: {"name": r.name, "subnet": f"{r.ip} 255.255.255.255"},
    "[FG] Create IP {ip} for {name} on {fg_addr}"
)(lambda req: None)

_endpoint("/create_ipv6", "POST",
    lambda r: f"https://{r.fg_addr}/api/v2/cmdb/firewall/address6",
    lambda r: {"name": f"{r.name}v6", "ip6": r.ipv6},
    "[FG] Create IPv6 {ipv6} for {name} on {fg_addr}"
)(lambda req: None)

_endpoint("/create_service", "POST",
    lambda r: f"https://{r.fg_addr}/api/v2/cmdb/firewall.service/custom",
    lambda r: {"name": r.name, "tcp-portrange": r.tcp, "udp-portrange": r.udp},
    "[FG] Create service {name} (tcp={tcp}, udp={udp}) on {fg_addr}"
)(lambda req: None)

@app.post("/create_policy")
def create_policy(req: CreatePolicyRequest):
    # Build URL with required params
    url = f"https://{req.fg_addr}/api/v2/cmdb/firewall/policy?datasource=true&with_meta=true&vdom=transparent"
    # Build payload exactly as specified
    payload = {
        "name": req.name,
        "srcintf": [{"name": "PPPoE_vlan"}],
        "dstintf": [{"name": "Core_vlan"}],
        # Use pre-created address objects
        "srcaddr": [{"name": req.username}],
        "dstaddr": [
            {"name": "ns4.belpak.by_ipv4"},
            {"name": "ns3.belpak.by_ipv4"}
        ],
        # Use pre-created address6 object named `<user>v6`
        "srcaddr6": [{"name": f"{req.username}v6"}],
        "dstaddr6": [
            {"name": "ns3.belpak.by_ipv6"},
            {"name": "ns4.belpak.by_ipv6"}
        ],
        "schedule": "always",
        "service": [{"name": req.name}],  # Service object with inverted ports, named by <hash>
        "ssl-ssh-profile": "",
        "logtraffic": "disable",
        "groups": [{"name": "class2"}],
        "dstaddr-negate": "enable",
        "dstaddr6-negate": "enable"
    }
    logger.info(f"[FG] Create policy {req.name} for user {req.username} on {req.fg_addr}")
    resp = _request("POST", url, payload)
    return {"mkey": resp.get("mkey") if isinstance(resp, dict) else None}

for _name, _url, _log in [
    ("delete_ip",      lambda r: f"https://{r.fg_addr}/api/v2/cmdb/firewall/address/{r.name}",      "[FG] Delete IP {name} on {fg_addr}"),
    ("delete_ipv6",    lambda r: f"https://{r.fg_addr}/api/v2/cmdb/firewall/address6/{r.name}v6",   "[FG] Delete IPv6 {name}v6 on {fg_addr}"),
    ("delete_service", lambda r: f"https://{r.fg_addr}/api/v2/cmdb/firewall.service/custom/{r.name}","[FG] Delete service {name} on {fg_addr}"),
    ("delete_policy",  lambda r: f"https://{r.fg_addr}/api/v2/cmdb/firewall/policy/{r.policy_id}",  "[FG] Delete policy {policy_id} on {fg_addr}")
]:
    _endpoint(f"/{_name}", "DELETE" if "delete" in _name else "POST", _url, None, _log)(lambda req: None)

@app.post("/move_policy_to_top")
def move_policy_to_top(req: MovePolicyRequest):
    url = f"https://{req.fg_addr}/api/v2/cmdb/firewall/policy/{req.policy_id}?action=move&before=1"
    logger.info(f"[FG] Move policy {req.policy_id} to top on {req.fg_addr}")
    return _request("PUT", url)

@app.post("/get_policy")
def get_policy(req: GetPolicyRequest):
    url = f"https://{req.fg_addr}/api/v2/cmdb/firewall/policy/{req.policy_id}"
    logger.info(f"[FG] Get policy {req.policy_id} from {req.fg_addr}")
    return _request("GET", url)

@app.post("/edit_policy")
def edit_policy(req: EditPolicyRequest):
    policy = get_policy(GetPolicyRequest(fg_addr=req.fg_addr, policy_id=req.policy_id))
    if not policy or not isinstance(policy, dict):
        logger.error(f"[FG] Policy {req.policy_id} not found on {req.fg_addr}")
        return {"mkey": None}
    logger.info(f"[FG] Edit policy {req.policy_id} action={req.action} on {req.fg_addr} with payload: {req.extra}")
    if req.action in ("add", "rename"):
        resp = _request("POST", f"https://{req.fg_addr}/api/v2/cmdb/firewall/policy", policy)
        return {"mkey": resp.get("mkey") if isinstance(resp, dict) else None}
    elif req.action == "remove":
        _request("PUT", f"https://{req.fg_addr}/api/v2/cmdb/firewall/policy/{req.policy_id}", policy)
    return {"mkey": None}


@app.get("/health")
def health_check():
    return {"status": "ok", "service": "mhe_fortiapi"}


if __name__ == "__main__":
    import uvicorn
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    uvicorn.run(app, host="0.0.0.0", port=80)


