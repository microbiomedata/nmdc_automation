from motor.motor_asyncio import AsyncIOMotorClient
from app.core.config import settings

async def get_db() -> AsyncIOMotorClient:
    client = AsyncIOMotorClient(settings.MONGO_URI)
    return client.get_default_database()
