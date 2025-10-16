from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

class RadiusEvent(BaseModel):
    attrs: dict

class FirewallProfileIn(BaseModel):
    id: Optional[int] = None
    profile_type: str
    can_delete: int
    profile_name: Optional[str] = None
    created_at: str
    updated_at: str
    name: str
    login: str
    ip_pool: Optional[str] = None
    ip_v6_pool: Optional[str] = None
    region_id: str
    tcp_rules: str
    udp_rules: str
    firewall_profile: Optional[str] = None

class ListResponse(BaseModel):
    success: bool
    data: List[Dict[str, Any]] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 25
    error: Optional[str] = None
    comment: Optional[str] = None

class ItemResponse(BaseModel):
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    comment: Optional[str] = None

class SimpleResponse(BaseModel):
    success: bool
    error: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    comment: Optional[str] = None 