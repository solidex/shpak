import os
import logging
from fastapi import FastAPI

try:
    from ldap3 import Server, Connection, ALL, Tls
except ImportError:
    Server = Connection = Tls = None

try:
    from app.config.env import st
except ImportError:
    st = None

logger = logging.getLogger("mhe_ldap")
if not logger.hasHandlers():
    log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
    os.makedirs(log_dir, exist_ok=True)
    handler = logging.FileHandler(os.path.join(log_dir, "mhe_ldap.log"), encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)

app = FastAPI()

def ldap_list_with_emails(uri, dn, pw, base_dn, start_tls=False):
    if not (Server and uri and dn and pw):
        logger.error("LDAP config missing or ldap3 not installed")
        return []
    try:
        tls = Tls(validate=None) if (uri.startswith("ldaps://") or start_tls) else None
        server = Server(uri, get_info=ALL, tls=tls)
        conn = Connection(server, user=dn, password=pw, auto_bind=True)
        if start_tls and not uri.startswith("ldaps://"):
            conn.start_tls()
        conn.search(base_dn or '', '(mail=*)', attributes=["mail", "sAMAccountName", "uid", "mailNickname"])
        res = []
        for e in conn.entries:
            login = next((str(getattr(e, attr).value)
                         for attr in ("sAMAccountName", "uid", "mailNickname")
                         if hasattr(e, attr) and getattr(e, attr).value), None)
            mails = getattr(e, "mail", None)
            emails = []
            if mails:
                val = mails.value
                vals = mails.values if hasattr(mails, "values") else None
                emails = [str(v) for v in (vals or [val]) if v]
            if login and emails:
                res.append({"login": login, "emails": emails})
        logger.info(f"Listed {len(res)} users with emails")
        return res
    except Exception as e:
        logger.error(f"LDAP error: {e}")
        return []

@app.get("/list")
def list_users():
    if not st:
        logger.error("'st' not available")
        return {"users": []}
    users = ldap_list_with_emails(
        getattr(st, "LDAP_URI", None),
        getattr(st, "LDAP_BIND_DN", None),
        getattr(st, "LDAP_BIND_PASSWORD", None),
        getattr(st, "LDAP_BASE_DN", ""),
        str(getattr(st, "LDAP_START_TLS", "false")).lower() in {"1", "true", "yes"}
    )
    return {"users": users}

@app.get("/health")
def health():
    return {"status": "ok", "service": "mhe_ldap"}

if __name__ == "__main__":
    import uvicorn
    port = getattr(st, "MHE_LDAP_PORT", 80) if st else 80
    logger.info(f"Starting MHE LDAP on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
