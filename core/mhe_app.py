import json
import logging
from fastapi import FastAPI, HTTPException, Response, status, Query, Body
from fastapi.responses import ORJSONResponse
from datetime import datetime
from models.fastclass import (
    FirewallProfilePagination,
    CreateProfileRequest,
    UpdateProfileRequest,
    PrettyJSONResponse,
)
from pydantic import BaseModel
from config.env import st
import requests

logger = logging.getLogger("mhe_app")
app = FastAPI()

MHE_DB_URL = f"http://{st.MHE_DB_HOST}:{st.MHE_DB_PORT}"

class KeepaliveRequest(BaseModel):
    login: str

def db_request(method: str, path: str, **kwargs):
    try:
        resp = requests.request(method, f"{MHE_DB_URL}{path}", timeout=5, **kwargs)
        resp.raise_for_status()
        js = resp.json()
        if not js.get("success", True):
            msg = js.get("error") or "DB error"
            comment = js.get("comment")
            if 'not found' in str(msg).lower():
                raise HTTPException(status_code=404, detail=msg)
            raise HTTPException(status_code=400, detail=f"{msg}. {comment}" if comment else msg)
        return js
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"DB {method} error: {e}")
        raise HTTPException(status_code=500, detail=f"DB {method} error: {e}")

@app.get("/api/firewall_profile_rules", response_class=ORJSONResponse)
async def get_firewall_profiles(page: int = 1, page_size: int = 25):
    with open('config/ports.json') as f:
        raw_data = json.load(f)
    return FirewallProfilePagination(raw_data, page_size).paginate(page)

@app.get("/api/firewall_custom_profile_unauthorized", response_class=PrettyJSONResponse)
async def get_custom_profile(logins: str):
    login_set = {l.strip() for l in logins.split(',') if l.strip()}
    resp = db_request("GET", "/firewall_profiles", params={"page": 1, "page_size": 10000, "login": None})
    profiles = resp.get("data", []) or []
    result = {p['login']: p for p in profiles if p['login'] in login_set}
    if not result:
        raise HTTPException(status_code=404, detail="Профиль не найден")
    return result

@app.post("/api/firewall_custom_profile_unauthorized", response_class=PrettyJSONResponse)
async def create_custom_profile(profile_data: CreateProfileRequest):
    required = (profile_data.name, profile_data.login, profile_data.tcp_rules, profile_data.udp_rules)
    if not all(required):
        raise HTTPException(status_code=400, detail="Недостаточно данных для создания профиля")
    resp = db_request("GET", "/firewall_profiles", params={"page": 1, "page_size": 10000, "login": profile_data.login})
    profiles = resp.get("data", []) or []
    if any(p['login'] == profile_data.login for p in profiles):
        raise HTTPException(status_code=400, detail=f"Профиль для логина {profile_data.login} уже существует")
    now = datetime.now().isoformat()
    profile = {
        "profile_type": "billing",
        "can_delete": 1,
        "profile_name": None,
        "created_at": now,
        "updated_at": now,
        "name": profile_data.name,
        "login": profile_data.login,
        "ip_pool": None,
        "ip_v6_pool": None,
        "region_id": "7",
        "tcp_rules": profile_data.tcp_rules,
        "udp_rules": profile_data.udp_rules,
        "firewall_profile": profile_data.firewall_profile,
    }
    resp2 = db_request("POST", "/firewall_profiles", json=profile)
    profile["id"] = resp2.get("data", {}).get("id")
    if resp2.get("comment"):
        profile["comment"] = resp2["comment"]
    return profile

@app.put("/api/firewall_custom_profile_unauthorized/{id}", response_class=PrettyJSONResponse)
async def update_custom_profile(id: int, profile_data: UpdateProfileRequest):
    old = db_request("GET", f"/firewall_profiles/{id}")
    old_data = old.get("data") or {}
    now = datetime.now().isoformat()
    profile = {
        "profile_type": "billing",
        "can_delete": 1,
        "profile_name": None,
        "created_at": old_data.get("created_at"),
        "updated_at": now,
        "name": profile_data.name,
        "login": profile_data.login,
        "ip_pool": None,
        "ip_v6_pool": None,
        "region_id": "7",
        "tcp_rules": profile_data.tcp_rules,
        "udp_rules": profile_data.udp_rules,
        "firewall_profile": profile_data.firewall_profile,
    }
    resp2 = db_request("PUT", f"/firewall_profiles/{id}", json=profile)
    profile["id"] = id
    if resp2.get("comment"):
        profile["comment"] = resp2["comment"]
    return profile

@app.delete("/api/firewall_custom_profile_unauthorized/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_custom_profile(id: int):
    resp = db_request("DELETE", f"/firewall_profiles/{id}")
    if resp.get("comment"):
        return {"success": True, "comment": resp["comment"]}
    return Response(status_code=204)

@app.post("/keepalive", response_class=PrettyJSONResponse)
async def receive_keepalive(keepalive_data: KeepaliveRequest = Body(...)):
    login = keepalive_data.login
    logger.info(f"Received keepalive for login: {login}")
    try:
        url = f"http://{st.MHE_AE_HOST}:{st.MHE_AE_PORT}/keepalive"
        result = requests.post(url, json={"login": login}, timeout=2)
        if result.status_code == 200:
            return {"success": True, "message": f"Keepalive forwarded for {login}"}
        return {"success": False, "error": f"Failed to forward keepalive, status: {result.status_code}"}
    except Exception as e:
        logger.error(f"Error forwarding keepalive for {login}: {e}")
        raise HTTPException(status_code=500, detail=f"Error forwarding keepalive: {e}")

if __name__ == "__main__":
    import uvicorn
    logging.basicConfig(filename='mhe_app.log', level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    uvicorn.run(app, host="0.0.0.0", port=80)
