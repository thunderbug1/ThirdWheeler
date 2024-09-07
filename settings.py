from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
import os

class Settings(BaseSettings):
    # Configuration for environment file and extra settings
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')

    BOT_TOKEN: str = Field(None, env="BOT_TOKEN")

    # PostgreSQL settings
    POSTGRES_USER: str = Field("user", env="POSTGRES_USER")
    POSTGRES_PASSWORD: str = Field("password", env="POSTGRES_PASSWORD")
    POSTGRES_DB: str = Field("thirdwheeler", env="POSTGRES_DB")
    POSTGRES_HOST: str = Field("localhost", env="POSTGRES_HOST")
    POSTGRES_PORT: str = Field("5432", env="POSTGRES_PORT")

    # Logging settings
    loglevel: str = Field("DEBUG", env="LOGLEVEL")
    log_dir: str = Field(os.path.join(os.getenv("HOME", "/home/nonroot"), "logs"))
    log_to_file: bool = Field(False, env="LOG_TO_FILE")

    llm_url: str | None = Field(None, env="LLM_URL")
    llm_model: str = Field(default="gpt-4o-mini", env="LLM_MODEL")
    use_openai_llm: bool = Field(True, env="USE_OPENAI_LLM")
    openai_api_key: str = Field(None, env="OPENAI_API_KEY")

# Usage
settings = Settings()

# # Access the settings
# Access the settings
# print(settings.DATABASE_URL)
# print(settings.loglevel)
