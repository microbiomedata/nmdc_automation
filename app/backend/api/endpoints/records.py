from fastapi import APIRouter, HTTPException, Body, Depends
from typing import List
from app import crud, schemas
from app.api import dependencies

router = APIRouter()

@router.post("/", response_model=schemas.record.RecordCreate)
async def create_record(record_in: schemas.RecordCreate, db: Depends(dependencies.get_db)):
    return await crud.crud_record.create_record(db, record_in)

@router.patch("/{nmdc_jobid}", response_model=schemas.record.RecordUpdate)
async def update_record(nmdc_jobid: str, update_data: schemas.RecordUpdate, db: Depends(dependencies.get_db)):
    return await crud.crud_record.update_record(db, nmdc_jobid, update_data)

@router.delete("/{nmdc_jobid}")
async def delete_record(nmdc_jobid: str, collection_name: str, db: Depends(dependencies.get_db)):
    result = await crud.crud_record.delete_record(db, nmdc_jobid, collection_name)
    if not result:
        raise HTTPException(status_code=404, detail="Record not found")
    return {"message": "Record deleted successfully"}

@router.get("/{nmdc_jobid}", response_model=schemas.record.RecordBase)
async def get_record(nmdc_jobid: str, collection_name: str, db=Depends(dependencies.get_db)):
    record = await crud.crud_record.get_record_by_nmdc_jobid(db, nmdc_jobid, collection_name)
    if not record:
        raise HTTPException(status_code=404, detail="Record not found")
    return record