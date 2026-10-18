from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(ROOT / ".env"), extra="ignore")
    falkordb_host: str = "127.0.0.1"
    falkordb_port: int = 6379
    falkordb_password: str = ""
    tenant_tokens: str = "demo:local-demo-token"
    worker_token: str = "local-worker-token"
    llm_base_url: str = ""
    llm_model: str = ""
    llm_api_key: str = ""
    lease_ms: int = 15000
    worker_poll_seconds: float = 0.5
    runtime_dir: Path = ROOT / ".runtime"


settings = Settings()
