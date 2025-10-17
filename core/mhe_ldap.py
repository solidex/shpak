import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI, Body
from fastapi.responses import JSONResponse

try:
    from ldap3 import Server, Connection, ALL
except Exception:  # optional dependency
    Server = None  # type: ignore
    Connection = None  # type: ignore


def setup_logging() -> None:
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    handler = RotatingFileHandler(log_dir / "mhe_ldap.log", maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])


setup_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="MHE LDAP Service")


def ldap_lookup(logins: List[str], server_uri: Optional[str], bind_dn: Optional[str], bind_pw: Optional[str], base_dn: Optional[str]) -> Dict[str, List[str]]:
    """Lookup emails for provided logins.

    If ldap3 is unavailable or configuration is missing, returns an empty mapping.
    """
    result: Dict[str, List[str]] = {login: [] for login in logins}
    if not server_uri or Server is None:
        logger.warning("LDAP not configured or ldap3 missing; returning empty emails")
        return result

    try:
        server = Server(server_uri, get_info=ALL)
        with Connection(server, user=bind_dn, password=bind_pw, auto_bind=True) as conn:
            for login in logins:
                # Common attributes; adjust filter as per directory schema
                search_filter = f"(|(sAMAccountName={login})(uid={login})(mailNickname={login}))"
                conn.search(search_base=base_dn or "", search_filter=search_filter, attributes=["mail"])
                emails: List[str] = []
                for entry in conn.entries:
                    try:
                        mail_attr = entry["mail"]
                        if mail_attr and mail_attr.value:
                            emails.append(str(mail_attr.value))
                    except Exception:
                        continue
                result[login] = emails
        return result
    except Exception as e:
        logger.error(f"LDAP lookup failed: {e}")
        return result


@app.post("/lookup")
def lookup(payload: Dict = Body(...)) -> JSONResponse:
    """Request body: { "logins": ["user1", "user2"], "ldap": {optional overrides} }

    Response: { "users": { "user1": ["a@b"], ... } }
    """
    logins: List[str] = list({str(u).strip() for u in payload.get("logins", []) if str(u).strip()})
    ldap_cfg = payload.get("ldap", {}) or {}
    users = ldap_lookup(
        logins,
        ldap_cfg.get("server"),
        ldap_cfg.get("bind_dn"),
        ldap_cfg.get("bind_pw"),
        ldap_cfg.get("base_dn"),
    )
    return JSONResponse({"users": users})


@app.get("/health")
def health():
    return {"status": "ok", "service": "mhe_ldap"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8086, log_config=None)


