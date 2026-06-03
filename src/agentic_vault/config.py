from pathlib import Path
from typing import ClassVar

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_file=".env", extra="ignore"
    )

    openai_api_key: SecretStr

    langfuse_public_key: str
    langfuse_secret_key: str
    langfuse_base_url: str

    redis_url: str

    vault_corpus_path: Path
    chunk_size: int = 1000
    chunk_overlap: int = 200

    # Self-signed JWT signing secret (Stage 5). Generate with: openssl rand -hex 32
    jwt_secret: SecretStr
    # Login password checked by /login, which then issues the JWT (Stage 5).
    app_password: SecretStr


settings = Settings()  # pyright: ignore[reportCallIssue]
