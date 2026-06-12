"""
Workbench user auth: hashing, default seed, login, forced rotation,
sessions, user CRUD — against a throwaway SQLite DB with the real
/auth router mounted on a minimal app.
"""

import asyncio
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from domains.auth.passwords import hash_password, verify_password
from domains.auth import users as users_svc


# ── Pure hashing ──────────────────────────────────────────────────────

def test_password_hash_roundtrip():
    h = hash_password("correct horse battery staple")
    assert h.startswith("scrypt$")
    assert verify_password("correct horse battery staple", h)
    assert not verify_password("wrong", h)
    assert not verify_password("anything", "garbage")
    # same password → different salt → different hash
    assert h != hash_password("correct horse battery staple")


# ── App harness: real router, throwaway DB, one event loop per test ───

@asynccontextmanager
async def make_client(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/auth.db")
    maker = async_sessionmaker(engine, expire_on_commit=False)

    from infrastructure.database.connection import Base
    from domains.models.db_models import WorkbenchUser, WorkbenchSession  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with maker() as s:
        await users_svc.ensure_default_admin(s)

    from api.routes.auth import router
    from infrastructure.database import get_db

    app = FastAPI()
    app.include_router(router)

    async def override_get_db():
        async with maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
    app.dependency_overrides[get_db] = override_get_db

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport,
                                 base_url="http://t") as client:
        client.extra_transport = transport
        yield client
    await engine.dispose()


# ── Flows ─────────────────────────────────────────────────────────────

def test_default_admin_and_forced_rotation(tmp_path):
    async def flow():
        async with make_client(tmp_path) as c:
            # wrong password → 401
            r = await c.post("/auth/login",
                             json={"username": "root", "password": "nope"})
            assert r.status_code == 401

            # root/root logs in, must_change flagged
            r = await c.post("/auth/login",
                             json={"username": "root", "password": "root"})
            assert r.status_code == 200
            assert r.json()["must_change_password"] is True

            # everything but the rotation flow is blocked
            assert (await c.get("/auth/users")).status_code == 403
            r = await c.get("/auth/me")
            assert r.status_code == 200
            assert r.json()["must_change_password"] is True

            # weak/forbidden passwords rejected
            for bad in ("short", "root", "ROOT"):
                r = await c.post("/auth/change-password", json={
                    "current_password": "root", "new_password": bad})
                assert r.status_code == 422, bad

            # rotate properly
            r = await c.post("/auth/change-password", json={
                "current_password": "root",
                "new_password": "hunter2hunter2"})
            assert r.status_code == 200

            # now admin endpoints open up
            r = await c.get("/auth/users")
            assert r.status_code == 200
            assert r.json()[0]["username"] == "root"
            assert r.json()[0]["must_change_password"] is False

            # old password no longer works
            r = await c.post("/auth/login",
                             json={"username": "root", "password": "root"})
            assert r.status_code == 401
    asyncio.run(flow())


def test_user_crud_and_roles(tmp_path):
    async def flow():
        async with make_client(tmp_path) as c:
            await c.post("/auth/login",
                         json={"username": "root", "password": "root"})
            await c.post("/auth/change-password", json={
                "current_password": "root", "new_password": "hunter2hunter2"})

            # create a member with a temp password (shown once)
            r = await c.post("/auth/users", json={"username": "chris",
                                                  "role": "member"})
            assert r.status_code == 201
            temp = r.json()["temporary_password"]

            # duplicate → 409
            assert (await c.post("/auth/users", json={
                "username": "chris"})).status_code == 409

            # can't disable yourself
            assert (await c.delete("/auth/users/root")).status_code == 422

            # member logs in (separate cookie jar), rotation forced
            async with httpx.AsyncClient(
                    transport=c.extra_transport, base_url="http://t") as m:
                r = await m.post("/auth/login", json={
                    "username": "chris", "password": temp})
                assert r.json()["must_change_password"] is True
                await m.post("/auth/change-password", json={
                    "current_password": temp,
                    "new_password": "memberpass1"})
                # member is not admin
                assert (await m.get("/auth/users")).status_code == 403

            # disable, then login dies
            assert (await c.delete("/auth/users/chris")).status_code == 200
            r = await c.post("/auth/login", json={
                "username": "chris", "password": "memberpass1"})
            assert r.status_code == 401
    asyncio.run(flow())


def test_logout_and_session_revocation(tmp_path):
    async def flow():
        async with make_client(tmp_path) as c:
            await c.post("/auth/login",
                         json={"username": "root", "password": "root"})
            await c.post("/auth/change-password", json={
                "current_password": "root", "new_password": "hunter2hunter2"})
            assert (await c.get("/auth/me")).status_code == 200
            await c.post("/auth/logout")
            assert (await c.get("/auth/me")).status_code == 401
    asyncio.run(flow())


def test_password_change_revokes_other_sessions(tmp_path):
    async def flow():
        async with make_client(tmp_path) as c:
            await c.post("/auth/login",
                         json={"username": "root", "password": "root"})
            await c.post("/auth/change-password", json={
                "current_password": "root", "new_password": "hunter2hunter2"})

            # second browser
            async with httpx.AsyncClient(
                    transport=c.extra_transport, base_url="http://t") as other:
                await other.post("/auth/login", json={
                    "username": "root", "password": "hunter2hunter2"})
                assert (await other.get("/auth/me")).status_code == 200

                # first browser rotates again → second session dies
                r = await c.post("/auth/change-password", json={
                    "current_password": "hunter2hunter2",
                    "new_password": "anotherone9"})
                assert r.json()["other_sessions_revoked"] == 1
                assert (await other.get("/auth/me")).status_code == 401
                assert (await c.get("/auth/me")).status_code == 200
    asyncio.run(flow())
