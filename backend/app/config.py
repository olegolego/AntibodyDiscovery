from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    secret_key: str = "change-me"

    database_url: str = "sqlite+aiosqlite:///./protein_design.db"  # resolved to absolute in db/session.py

    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    storage_backend: str = "local"
    local_artifact_dir: str = "./artifacts"

    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_region: str = "us-east-1"
    s3_artifact_bucket: str = ""

    gcs_artifact_bucket: str = ""

    alphafold_url: str = "http://localhost:8001"
    rfdiffusion_url: str = "http://localhost:8002"
    proteinmpnn_url: str = "http://localhost:8003"
    esmfold_url: str = "http://localhost:8004"
    abmap_url: str = "http://localhost:8005"


settings = Settings()
