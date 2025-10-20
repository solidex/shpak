from pydantic import BaseModel
from typing import List, Optional, Any
from fastapi.responses import JSONResponse
import orjson

class PrettyJSONResponse(JSONResponse):
    def render(self, content: Any) -> bytes:
        return orjson.dumps(content, option=orjson.OPT_INDENT_2)

class CreateProfileRequest(BaseModel):
    name: str
    login: str
    tcp_rules: str
    udp_rules: str
    firewall_profile: Optional[str] = None
    ip_pool: Optional[str] = None
    ip_v6_pool: Optional[str] = None
    region_id: Optional[str] = None
    comment: Optional[str] = None
    error: Optional[str] = None

class UpdateProfileRequest(BaseModel):
    name: str
    login: str
    tcp_rules: str
    udp_rules: str
    firewall_profile: Optional[str]
    comment: Optional[str] = None
    error: Optional[str] = None

class PaginatedResponse(BaseModel):
    count: int
    next: Optional[str]
    previous: Optional[str]
    current_page: int
    num_pages: int
    page_size: int
    results: List[dict]

class FirewallProfilePagination:
    """Simple pagination logic for a list of dicts."""
    def __init__(self, items: List[dict], page_size: int = 25):
        self.items = items
        self.page_size = page_size

    def paginate(self, page: int = 1) -> PaginatedResponse:
        total = len(self.items)
        num_pages = (total + self.page_size - 1) // self.page_size
        start = (page - 1) * self.page_size
        end = start + self.page_size
        return PaginatedResponse(
            count=total,
            next=f"/api/firewall_profile_rules?page={page+1}" if page < num_pages else None,
            previous=f"/api/firewall_profile_rules?page={page-1}" if page > 1 else None,
            current_page=page,
            num_pages=num_pages,
            page_size=self.page_size,
            results=self.items[start:end]
        )
