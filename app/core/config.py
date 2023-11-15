from pydantic import BaseSettings

class Settings(BaseSettings):
    MONGO_URI: str = "mongodb://localhost:27017/mydatabase"

settings = Settings()
