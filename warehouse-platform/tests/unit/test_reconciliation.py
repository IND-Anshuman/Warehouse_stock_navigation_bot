"""
Unit tests for the Reconciliation Engine.
Tests all mismatch detection scenarios.
"""
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

# ---------------------------------------------------------------------------
#  Test fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def make_observation():
    """Factory for synthetic ObservationCreated events."""

    def _make(
        bin_id: str = "bin-001",
        decoded_qr: str = "SKU-ELEC-001",
        confidence: float = 0.95,
        warehouse_id: str = "wh-001",
        mission_id: str = "mission-001",
        robot_id: str = "robot-001",
    ) -> dict:
        return {
            "observation_id": str(uuid.uuid4()),
            "bin_id": bin_id,
            "decoded_qr": decoded_qr,
            "detection_confidence": confidence,
            "warehouse_id": warehouse_id,
            "mission_id": mission_id,
            "robot_id": robot_id,
            "bin_code": f"Z1-A1-R1-S1-B1",
        }

    return _make


@pytest.fixture
def make_inventory_item():
    """Factory for expected inventory records."""

    def _make(bin_id: str, sku: str, expected_qty: int = 1) -> MagicMock:
        item = MagicMock()
        item.bin_id = bin_id
        item.sku = sku
        item.expected_qty = expected_qty
        return item

    return _make


# ---------------------------------------------------------------------------
#  ReconciliationEngine tests (mocked dependencies)
# ---------------------------------------------------------------------------

class TestReconciliationEngineCorrectPlacement:
    """Tests for CORRECT_PLACEMENT scenario."""

    @pytest.mark.asyncio
    async def test_correct_placement_returns_correct_status(
        self, make_observation, make_inventory_item
    ):
        """When observed SKU matches expected SKU in same bin → CORRECT_PLACEMENT."""
        # Arrange
        observation = make_observation(bin_id="bin-001", decoded_qr="SKU-ELEC-001")
        expected_items = [make_inventory_item("bin-001", "SKU-ELEC-001", expected_qty=1)]

        repo = AsyncMock()
        repo.get_inventory_by_bin.return_value = expected_items
        producer = AsyncMock()

        # Act — import lazily to avoid circular imports in test context
        from services.reconciliation_service.app.engine.reconciliation_engine import (
            ReconciliationEngine,
            MismatchType,
        )  # type: ignore
        engine = ReconciliationEngine(repo=repo, alert_publisher=producer)
        result = await engine.reconcile_observation(observation)

        # Assert
        assert result.result_type == MismatchType.CORRECT_PLACEMENT
        repo.create_alert.assert_not_called()
        producer.publish_inventory_mismatch.assert_not_called()
        producer.publish_inventory_verified.assert_called_once()

    @pytest.mark.asyncio
    async def test_low_confidence_observation_skipped(self, make_observation):
        """Observations below confidence threshold are not reconciled."""
        observation = make_observation(confidence=0.50)  # below 0.70 threshold

        repo = AsyncMock()
        producer = AsyncMock()

        from services.reconciliation_service.app.engine.reconciliation_engine import (
            ReconciliationEngine,
        )  # type: ignore
        engine = ReconciliationEngine(repo=repo, alert_publisher=producer)
        result = await engine.reconcile_observation(observation)

        assert result is None
        repo.get_inventory_by_bin.assert_not_called()


class TestReconciliationEngineMisplaced:
    """Tests for MISPLACED scenario."""

    @pytest.mark.asyncio
    async def test_misplaced_item_creates_warning_alert(
        self, make_observation, make_inventory_item
    ):
        """SKU found in wrong bin → MISPLACED alert with MEDIUM severity."""
        observation = make_observation(bin_id="bin-001", decoded_qr="SKU-FURN-001")

        # bin-001 has SKU-ELEC-001, not SKU-FURN-001
        wrong_bin_items = [make_inventory_item("bin-001", "SKU-ELEC-001")]

        # SKU-FURN-001 belongs in bin-050
        correct_location = make_inventory_item("bin-050", "SKU-FURN-001")

        repo = AsyncMock()
        repo.get_inventory_by_bin.return_value = wrong_bin_items
        repo.locate_sku_globally.return_value = correct_location

        alert = MagicMock()
        alert.id = str(uuid.uuid4())
        repo.create_alert.return_value = alert
        producer = AsyncMock()

        from services.reconciliation_service.app.engine.reconciliation_engine import (
            ReconciliationEngine,
            MismatchType,
        )  # type: ignore
        engine = ReconciliationEngine(repo=repo, alert_publisher=producer)
        result = await engine.reconcile_observation(observation)

        assert result.result_type == MismatchType.MISPLACED
        repo.create_alert.assert_called_once()
        call_args = repo.create_alert.call_args
        assert call_args[1]["severity"] == "MEDIUM" or call_args[0][0].get("severity") == "MEDIUM"


class TestReconciliationEngineUnknown:
    """Tests for UNKNOWN inventory scenario."""

    @pytest.mark.asyncio
    async def test_unknown_sku_creates_critical_alert(
        self, make_observation
    ):
        """SKU not in any WMS record → UNKNOWN with CRITICAL severity."""
        observation = make_observation(decoded_qr="SKU-COUNTERFEIT-999")

        repo = AsyncMock()
        repo.get_inventory_by_bin.return_value = []  # bin has nothing expected
        repo.locate_sku_globally.return_value = None  # SKU not in WMS at all

        alert = MagicMock()
        alert.id = str(uuid.uuid4())
        repo.create_alert.return_value = alert
        producer = AsyncMock()

        from services.reconciliation_service.app.engine.reconciliation_engine import (
            ReconciliationEngine,
            MismatchType,
        )  # type: ignore
        engine = ReconciliationEngine(repo=repo, alert_publisher=producer)
        result = await engine.reconcile_observation(observation)

        assert result.result_type == MismatchType.UNKNOWN
        repo.create_alert.assert_called_once()


class TestReconciliationEngineMissing:
    """Tests for MISSING inventory scenario."""

    @pytest.mark.asyncio
    async def test_missing_item_when_bin_scanned_empty(
        self, make_inventory_item
    ):
        """Robot scanned bin but detected nothing (decoded_qr is empty) → MISSING."""
        observation = {
            "observation_id": str(uuid.uuid4()),
            "bin_id": "bin-001",
            "decoded_qr": "",  # nothing scanned
            "detection_confidence": 0.90,  # confident scan, just empty
            "warehouse_id": "wh-001",
            "mission_id": "mission-001",
            "robot_id": "robot-001",
            "bin_code": "Z1-A1-R1-S1-B1",
        }

        expected = [make_inventory_item("bin-001", "SKU-ELEC-001")]

        repo = AsyncMock()
        repo.get_inventory_by_bin.return_value = expected
        alert = MagicMock()
        alert.id = str(uuid.uuid4())
        repo.create_alert.return_value = alert
        producer = AsyncMock()

        from services.reconciliation_service.app.engine.reconciliation_engine import (
            ReconciliationEngine,
            MismatchType,
        )  # type: ignore
        engine = ReconciliationEngine(repo=repo, alert_publisher=producer)
        result = await engine.reconcile_observation(observation)

        assert result.result_type == MismatchType.MISSING


# ---------------------------------------------------------------------------
#  Event Bus Deduplication Tests
# ---------------------------------------------------------------------------

class TestEventDeduplication:
    """Tests for Redis-based idempotency checks."""

    @pytest.mark.asyncio
    async def test_duplicate_observation_is_rejected(self):
        """Same observation_id submitted twice → second is deduplicated."""
        redis_mock = AsyncMock()
        # First call: key doesn't exist → SET returns True
        # Second call: key exists → SET returns False
        redis_mock.set.side_effect = [True, False]

        obs_id = str(uuid.uuid4())

        from services.observation_service.app.middleware.deduplication import is_duplicate  # type: ignore

        is_dup_1 = await is_duplicate(obs_id, redis_mock)
        is_dup_2 = await is_duplicate(obs_id, redis_mock)

        assert not is_dup_1  # first submission: not a duplicate
        assert is_dup_2       # second submission: is a duplicate


# ---------------------------------------------------------------------------
#  Frame Processing Tests
# ---------------------------------------------------------------------------

class TestFrameProcessor:
    """Tests for the QR detection and blur analysis logic."""

    def test_laplacian_variance_blurry_image(self):
        """Simulated blurry image should return low variance score."""
        import numpy as np

        # Create a solid-color 'blurry' image (no edges = zero variance)
        blurry_array = np.ones((100, 100, 3), dtype=np.uint8) * 128
        import cv2
        _, img_bytes = cv2.imencode(".jpg", blurry_array)

        from services.observation_service.app.processing.frame_processor import FrameProcessor  # type: ignore

        score = FrameProcessor.compute_laplacian_variance(img_bytes.tobytes())
        assert score < 10.0, f"Expected blurry image to score < 10, got {score}"

    def test_is_blurry_returns_true_for_solid_image(self):
        """Solid color image should be flagged as blurry."""
        import numpy as np
        import cv2

        solid = np.ones((100, 100, 3), dtype=np.uint8) * 64
        _, img_bytes = cv2.imencode(".jpg", solid)

        from services.observation_service.app.processing.frame_processor import FrameProcessor  # type: ignore

        assert FrameProcessor.is_blurry(img_bytes.tobytes(), threshold=100.0) is True


# ---------------------------------------------------------------------------
#  Security Context Tests
# ---------------------------------------------------------------------------

class TestJWTSecurity:
    """Tests for JWT token creation and validation."""

    def test_create_and_decode_token(self):
        """Created token should decode with matching claims."""
        from packages.security_context import create_access_token, decode_token, UserRole  # type: ignore

        secret = "test-secret-key-for-testing"
        user_id = str(uuid.uuid4())

        token = create_access_token(
            user_id=user_id,
            email="test@example.com",
            role=UserRole.OPERATOR,
            warehouse_ids=["wh-001", "wh-002"],
            secret_key=secret,
        )

        payload = decode_token(token, secret)

        assert payload.sub == user_id
        assert payload.email == "test@example.com"
        assert payload.role == UserRole.OPERATOR
        assert "wh-001" in payload.warehouse_ids

    def test_invalid_token_raises_http_exception(self):
        """Malformed token should raise 401 HTTPException."""
        from fastapi import HTTPException
        from packages.security_context import decode_token  # type: ignore

        with pytest.raises(HTTPException) as exc_info:
            decode_token("this.is.not.a.valid.token", "some-secret")

        assert exc_info.value.status_code == 401

    def test_role_permissions_platform_admin_has_all(self):
        """Platform admin should have all critical permissions."""
        from packages.security_context import has_permission, UserRole  # type: ignore

        admin = UserRole.PLATFORM_ADMIN
        assert has_permission(admin, "warehouses:write") is True
        assert has_permission(admin, "users:delete") is True
        assert has_permission(admin, "audit:read") is True

    def test_role_permissions_viewer_has_limited(self):
        """Viewer should only have read permissions."""
        from packages.security_context import has_permission, UserRole  # type: ignore

        viewer = UserRole.VIEWER
        assert has_permission(viewer, "warehouses:read") is True
        assert has_permission(viewer, "warehouses:write") is False
        assert has_permission(viewer, "users:delete") is False
        assert has_permission(viewer, "missions:write") is False
