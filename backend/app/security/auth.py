import hmac
from fastapi import Depends, Header, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from app.core.config import settings
from app.memory.manager import AgentMemoryManager

bearer = HTTPBearer(auto_error=False)


def tenants():
    return dict(item.split(":", 1) for item in settings.tenant_tokens.split(",") if ":" in item)


def memory(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    if credentials:
        for tenant, token in tenants().items():
            if hmac.compare_digest(credentials.credentials, token):
                return AgentMemoryManager(tenant)
    raise HTTPException(401, "Valid tenant bearer token required")


def require_worker(x_worker_token: str = Header(default="")):
    if not hmac.compare_digest(x_worker_token, settings.worker_token):
        raise HTTPException(403, "Worker credential required in addition to tenant token")
