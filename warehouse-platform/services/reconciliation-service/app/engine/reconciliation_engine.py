import structlog
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models.reconciliation import Inventory, ReconciliationResult, Alert
from packages.event_bus import Topics, BaseEventProducer # type: ignore
import enum

logger = structlog.get_logger(__name__)

class MismatchType(str, enum.Enum):
    CORRECT_PLACEMENT = "CORRECT_PLACEMENT"
    MISPLACED = "MISPLACED"
    MISSING = "MISSING"
    DUPLICATE = "DUPLICATE"
    UNKNOWN = "UNKNOWN"
    QUANTITY_DISCREPANCY = "QUANTITY_DISCREPANCY"

class ReconciliationEngine:
    def __init__(self, db: AsyncSession, event_producer: BaseEventProducer):
        self.db = db
        self.producer = event_producer

    async def reconcile_observation(self, observation: dict) -> ReconciliationResult:
        """
        Process observation data against expected inventory state.
        Determines mismatch type and triggers alerts.
        """
        bin_id = observation.get("bin_id")
        decoded_qr = observation.get("decoded_qr")
        warehouse_id = observation.get("warehouse_id")
        obs_id = observation.get("observation_id")
        confidence = observation.get("detection_confidence", 1.0)

        # 1. Fetch expected inventory items in the bin
        result = await self.db.execute(select(Inventory).filter(Inventory.bin_id == bin_id, Inventory.is_active == True))
        expected_items = result.scalars().all()

        recon_type = MismatchType.CORRECT_PLACEMENT
        expected_sku = None
        expected_qty = 0
        observed_sku = decoded_qr if decoded_qr else None
        observed_qty = 1 if decoded_qr else 0
        correct_bin_id = None

        if not expected_items:
            # Nothing expected in this bin
            if decoded_qr:
                # But something was found! Check if SKU is misplaced from another bin
                gl_result = await self.db.execute(select(Inventory).filter(Inventory.sku == decoded_qr, Inventory.is_active == True))
                any_item = gl_result.scalar_one_or_none()
                if any_item:
                    recon_type = MismatchType.MISPLACED
                    correct_bin_id = any_item.bin_id
                else:
                    recon_type = MismatchType.UNKNOWN
            else:
                # Expected nothing, found nothing
                recon_type = MismatchType.CORRECT_PLACEMENT
        else:
            # We expected items in this bin
            expected_sku = expected_items[0].sku
            expected_qty = sum(item.expected_qty for item in expected_items)

            if not decoded_qr:
                # Expected items, but found nothing
                recon_type = MismatchType.MISSING
            elif decoded_qr == expected_sku:
                # Correct SKU. Check quantity
                if observed_qty == expected_qty:
                    recon_type = MismatchType.CORRECT_PLACEMENT
                else:
                    recon_type = MismatchType.QUANTITY_DISCREPANCY
            else:
                # Wrong SKU found. Check if the scanned SKU exists elsewhere in WMS
                gl_result = await self.db.execute(select(Inventory).filter(Inventory.sku == decoded_qr, Inventory.is_active == True))
                any_item = gl_result.scalar_one_or_none()
                if any_item:
                    recon_type = MismatchType.MISPLACED
                    correct_bin_id = any_item.bin_id
                else:
                    recon_type = MismatchType.UNKNOWN

        # 2. Write Reconciliation Result Record
        recon = ReconciliationResult(
            observation_id=obs_id,
            warehouse_id=warehouse_id,
            bin_id=bin_id,
            sku=observed_sku,
            result_type=recon_type.value,
            expected_sku=expected_sku,
            expected_qty=expected_qty,
            observed_sku=observed_sku,
            observed_qty=observed_qty,
            expected_bin_id=correct_bin_id,
            confidence=confidence
        )
        self.db.add(recon)
        await self.db.commit()
        await self.db.refresh(recon)

        # 3. Create Alert if mismatch detected
        if recon_type != MismatchType.CORRECT_PLACEMENT:
            severity = "MEDIUM"
            if recon_type == MismatchType.UNKNOWN:
                severity = "CRITICAL"
            elif recon_type == MismatchType.MISSING:
                severity = "HIGH"

            alert = Alert(
                warehouse_id=warehouse_id,
                reconciliation_id=recon.id,
                observation_id=obs_id,
                bin_id=bin_id,
                sku=observed_sku or expected_sku,
                alert_type=recon_type.value,
                severity=severity,
                title=f"{recon_type.value} Discrepancy in Bin {observation.get('bin_code')}",
                description=f"Expected: {expected_sku or 'EMPTY'} (Qty: {expected_qty}), Observed: {observed_sku or 'EMPTY'} (Qty: {observed_qty}).",
                expected_value=f"SKU: {expected_sku}, Qty: {expected_qty}",
                observed_value=f"SKU: {observed_sku}, Qty: {observed_qty}"
            )
            self.db.add(alert)
            await self.db.commit()
            await self.db.refresh(alert)
            logger.info("reconciliation_mismatch_alert", alert_id=alert.id, type=recon_type.value)

            # Publish Mismatch Event
            await self.producer.publish(
                topic=Topics.RECONCILIATION_MISMATCH,
                event_type="InventoryMismatchDetected",
                payload={
                    "mismatch_id": recon.id,
                    "alert_id": alert.id,
                    "observation_id": obs_id,
                    "warehouse_id": warehouse_id,
                    "bin_id": bin_id,
                    "expected_sku": expected_sku,
                    "expected_quantity": expected_qty,
                    "observed_sku": observed_sku,
                    "observed_quantity": observed_qty,
                    "mismatch_type": recon_type.value,
                    "confidence": float(confidence),
                    "expected_bin_id": correct_bin_id
                },
                partition_key=warehouse_id
            )
        else:
            # Publish Verified Event
            await self.producer.publish(
                topic=Topics.RECONCILIATION_VERIFIED,
                event_type="InventoryVerified",
                payload={
                    "verification_id": recon.id,
                    "observation_id": obs_id,
                    "warehouse_id": warehouse_id,
                    "bin_id": bin_id,
                    "sku": observed_sku,
                    "confidence": float(confidence)
                },
                partition_key=warehouse_id
            )

        return recon
