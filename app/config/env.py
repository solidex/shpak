import os
from typing import Dict, Any
from dotenv import load_dotenv


# Load environment variables from .env if present
load_dotenv()


def _get(name: str, default: Any = None, cast=None):
    val = os.getenv(name, default)
    if cast and val is not None:
        try:
            return cast(val)
        except Exception:
            return default
    return val


class _Settings:
    # API token
    API_TOKEN: str = _get("API_TOKEN", "1234567890")
    # Email token (separate secret used to sign report links)
    EMAIL_TOKEN: str = _get("EMAIL_TOKEN", "email-secret")

    # StarRocks settings (primary analytical store)
    # StarRocks speaks MySQL protocol, so we use the same connector interface
    starrocks_config: Dict[str, Any] = {
        'user': _get('STARROCKS_USER', 'root'),
        'password': _get('STARROCKS_PASSWORD', ''),
        'host': _get('STARROCKS_HOST', '127.0.0.1'),
        'database': _get('STARROCKS_DB', 'RADIUS'),
        'port': _get('STARROCKS_PORT', 9030, int),
    }

    # MySQL settings (legacy, not used when StarRocks is enabled)
    mysql_config: Dict[str, Any] = {
        'user': _get('MYSQL_USER', 'root'),
        'password': _get('MYSQL_PASSWORD', ''),
        'host': _get('MYSQL_HOST', '127.0.0.1'),
        'database': _get('MYSQL_DB', 'RADIUS'),
        'port': _get('MYSQL_PORT', '3306'),
        'use_pure': _get('MYSQL_USE_PURE', 'True'),
    }

    # Default FortiGate policy payload (data section) aligned with current API usage
    default_policy: Dict[str, Any] = {
        "action": _get("DEFAULT_POLICY_ACTION", "deny"),
        "srcintf": [{"name": _get("DEFAULT_POLICY_SRCINTF", "PPPoE_vlan")}],
        "dstintf": [{"name": _get("DEFAULT_POLICY_DSTINTF", "Core_vlan")}],
        "dstaddr": [
            {"name": _get("DEFAULT_POLICY_DSTADDR1", "ns3.belpak.by_ipv4")},
            {"name": _get("DEFAULT_POLICY_DSTADDR2", "ns4.belpak.by_ipv4")},
        ],
        "dstaddr6": [
            {"name": _get("DEFAULT_POLICY_DSTADDR6_1", "ns3.belpak.by_ipv6")},
            {"name": _get("DEFAULT_POLICY_DSTADDR6_2", "ns4.belpak.by_ipv6")},
        ],
        "schedule": _get("DEFAULT_POLICY_SCHEDULE", "always"),
        "ssl-ssh-profile": _get("DEFAULT_POLICY_SSL_SSH_PROFILE", ""),
        "logtraffic": _get("DEFAULT_POLICY_LOGTRAFFIC", "disable"),
        "groups": [{"name": _get("DEFAULT_POLICY_GROUP", "class2")}],
        "dstaddr-negate": _get("DEFAULT_POLICY_DSTADDR_NEGATE", "enable"),
        "dstaddr6-negate": _get("DEFAULT_POLICY_DSTADDR6_NEGATE", "enable"),
    }

    # RADIUS
    RADIUS_SERVER_IP = [s.strip() for s in _get("RADIUS_SERVER_IP", "").split(",") if s.strip()]
    RADIUS_SHARED_SECRET = _get("RADIUS_SHARED_SECRET", "testing123").encode()

    # Mapping NAS-IP -> list of FortiGate addresses (with fallback support)
    def _parse_forti_gate(self) -> Dict[str, list]:
        """Build NAS_IP -> [FG_IPs...] mapping from .env.

        Supports two formats (multi-line preferred):
        1) Multi-line indexed (supports multiple NAS-IPs per group):
           FORTI_GATE_1_NAS=172.26.202.244,172.26.202.245
           FORTI_GATE_1_FGS=10.3.1.101,10.3.1.102
           Each NAS-IP from the list will map to the same FG-IP list.

        2) Legacy single-line:
           FORTI_GATE="nas1=fg1;fg2|nas2=fg3"
        """
        mapping: Dict[str, list] = {}

        # Prefer multi-line indexed variables
        indices: set[str] = set()
        for key in os.environ.keys():
            if key.startswith("FORTI_GATE_") and key.endswith("_NAS"):
                idx = key[len("FORTI_GATE_"):-len("_NAS")]
                if idx:
                    indices.add(idx)

        for idx in sorted(indices):
            nas_raw = _get(f"FORTI_GATE_{idx}_NAS", "")
            fgs_raw = _get(f"FORTI_GATE_{idx}_FGS", "")
            
            # Parse multiple NAS-IPs and FG-IPs from comma-separated lists
            nas_list = [nas.strip() for nas in nas_raw.split(',') if nas.strip()]
            fg_list = [fg.strip() for fg in fgs_raw.split(',') if fg.strip()]
            
            # Map each NAS-IP to the same list of FG-IPs
            if nas_list and fg_list:
                for nas_ip in nas_list:
                    mapping[nas_ip] = fg_list

        if mapping:
            return mapping

        # Fallback to legacy single-line format
        raw = _get("FORTI_GATE", "")
        if not raw:
            return mapping
        for pair in raw.split("|"):
            if not pair:
                continue
            nas, _, fgs = pair.partition("=")
            nas_ip = nas.strip()
            fg_list = [fg.strip() for fg in fgs.split(';') if fg.strip()]
            if nas_ip and fg_list:
                mapping[nas_ip] = fg_list
        return mapping

    FORTI_GATE: Dict[str, list] = property(lambda self: self._parse_forti_gate())

    # Service hosts/ports
    MHE_DB_HOST = _get("MHE_DB_HOST", "127.0.0.1")
    MHE_DB_PORT = _get("MHE_DB_PORT", 80, int)

    # MHE_AE (Application Engine) replaces OPLOGIC
    MHE_AE_HOST = _get("MHE_AE_HOST", "127.0.0.1")
    MHE_AE_PORT = _get("MHE_AE_PORT", 80, int)

    MHE_APP_HOST = _get("MHE_APP_HOST", "127.0.0.1")
    MHE_APP_PORT = _get("MHE_APP_PORT", 80, int)

    MHE_FORTIAPI_HOST = _get("MHE_FORTIAPI_HOST", "127.0.0.1")
    MHE_FORTIAPI_PORT = _get("MHE_FORTIAPI_PORT", 80, int)

    MHE_LDAP_HOST = _get("MHE_LDAP_HOST", "127.0.0.1")
    MHE_LDAP_PORT = _get("MHE_LDAP_PORT", 80, int)

    MHE_EMAIL_HOST = _get("MHE_EMAIL_HOST", "127.0.0.1")
    MHE_EMAIL_PORT = _get("MHE_EMAIL_PORT", 80, int)

    GUI_HOST = _get("GUI_HOST", "127.0.0.1")
    GUI_PORT = _get("GUI_PORT", 80, int)

    # SMTP settings
    SMTP_HOST = _get("SMTP_HOST", "localhost")
    SMTP_PORT = _get("SMTP_PORT", 587, int)
    SMTP_USER = _get("SMTP_USER", "")
    SMTP_PASSWORD = _get("SMTP_PASSWORD", "")
    SMTP_USE_TLS = _get("SMTP_USE_TLS", "True").lower() in ("true", "1", "yes")
    SMTP_FROM = _get("SMTP_FROM", "noreply@example.com")
    SMTP_USE_SSL = _get("SMTP_USE_SSL", "False").lower() in ("true", "1", "yes")
    SMTP_TIMEOUT = _get("SMTP_TIMEOUT", 10, int)
    
    # LDAP settings for mhe_ldap/mhe_email integration
    LDAP_URI = _get("LDAP_URI", "ldap://127.0.0.1:389")
    LDAP_BIND_DN = _get("LDAP_BIND_DN", "")
    LDAP_BIND_PASSWORD = _get("LDAP_BIND_PASSWORD", "")
    LDAP_BASE_DN = _get("LDAP_BASE_DN", "")
    LDAP_START_TLS = _get("LDAP_START_TLS", "false")
    
    # Email report schedule (HH:MM format, 24-hour)
    REPORT_SEND_TIME = _get("REPORT_SEND_TIME", "09:00")

# Export a singleton compatible with previous `start_settings as st`
st = _Settings()