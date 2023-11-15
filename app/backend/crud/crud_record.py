# /app/crud/crud_record.py
from app.schemas.record import RecordBase, RecordUpdate
from motor.motor_asyncio import AsyncIOMotorClient

async def create_record(db: AsyncIOMotorClient, record_in: RecordBase):
    collection = db[record_in.conf.get("activity_set")]
    record = await collection.insert_one(record_in.dict())
    return record

async def update_record(db: AsyncIOMotorClient, nmdc_jobid: str, update_data: RecordUpdate):
    collection = db[update_data.activity_set]  # Determine the collection name dynamically
    await collection.update_one({"nmdc_jobid": nmdc_jobid}, {"$set": update_data.dict()})
    return {"nmdc_jobid": nmdc_jobid}

async def patch_record(db: AsyncIOMotorClient, nmdc_jobid: str, update_data: RecordUpdate):
    collection_name = update_data.activity_set  # Assuming the collection name is in the update data
    collection = db[collection_name]
    await collection.update_one({"nmdc_jobid": nmdc_jobid}, {"$set": update_data.dict(exclude_unset=True)})
    return {"nmdc_jobid": nmdc_jobid}


async def get_record_by_nmdc_jobid(db: AsyncIOMotorClient, nmdc_jobid: str, collection_name: str) -> RecordBase:
    collection = db[collection_name]
    record = await collection.find_one({"nmdc_jobid": nmdc_jobid})
    if record:
        return record
    else:
        return None
