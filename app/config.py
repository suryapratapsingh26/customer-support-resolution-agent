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

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )


settings = Settings()
