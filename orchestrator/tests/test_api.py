"""Tests for API endpoints using FastAPI TestClient.

Uses SQLite in-memory database for fast, isolated API tests.
Bypasses the app lifespan (which connects to PostgreSQL) and
overrides the get_session dependency to use the test database.
"""

import pytest
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from orchestrator.models.database import Base, get_session
from orchestrator.models.orm import UserORM
from orchestrator.services.auth import hash_password, create_access_token


@pytest.fixture
def test_app():
    """Create a FastAPI app with test database, bypassing production lifespan."""
    # Use StaticPool to ensure a single shared connection for SQLite in-memory
    engine = create_engine(
        "sqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    # conftest.py patches PG types at import time
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine)

    # Create app WITHOUT the production lifespan
    @asynccontextmanager
    async def test_lifespan(app: FastAPI):
        yield

    app = FastAPI(lifespan=test_lifespan)

    # Register routers
    from orchestrator.api.auth import router as auth_router
    from orchestrator.api.admin import router as admin_router
    from orchestrator.api.test_runs import router as test_runs_router
    app.include_router(auth_router)
    app.include_router(admin_router)
    app.include_router(test_runs_router)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    # Override get_session dependency
    def override_get_session():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = override_get_session

    # Seed admin user
    session = TestSession()
    admin = UserORM(
        username="admin",
        password_hash=hash_password("admin123"),
        email="admin@test.com",
        role="admin",
        is_active=True,
    )
    session.add(admin)
    session.commit()
    session.close()

    return app


@pytest.fixture
def client(test_app):
    """Create a FastAPI test client."""
    return TestClient(test_app)


@pytest.fixture
def admin_token():
    """Generate a valid admin JWT token."""
    return create_access_token(data={"sub": "admin"})


@pytest.fixture
def auth_headers(admin_token):
    """Authorization headers with admin token."""
    return {"Authorization": f"Bearer {admin_token}"}


class TestHealth:
    def test_health_endpoint(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestAuth:
    def test_login_success(self, client):
        response = client.post("/api/auth/login", data={
            "username": "admin",
            "password": "admin123",
        })
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    def test_login_wrong_password(self, client):
        response = client.post("/api/auth/login", data={
            "username": "admin",
            "password": "wrongpassword",
        })
        assert response.status_code == 401

    def test_login_nonexistent_user(self, client):
        response = client.post("/api/auth/login", data={
            "username": "nobody",
            "password": "test",
        })
        assert response.status_code == 401

    def test_me_endpoint(self, client, auth_headers):
        response = client.get("/api/auth/me", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["username"] == "admin"
        assert data["role"] == "admin"


class TestAdminHardwareProfiles:
    def test_create_hardware_profile(self, client, auth_headers):
        response = client.post("/api/admin/hardware-profiles", json={
            "name": "test-hw-4c8g",
            "cpu_count": 4,
            "memory_gb": 8.0,
            "disk_type": "ssd",
            "disk_size_gb": 100.0,
        }, headers=auth_headers)
        assert response.status_code in (200, 201)
        data = response.json()
        assert data["name"] == "test-hw-4c8g"
        assert data["cpu_count"] == 4
        assert "id" in data

    def test_list_hardware_profiles(self, client, auth_headers):
        # Create first
        client.post("/api/admin/hardware-profiles", json={
            "name": "hw-list-test",
            "cpu_count": 2,
            "memory_gb": 4.0,
            "disk_type": "hdd",
            "disk_size_gb": 50.0,
        }, headers=auth_headers)
        response = client.get("/api/admin/hardware-profiles", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1

    def test_unauthorized_access(self, client):
        response = client.get("/api/admin/hardware-profiles")
        assert response.status_code == 401


class TestAdminLoadProfiles:
    def test_crud_load_profile(self, client, auth_headers):
        # Create
        response = client.post("/api/admin/load-profiles", json={
            "name": "test-low",
            "target_cpu_range_min": 20.0,
            "target_cpu_range_max": 40.0,
            "duration_sec": 300,
            "ramp_up_sec": 30,
        }, headers=auth_headers)
        assert response.status_code in (200, 201)
        lp_id = response.json()["id"]

        # Read
        response = client.get(f"/api/admin/load-profiles/{lp_id}", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["name"] == "test-low"

        # Update
        response = client.put(f"/api/admin/load-profiles/{lp_id}", json={
            "duration_sec": 600,
        }, headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["duration_sec"] == 600

        # Delete
        response = client.delete(f"/api/admin/load-profiles/{lp_id}", headers=auth_headers)
        assert response.status_code in (200, 204)

        # Verify deleted
        response = client.get(f"/api/admin/load-profiles/{lp_id}", headers=auth_headers)
        assert response.status_code == 404
