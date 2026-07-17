from pydantic_settings import BaseSettings
from pydantic import Field

class Config(BaseSettings):
    OBSERVATION_SERVICE_URL: str = Field("http://localhost:8003", env="OBSERVATION_SERVICE_URL")
    MISSION_SERVICE_URL: str = Field("http://localhost:8002", env="MISSION_SERVICE_URL")
    TOPOLOGY_SERVICE_URL: str = Field("http://localhost:8001", env="TOPOLOGY_SERVICE_URL")
    
    ROBOT_COUNT: int = Field(3, env="ROBOT_COUNT")
    WAREHOUSE_ID: str = Field("a1b2c3d4-e5f6-7890-abcd-ef1234567890", env="WAREHOUSE_ID")
    LOG_LEVEL: str = "INFO"
    
    SCAN_INTERVAL_MS: int = 2000
    HEARTBEAT_INTERVAL_MS: int = 1000
    BATTERY_DRAIN_RATE: float = 0.02
    
    CONNECTIVITY_FAILURE_PROBABILITY: float = 0.05
    DECODE_FAILURE_PROBABILITY: float = 0.08

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

config = Config()
