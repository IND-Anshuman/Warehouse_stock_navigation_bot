from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from app.database import get_db
from app.repositories.topology_repo import TopologyRepository
from app.cache.topology_cache import TopologyCache
from app.config import settings
from app.schemas.topology import (
    WarehouseCreate, WarehouseResponse, WarehouseDetail,
    ZoneCreate, ZoneResponse,
    AisleCreate, AisleResponse,
    RackCreate, RackResponse,
    ShelfCreate, ShelfResponse,
    BinCreate, BinResponse, BinDetail
)

router = APIRouter()
cache = TopologyCache(settings.REDIS_URL)

@router.get("/warehouses", response_model=List[WarehouseResponse])
async def list_warehouses(skip: int = 0, limit: int = 10, db: AsyncSession = Depends(get_db)):
    repo = TopologyRepository(db)
    return await repo.get_warehouses(skip, limit)

@router.post("/warehouses", response_model=WarehouseResponse, status_code=status.HTTP_201_CREATED)
async def create_warehouse(data: WarehouseCreate, db: AsyncSession = Depends(get_db)):
    repo = TopologyRepository(db)
    return await repo.create_warehouse(data)

@router.get("/warehouses/{warehouse_id}", response_model=WarehouseResponse)
async def get_warehouse(warehouse_id: str, db: AsyncSession = Depends(get_db)):
    repo = TopologyRepository(db)
    wh = await repo.get_warehouse_by_id(warehouse_id)
    if not wh:
        raise HTTPException(status_code=404, detail="Warehouse not found")
    return wh

@router.get("/warehouses/{warehouse_id}/topology", response_model=WarehouseDetail)
async def get_topology(warehouse_id: str, db: AsyncSession = Depends(get_db)):
    # Check cache first
    cached = await cache.get_cached_topology(warehouse_id)
    if cached:
        return cached

    repo = TopologyRepository(db)
    wh = await repo.get_topology(warehouse_id)
    if not wh:
        raise HTTPException(status_code=404, detail="Warehouse topology not found")
    
    # Simple serialization for demo/pydantic compatibility
    from fastapi.encoders import jsonable_encoder
    topo_dict = jsonable_encoder(wh)
    await cache.cache_topology(warehouse_id, topo_dict)
    return wh

@router.post("/warehouses/{warehouse_id}/zones", response_model=ZoneResponse)
async def create_zone(warehouse_id: str, data: ZoneBase, db: AsyncSession = Depends(get_db)):
    repo = TopologyRepository(db)
    # Wrap base schema to create schema
    create_data = ZoneCreate(warehouse_id=warehouse_id, **data.model_dump())
    return await repo.create_zone(create_data)

@router.get("/bins/{bin_id}", response_model=BinDetail)
async def get_bin(bin_id: str, db: AsyncSession = Depends(get_db)):
    repo = TopologyRepository(db)
    b = await repo.get_bin_by_id(bin_id)
    if not b:
        raise HTTPException(status_code=404, detail="Bin not found")
    return b

@router.get("/warehouses/{warehouse_id}/bins/resolve", response_model=BinResponse)
async def resolve_bin(warehouse_id: str, x: float, y: float, z: float, db: AsyncSession = Depends(get_db)):
    repo = TopologyRepository(db)
    b = await repo.resolve_bin_from_coords(warehouse_id, x, y, z)
    if not b:
        raise HTTPException(status_code=404, detail="No matching bin found within proximity")
    return b

@router.post("/warehouses/{warehouse_id}/seed-demo")
async def seed_demo(warehouse_id: str, db: AsyncSession = Depends(get_db)):
    repo = TopologyRepository(db)
    await repo.seed_demo_warehouse(warehouse_id)
    await cache.invalidate_topology(warehouse_id)
    return {"status": "success", "message": "Demo data populated"}
