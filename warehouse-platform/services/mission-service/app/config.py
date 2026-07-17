from pydantic_settings import BaseSettings
from pydantic import Field

class Settings(BaseSettings):
    DATABASE_URL: str = Field(..., env="DATABASE_URL")
    REDIS_URL: str = Field(..., env="REDIS_URL")
    KAFKA_BOOTSTRAP_SERVERS: str = Field(..., env="KAFKA_BOOTSTRAP_SERVERS")
    TOPOLOGY_SERVICE_URL: str = Field(..., env="TOPOLOGY_SERVICE_URL")
    SERVICE_NAME: str = "mission-service"
    LOG_LEVEL: str = "INFO"
    PORT: int = 8002
    ROBOT_HEARTBEAT_TIMEOUT_SECS: int = 180
    MISSION_LOCK_TTL_SECS: int = 300

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

settings = Settings()
