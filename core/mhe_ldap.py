import os
import ssl
import logging
from fastapi import FastAPI

try:
    from ldap3 import Server, Connection, ALL, Tls
except ImportError:
    Server = Connection = Tls = None

try:
    from config.env import st
except ImportError:
    st = None

# Простой логгер
logger = logging.getLogger("mhe_ldap")
if not logger.hasHandlers():
    log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
    os.makedirs(log_dir, exist_ok=True)
    handler = logging.FileHandler(os.path.join(log_dir, "mhe_ldap.log"), encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)

app = FastAPI(title="MHE LDAP Service")

def _connect(uri, dn, pw, start_tls):
    if not (Server and uri and dn and pw):
        logger.error("LDAP config missing or ldap3 not installed")
        return None
    try:
        tls_ctx = Tls(validate=ssl.CERT_NONE) if (uri.startswith("ldaps://") or start_tls) else None
        server = Server(uri, get_info=ALL, tls=tls_ctx)
        conn = Connection(server, user=dn, password=pw, auto_bind=True)
        if start_tls and not uri.startswith("ldaps://"):
            conn.start_tls()
        return conn
    except Exception as e:
        logger.error(f"LDAP connect failed: {e}")
        return None

def ldap_list_with_emails(server_uri, bind_dn, bind_pw, base_dn, start_tls=False):
    conn = _connect(server_uri, bind_dn, bind_pw, start_tls)
    if not conn:
        return []
    try:
        conn.search(base_dn or '', '(mail=*)', attributes=["mail", "sAMAccountName", "uid", "mailNickname"])
        result = []
        for e in conn.entries:
            login = next(
                (str(getattr(e, attr).value)
                 for attr in ("sAMAccountName", "uid", "mailNickname")
                 if hasattr(e, attr) and getattr(e, attr).value),
                None
            )
            if login and hasattr(e, "mail") and getattr(e, "mail").value:
                mail_attr = getattr(e, "mail")
                if hasattr(mail_attr, "values"):
                    emails = [str(v) for v in mail_attr.values if v]
                else:
                    emails = [str(mail_attr.value)] if mail_attr.value else []
                if emails:
                    result.append({"login": login, "emails": emails})
        logger.info(f"List users with emails: {len(result)} entries")
        return result
    except Exception as e:
        logger.error(f"LDAP list query failed: {e}")
        return []

@app.get("/list")
def list_users():
    """Return list of users with emails: [{login, emails: [..]}]."""
    if st is None:
        logger.error("Settings 'st' not available; cannot perform LDAP list")
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
    logger.info(f"Starting MHE LDAP service on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
