from pydantic import BaseModel

class CreateIPRequest(BaseModel):
    fg_addr: str
    name: str
    ip: str

class CreateIPv6Request(BaseModel):
    fg_addr: str
    name: str
    ipv6: str

class CreateServiceRequest(BaseModel):
    fg_addr: str
    name: str
    tcp: str
    udp: str

class CreatePolicyRequest(BaseModel):
    fg_addr: str
    name: str
    username: str

class DeleteObjectRequest(BaseModel):
    fg_addr: str
    name: str

class DeletePolicyRequest(BaseModel):
    fg_addr: str
    policy_id: str

class MovePolicyRequest(BaseModel):
    fg_addr: str
    policy_id: str

class GetPolicyRequest(BaseModel):
    fg_addr: str
    policy_id: str

class EditPolicyRequest(BaseModel):
    fg_addr: str
    action: str
    policy_id: str
    extra: dict = {} 