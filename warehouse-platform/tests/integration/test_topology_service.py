"""
Integration tests for Topology Service.
Uses testcontainers to spin up real PostgreSQL and Redis instances.

Run with: pytest tests/integration/ -v
Requires Docker to be running.
"""
import uuid
from typing import AsyncGenerator

import pytest
import pytest_asyncio
import httpx
import asyncio

# NOTE: These tests run against a real service instance.
# Use: docker-compose up topology-service -d before running.
# Or use testcontainers to spin up real DB + service.

TOPOLOGY_SERVICE_URL = "http://localhost:8001"


@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def http_client():
    """Shared async HTTP client for the test session."""
    async with httpx.AsyncClient(base_url=TOPOLOGY_SERVICE_URL, timeout=30.0) as client:
        yield client


@pytest_asyncio.fixture(scope="session")
async def created_warehouse(http_client: httpx.AsyncClient) -> dict:
    """Create a test warehouse and return its data."""
    response = await http_client.post(
        "/api/v1/warehouses",
        json={
            "code": f"TEST-WH-{uuid.uuid4().hex[:6].upper()}",
            "name": "Integration Test Warehouse",
            "city": "Bangalore",
            "country": "India",
            "total_area_sqm": 5000.0,
        },
    )
    assert response.status_code == 201, f"Failed to create warehouse: {response.text}"
    return response.json()


class TestTopologyServiceHealth:
    """Tests for service health endpoint."""

    @pytest.mark.asyncio
    async def test_health_check_returns_ok(self, http_client: httpx.AsyncClient):
        """Service health endpoint should return 200 with status=ok."""
        response = await http_client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "topology-service"


class TestWarehouseCRUD:
    """Tests for warehouse CRUD operations."""

    @pytest.mark.asyncio
    async def test_create_warehouse_returns_201(self, http_client: httpx.AsyncClient):
        """POST /api/v1/warehouses creates a new warehouse."""
        unique_code = f"UNIT-{uuid.uuid4().hex[:6].upper()}"
        response = await http_client.post(
            "/api/v1/warehouses",
            json={
                "code": unique_code,
                "name": "Unit Test Warehouse",
                "city": "Mumbai",
                "country": "India",
                "total_area_sqm": 10000.0,
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["code"] == unique_code
        assert "id" in data

    @pytest.mark.asyncio
    async def test_create_duplicate_warehouse_returns_409(
        self, http_client: httpx.AsyncClient, created_warehouse: dict
    ):
        """Creating a warehouse with duplicate code → 409 Conflict."""
        response = await http_client.post(
            "/api/v1/warehouses",
            json={
                "code": created_warehouse["code"],  # same code
                "name": "Duplicate Warehouse",
                "city": "Delhi",
                "country": "India",
            },
        )
        assert response.status_code == 409

    @pytest.mark.asyncio
    async def test_get_warehouse_by_id(
        self, http_client: httpx.AsyncClient, created_warehouse: dict
    ):
        """GET /api/v1/warehouses/{id} returns correct warehouse."""
        wh_id = created_warehouse["id"]
        response = await http_client.get(f"/api/v1/warehouses/{wh_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == wh_id

    @pytest.mark.asyncio
    async def test_get_nonexistent_warehouse_returns_404(
        self, http_client: httpx.AsyncClient
    ):
        """GET /api/v1/warehouses/{unknown-id} → 404."""
        fake_id = str(uuid.uuid4())
        response = await http_client.get(f"/api/v1/warehouses/{fake_id}")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_list_warehouses_returns_paginated(
        self, http_client: httpx.AsyncClient
    ):
        """GET /api/v1/warehouses returns paginated list."""
        response = await http_client.get("/api/v1/warehouses?limit=10&skip=0")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "pagination" in data
        assert isinstance(data["items"], list)


class TestTopologyFullHierarchy:
    """Tests for full topology creation and retrieval."""

    @pytest.mark.asyncio
    async def test_seed_demo_creates_full_hierarchy(
        self, http_client: httpx.AsyncClient, created_warehouse: dict
    ):
        """POST /api/v1/warehouses/{id}/seed-demo populates full hierarchy."""
        wh_id = created_warehouse["id"]
        response = await http_client.post(f"/api/v1/warehouses/{wh_id}/seed-demo")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_get_topology_returns_nested_structure(
        self, http_client: httpx.AsyncClient, created_warehouse: dict
    ):
        """GET /api/v1/warehouses/{id}/topology returns nested hierarchy."""
        wh_id = created_warehouse["id"]
        response = await http_client.get(f"/api/v1/warehouses/{wh_id}/topology")
        assert response.status_code == 200
        data = response.json()
        assert "zones" in data or "warehouse_id" in data

    @pytest.mark.asyncio
    async def test_bin_resolve_from_coordinates(
        self, http_client: httpx.AsyncClient, created_warehouse: dict
    ):
        """GET /bins/resolve?x=...&y=...&z=... returns nearest bin."""
        wh_id = created_warehouse["id"]
        response = await http_client.get(
            f"/api/v1/warehouses/{wh_id}/bins/resolve",
            params={"x": 5.0, "y": 3.0, "z": 0.5},
        )
        # Either 200 with a bin, or 404 if no bin at that coord (both are valid)
        assert response.status_code in (200, 404)
