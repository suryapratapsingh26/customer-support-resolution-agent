from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Customer Support Resolution Agent"
    environment: str = "development"
    database_url: str
    knowledge_base_dir: str = "knowledge_base"
    chroma_persist_dir: str = ".data/chroma"
    chroma_collection_name: str = "support_knowledge"
    embedding_model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_device: str = "cpu"
    knowledge_chunk_size: int = 900
    knowledge_chunk_overlap: int = 120
    knowledge_top_k: int = 5
    knowledge_context_max_chars: int = 12000
    llm_api_key: str | None = None
    llm_model: str = "gpt-4o-mini"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_timeout_seconds: float = 30.0
    approval_api_key: str | None = None
    approval_actor_id: str | None = None
    approval_request_api_key: str | None = None
    approval_request_actor_id: str | None = None
    agent_api_key: str | None = None
    agent_customer_token_secret: str | None = None
    oidc_issuer: str | None = None
    oidc_audience: str | None = None
    oidc_client_id: str | None = None
    oidc_client_secret: str | None = None
    oidc_redirect_uri: str | None = None
    oidc_jwks_url: str | None = None
    oidc_allowed_algorithms: list[str] = Field(default_factory=lambda: ["RS256"])
    oidc_roles_claim: str = "roles"
    oidc_customer_ids_claim: str = "customer_ids"
    oidc_reviewer_role: str = "support_reviewer"
    oidc_agent_role: str = "support_agent"
    bff_session_cookie_name: str = "support_session"
    bff_session_ttl_seconds: int = 28800
    bff_session_cookie_secure: bool = True
    bff_trusted_origins: list[str] = Field(default_factory=list)
    backend_service_api_key: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )


settings = Settings()
