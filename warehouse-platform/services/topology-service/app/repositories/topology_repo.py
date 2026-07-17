from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from app.models.topology import Warehouse, Zone, Aisle, Rack, Shelf, Bin
from app.schemas.topology import WarehouseCreate, ZoneCreate, AisleCreate, RackCreate, ShelfCreate, BinCreate
from decimal import Decimal
import math

class TopologyRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_warehouses(self, skip: int = 0, limit: int = 10):
        result = await self.session.execute(
            select(Warehouse).offset(skip).limit(limit)
        )
        return result.scalars().all()

    async def get_warehouse_by_id(self, warehouse_id: str):
        result = await self.session.execute(
            select(Warehouse).filter(Warehouse.id == warehouse_id)
        )
        return result.scalar_one_or_none()

    async def create_warehouse(self, data: WarehouseCreate) -> Warehouse:
        warehouse = Warehouse(**data.model_dump())
        self.session.add(warehouse)
        await self.session.commit()
        await self.session.refresh(warehouse)
        return warehouse

    async def get_topology(self, warehouse_id: str) -> Optional[Warehouse]:
        result = await self.session.execute(
            select(Warehouse)
            .filter(Warehouse.id == warehouse_id)
            .options(
                selectinload(Warehouse.zones)
                .selectinload(Zone.aisles)
                .selectinload(Aisle.racks)
                .selectinload(Rack.shelves)
                .selectinload(Shelf.bins)
            )
        )
        return result.scalar_one_or_none()

    async def create_zone(self, data: ZoneCreate) -> Zone:
        zone = Zone(**data.model_dump())
        self.session.add(zone)
        await self.session.commit()
        await self.session.refresh(zone)
        return zone

    async def create_aisle(self, data: AisleCreate) -> Aisle:
        aisle = Aisle(**data.model_dump())
        self.session.add(aisle)
        await self.session.commit()
        await self.session.refresh(aisle)
        return aisle

    async def create_rack(self, data: RackCreate) -> Rack:
        rack = Rack(**data.model_dump())
        self.session.add(rack)
        await self.session.commit()
        await self.session.refresh(rack)
        return rack

    async def create_shelf(self, data: ShelfCreate) -> Shelf:
        shelf = Shelf(**data.model_dump())
        self.session.add(shelf)
        await self.session.commit()
        await self.session.refresh(shelf)
        return shelf

    async def create_bin(self, data: BinCreate) -> Bin:
        bin_obj = Bin(**data.model_dump())
        self.session.add(bin_obj)
        await self.session.commit()
        await self.session.refresh(bin_obj)
        return bin_obj

    async def get_bin_by_id(self, bin_id: str) -> Optional[Bin]:
        result = await self.session.execute(
            select(Bin).filter(Bin.id == bin_id)
        )
        return result.scalar_one_or_none()

    async def get_bin_by_code(self, code: str) -> Optional[Bin]:
        result = await self.session.execute(
            select(Bin).filter(Bin.code == code)
        )
        return result.scalar_one_or_none()

    async def resolve_bin_from_coords(self, warehouse_id: str, x: float, y: float, z: float) -> Optional[Bin]:
        """Nearest bin lookup based on Euclidean distance metric."""
        result = await self.session.execute(
            select(Bin)
            .join(Shelf).join(Rack).join(Aisle).join(Zone)
            .filter(Zone.warehouse_id == warehouse_id)
        )
        bins = result.scalars().all()
        if not bins:
            return None

        best_bin = None
        min_dist = float('inf')

        for b in bins:
            if b.coord_x is None or b.coord_y is None or b.coord_z is None:
                continue
            dx = float(b.coord_x) - x
            dy = float(b.coord_y) - y
            dz = float(b.coord_z) - z
            dist = math.sqrt(dx*dx + dy*dy + dz*dz)
            if dist < min_dist:
                min_dist = dist
                best_bin = b
        
        # Only resolve if it's within a 2-meter physical boundary box
        if min_dist <= 2.0:
            return best_bin
        return None

    async def seed_demo_warehouse(self, warehouse_id: str):
        """Seed a clean topology mapping for testing."""
        # Check if zones exist, if not create
        zone_data = ZoneCreate(
            warehouse_id=warehouse_id,
            code="Z1",
            name="Main Storage Zone",
            zone_type="STORAGE",
            floor_level=0
        )
        zone = await self.create_zone(zone_data)
        
        for a_idx in range(1, 4):
            aisle = await self.create_aisle(AisleCreate(
                zone_id=zone.id,
                code=f"A{a_idx}",
                aisle_number=a_idx,
                start_coord_x=Decimal(a_idx * 4),
                start_coord_y=Decimal(0),
                end_coord_x=Decimal(a_idx * 4),
                end_coord_y=Decimal(20)
            ))
            
            for r_idx in range(1, 5):
                rack = await self.create_rack(RackCreate(
                    aisle_id=aisle.id,
                    code=f"A{a_idx}-R{r_idx}",
                    rack_number=r_idx,
                    coord_x=Decimal(a_idx * 4 + (0.5 if r_idx % 2 == 0 else -0.5)),
                    coord_y=Decimal(r_idx * 4)
                ))
                
                for s_idx in range(1, 4):
                    shelf = await self.create_shelf(ShelfCreate(
                        rack_id=rack.id,
                        code=f"A{a_idx}-R{r_idx}-S{s_idx}",
                        level_number=s_idx,
                        height_from_floor_cm=Decimal(s_idx * 100)
                    ))
                    
                    for b_idx in range(1, 3):
                        await self.create_bin(BinCreate(
                            shelf_id=shelf.id,
                            code=f"A{a_idx}-R{r_idx}-S{s_idx}-B{b_idx}",
                            bin_number=b_idx,
                            coord_x=rack.coord_x,
                            coord_y=rack.coord_y + Decimal(b_idx * 0.5),
                            coord_z=shelf.height_from_floor_cm,
                            qr_code=f"BIN-A{a_idx}-R{r_idx}-S{s_idx}-B{b_idx}"
                        ))
