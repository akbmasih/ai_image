# /ai/config.py
# Configuration management for AI server environment variables and settings

import os
from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    # Database Configuration
    database_url: str = "postgresql://ai_user:ai_password@localhost:5432/ai_db"
    
    # MinIO Configuration
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin123"
    minio_secure: bool = False
    
    # JWT Configuration
    jwt_secret_key: str = "your_jwt_secret_key_here"
    jwt_algorithm: str = "RS256"
    
    # AI Model API Keys
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    deepseek_api_key: Optional[str] = None
    
    # External AI Service URLs
    flux_api_url: str = "http://213.192.2.72:8080"
    chatterbox_api_url: str = "http://213.192.2.72:8080"
    
    # Rate Limiting Configuration
    rate_limit_per_minute: int = 50
    plugin_rate_limit_per_minute: int = 20
    
    # Cache Configuration
    cache_enabled: bool = True
    force_refresh_header: str = "X-Force-Refresh"
    
    # Logging Configuration
    log_level: str = "INFO"
    log_rotation_days: int = 60
    
    # CORS Configuration
    cors_origins: list = ["*"]
    
    class Config:
        env_file = ".env"
        case_sensitive = False

# Global settings instance
settings = Settings()