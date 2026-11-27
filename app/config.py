from urllib.parse import urlsplit

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
    oidc_backchannel_base_url: str | None = None
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
        # Compose keeps database bootstrap credentials beside app settings.
        # They are consumed by containers, not by this application model.
        extra="ignore",
    )

    def validate_runtime(self) -> None:
        """Fail closed for deployment configurations that would weaken security."""
        if self.environment.strip().lower() == "development":
            return

        errors: list[str] = []
        database = urlsplit(self.database_url)
        if database.scheme != "postgresql+psycopg" or not database.hostname:
            errors.append("DATABASE_URL must use the psycopg PostgreSQL driver and include a host")

        required = {
            "OIDC_ISSUER": self.oidc_issuer,
            "OIDC_AUDIENCE": self.oidc_audience,
            "OIDC_CLIENT_ID": self.oidc_client_id,
            "OIDC_CLIENT_SECRET": self.oidc_client_secret,
            "OIDC_REDIRECT_URI": self.oidc_redirect_uri,
            "BACKEND_SERVICE_API_KEY": self.backend_service_api_key,
            "AGENT_API_KEY": self.agent_api_key,
            "AGENT_CUSTOMER_TOKEN_SECRET": self.agent_customer_token_secret,
            "APPROVAL_API_KEY": self.approval_api_key,
            "APPROVAL_REQUEST_API_KEY": self.approval_request_api_key,
            "APPROVAL_ACTOR_ID": self.approval_actor_id,
            "APPROVAL_REQUEST_ACTOR_ID": self.approval_request_actor_id,
            "LLM_API_KEY": self.llm_api_key,
        }
        errors.extend(f"{name} is required" for name, value in required.items() if not value or not value.strip())
        for name, value in required.items():
            if name.endswith("_API_KEY") or name.endswith("_SECRET"):
                if value and len(value.strip()) < 32:
                    errors.append(f"{name} must contain at least 32 characters")

        issuer = urlsplit(self.oidc_issuer or "")
        callback = urlsplit(self.oidc_redirect_uri or "")
        if issuer.scheme != "https" or not issuer.hostname:
            errors.append("OIDC_ISSUER must be an HTTPS URL")
        if (callback.scheme != "https" or not callback.hostname
                or callback.path != "/api/bff/auth/callback"):
            errors.append("OIDC_REDIRECT_URI must be an HTTPS BFF callback URL")
        if self.oidc_backchannel_base_url:
            backchannel = urlsplit(self.oidc_backchannel_base_url)
            if (backchannel.scheme != "https" or not backchannel.hostname
                    or backchannel.username or backchannel.password
                    or backchannel.path not in {"", "/"} or backchannel.query or backchannel.fragment):
                errors.append("OIDC_BACKCHANNEL_BASE_URL must use HTTPS outside development")
        asymmetric_oidc_algorithms = {
            "RS256", "RS384", "RS512", "PS256", "PS384", "PS512",
            "ES256", "ES384", "ES512", "EdDSA",
        }
        if (not self.oidc_allowed_algorithms
                or any(algorithm not in asymmetric_oidc_algorithms for algorithm in self.oidc_allowed_algorithms)):
            errors.append("OIDC_ALLOWED_ALGORITHMS must use supported asymmetric signing algorithms")
        if not self.oidc_roles_claim.strip() or not self.oidc_customer_ids_claim.strip():
            errors.append("OIDC role and customer identity claim names are required")
        if not self.oidc_agent_role.strip() or not self.oidc_reviewer_role.strip() or self.oidc_agent_role == self.oidc_reviewer_role:
            errors.append("OIDC agent and reviewer roles must be distinct")
        if not self.bff_session_cookie_secure:
            errors.append("BFF_SESSION_COOKIE_SECURE must be true outside development")
        if self.bff_session_ttl_seconds <= 0:
            errors.append("BFF_SESSION_TTL_SECONDS must be positive")
        if not self.bff_trusted_origins:
            errors.append("BFF_TRUSTED_ORIGINS must contain at least one HTTPS origin")
        for origin in self.bff_trusted_origins:
            parsed = urlsplit(origin)
            if parsed.scheme != "https" or not parsed.hostname or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
                errors.append("BFF_TRUSTED_ORIGINS must contain only HTTPS origins")
                break

        request_key = self.approval_request_api_key or ""
        reviewer_key = self.approval_api_key or ""
        if request_key and reviewer_key and request_key == reviewer_key:
            errors.append("Approval request and reviewer credentials must differ")
        if (self.approval_actor_id and self.approval_request_actor_id
                and self.approval_actor_id.strip() == self.approval_request_actor_id.strip()):
            errors.append("Approval requester and reviewer identities must differ")
        service_secrets = [value.strip() for name, value in required.items()
                           if (name.endswith("_API_KEY") or name.endswith("_SECRET"))
                           and value and value.strip()]
        if len(set(service_secrets)) != len(service_secrets):
            errors.append("Server-side service credentials and signing secrets must be distinct")
        llm_url = urlsplit(self.llm_base_url)
        if llm_url.scheme != "https" or not llm_url.hostname:
            errors.append("LLM_BASE_URL must be an HTTPS URL")
        if errors:
            raise ValueError("Invalid production configuration: " + "; ".join(errors))


settings = Settings()
