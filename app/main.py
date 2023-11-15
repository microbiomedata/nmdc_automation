from fastapi import FastAPI
from app.api.endpoints import record

app = FastAPI()

app.include_router(record.router, prefix="/records", tags=["records"])
