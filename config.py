from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    BOT_TOKEN: str
    WEBAPP_URL: str = ""
    ADMIN_IDS: List[int] = []
    OWNER_CHAT_ID: int = 0

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
