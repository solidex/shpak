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

    # MySQL settings (legacy block left for compatibility)
    mysql_config: Dict[str, Any] = {
        'user': _get('MYSQL_USER', 'root'),
        'password': _get('MYSQL_PASSWORD', ''),
        'host': _get('MYSQL_HOST', '127.0.0.1'),
        'database': _get('MYSQL_DB', 'Radius'),
        'port': _get('MYSQL_PORT', '3306'),
        'use_pure': _get('MYSQL_USE_PURE', 'True'),
    }

    # Default policy JSON fields (string values expected by FortiGate)
    default_policy: Dict[str, Any] = {
        "srcintf": _get("DEFAULT_POLICY_SRCINTF", "PPoE"),
        "dstintf": _get("DEFAULT_POLICY_DSTINTF", "Ethernet"),
        "dstaddr": _get("DEFAULT_POLICY_DSTADDR", "all"),
        "dstaddr6": _get("DEFAULT_POLICY_DSTADDR6", "all"),
        "schedule": _get("DEFAULT_POLICY_SCHEDULE", "always"),
        "utm-status": _get("DEFAULT_POLICY_UTM_STATUS", "enable"),
        "av-profile": _get("DEFAULT_POLICY_AV_PROFILE", "g-default"),
        "ips-sensor": _get("DEFAULT_POLICY_IPS_SENSOR", "g-default"),
        "dns-filter-profile": _get("DEFAULT_POLICY_DNS_FILTER_PROFILE", "dns_custom"),
        "ssl-ssh-profile": _get("DEFAULT_POLICY_SSL_SSH_PROFILE", "no-inspection"),
        "nat": _get("DEFAULT_POLICY_NAT", "disable"),
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

    GUI_HOST = _get("GUI_HOST", "127.0.0.1")
    GUI_PORT = _get("GUI_PORT", 80, int)

    LOGGING_SERVICE_HOST = _get("LOGGING_SERVICE_HOST", "127.0.0.1")
    LOGGING_SERVICE_PORT = _get("LOGGING_SERVICE_PORT", 80, int)

# Export a singleton compatible with previous `start_settings as st`
st = _Settings()


