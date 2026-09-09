"""Tests for FastAPI endpoints."""

import pytest
from httpx import ASGITransport, AsyncClient

from costlens.api.app import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_health_check(client):
    response = await client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["version"] == "0.1.0"


@pytest.mark.asyncio
async def test_create_budget(client):
    response = await client.post("/api/budgets", json={
        "name": "Monthly AWS",
        "amount": 10000.0,
        "currency": "USD",
        "period": "monthly",
        "provider": "aws",
    })
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "created"
    assert data["budget"]["name"] == "Monthly AWS"


@pytest.mark.asyncio
async def test_delete_nonexistent_session(client):
    response = await client.delete("/api/sessions/nonexistent")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_get_nonexistent_session_history(client):
    response = await client.get("/api/sessions/nonexistent/history")
    assert response.status_code == 404
