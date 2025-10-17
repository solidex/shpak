import logging
from fastapi import FastAPI, Body

try:
    from ldap3 import Server, Connection, ALL
except ImportError:
    Server = Connection = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mhe_ldap")
app = FastAPI(title="MHE LDAP Service")


def ldap_lookup(logins, server, bind_dn, bind_pw, base_dn):
    """Very simple LDAP lookup for emails by login."""
    result = {login: [] for login in logins}
    if not (Server and server):
        logger.warning("LDAP unavailable/config missing")
        return result
    try:
        with Connection(Server(server, get_info=ALL), user=bind_dn, password=bind_pw, auto_bind=True) as c:
            for login in logins:
                filt = f"(|(sAMAccountName={login})(uid={login})(mailNickname={login}))"
                c.search(search_base=base_dn or '', search_filter=filt, attributes=["mail"])
                result[login] = [str(e["mail"].value) for e in c.entries if "mail" in e and e["mail"].value]
    except Exception as e:
        logger.error(f"LDAP lookup failed: {e}")
    return result


@app.post("/lookup")
def lookup(payload=Body(...)):
    logins = [str(u).strip() for u in payload.get("logins", []) if str(u).strip()]
    ldap_cfg = payload.get("ldap", {}) or {}
    users = ldap_lookup(
        logins,
        ldap_cfg.get("server"),
        ldap_cfg.get("bind_dn"),
        ldap_cfg.get("bind_pw"),
        ldap_cfg.get("base_dn"),
    )
    return {"users": users}


@app.get("/health")
def health():
    return {"status": "ok", "service": "mhe_ldap"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8086)
