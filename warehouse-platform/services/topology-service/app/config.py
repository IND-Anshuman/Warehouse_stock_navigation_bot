from pydantic_settings import BaseSettings
from pydantic import Field

class Settings(BaseSettings):
    DATABASE_URL: str = Field(..., env="DATABASE_URL")
    REDIS_URL: str = Field(..., env="REDIS_URL")
    KAFKA_BOOTSTRAP_SERVERS: str = Field(..., env="KAFKA_BOOTSTRAP_SERVERS")
    SERVICE_NAME: str = "topology-service"
    LOG_LEVEL: str = "INFO"
    PORT: int = 8001
    SECRET_KEY: str = "dev-secret-key-change-in-prod"
    REDIS_TOPOLOGY_TTL_SECONDS: int = 86400

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

settings = Settings()
