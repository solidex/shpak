from pydantic import BaseModel
from typing import List, Optional, Any
from fastapi.responses import JSONResponse
import orjson

class PrettyJSONResponse(JSONResponse):
    def render(self, content: Any) -> bytes:
        return orjson.dumps(
            content,
            option=orjson.OPT_INDENT_2,
        )

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
    """Helper class for pagination logic (works with list of dicts)"""
    def __init__(self, items: List[dict], page_size: int = 25):
        self.items = items
        self.page_size = page_size
    
    def paginate(self, page_number: int = 1) -> PaginatedResponse:
        total_items = len(self.items)
        num_pages = -(-total_items // self.page_size)  # Ceiling division
        start_idx = (page_number - 1) * self.page_size
        end_idx = start_idx + self.page_size
        paginated_items = self.items[start_idx:end_idx]
        return PaginatedResponse(
            count=total_items,
            next=self._get_next_url(page_number, num_pages),
            previous=self._get_previous_url(page_number),
            current_page=page_number,
            num_pages=num_pages,
            page_size=self.page_size,
            results=paginated_items
        )
    def _get_next_url(self, current_page: int, total_pages: int) -> Optional[str]:
        if current_page < total_pages:
            return f"/api/firewall_profile_rules?page={current_page + 1}"
        return None
    def _get_previous_url(self, current_page: int) -> Optional[str]:
        if current_page > 1:
            return f"/api/firewall_profile_rules?page={current_page - 1}"
        return None
