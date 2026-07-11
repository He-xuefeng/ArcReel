"""Credential pool repository tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from lib.config.service import ConfigService
from lib.db.base import DEFAULT_USER_ID, Base, utc_now
from lib.db.models.task import Task
from lib.db.repositories.credential_pool_repository import CredentialPoolRepository
from lib.db.repositories.credential_repository import CredentialRepository


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as s:
        yield s
    await engine.dispose()


async def _enable_pool(session: AsyncSession, provider: str, mode: str = "shared") -> None:
    svc = ConfigService(session)
    await svc.set_provider_config(provider, "credential_pool_enabled", "true")
    await svc.set_provider_config(provider, "credential_pool_concurrency_mode", mode)


async def _task(session: AsyncSession, task_id: str, media_type: str, status: str = "running") -> Task:
    now = utc_now()
    task = Task(
        task_id=task_id,
        project_name="proj",
        task_type=f"generate_{media_type}",
        media_type=media_type,
        resource_id=task_id,
        status=status,
        source="webui",
        provider_id="gemini-aistudio",
        queued_at=now,
        updated_at=now,
        user_id=DEFAULT_USER_ID,
    )
    session.add(task)
    await session.flush()
    return task


class TestCredentialPoolRepository:
    async def test_get_pool_settings_defaults_to_disabled_shared(self, session: AsyncSession):
        repo = CredentialPoolRepository(session)
        settings = await repo.get_pool_settings("gemini-aistudio")
        assert settings.enabled is False
        assert settings.concurrency_mode == "shared"

    async def test_list_pool_summaries_counts_enabled_credentials_and_active_leases(self, session: AsyncSession):
        await _enable_pool(session, "gemini-aistudio", "separate")
        cred_repo = CredentialRepository(session)
        c1 = await cred_repo.create("gemini-aistudio", "k1", api_key="1", is_enabled=True)
        await cred_repo.create("gemini-aistudio", "k2", api_key="2", is_enabled=False)
        await _task(session, "t1", "image")
        pool_repo = CredentialPoolRepository(session)
        acquired = await pool_repo.acquire_lease("gemini-aistudio", "image", "t1", "worker-1")
        assert acquired.acquired is True
        assert acquired.credential_id == c1.id

        summaries = await pool_repo.list_pool_summaries({"gemini-aistudio"})
        summary = summaries["gemini-aistudio"]
        assert summary.enabled is True
        assert summary.concurrency_mode == "separate"
        assert summary.enabled_credentials_count == 1
        assert summary.active_lease_count == 1

    async def test_acquire_shared_blocks_other_media_on_same_credential(self, session: AsyncSession):
        await _enable_pool(session, "gemini-aistudio", "shared")
        cred_repo = CredentialRepository(session)
        credential = await cred_repo.create("gemini-aistudio", "k1", api_key="1", is_enabled=True)
        await _task(session, "image-task", "image")
        await _task(session, "video-task", "video")
        pool_repo = CredentialPoolRepository(session)

        first = await pool_repo.acquire_lease("gemini-aistudio", "image", "image-task", "worker-1")
        second = await pool_repo.acquire_lease("gemini-aistudio", "video", "video-task", "worker-2")

        assert first == type(first)(acquired=True, credential_id=credential.id)
        assert second.acquired is False
        assert second.reason == "waiting_for_credential"

    async def test_acquire_separate_allows_one_image_and_one_video_per_credential(self, session: AsyncSession):
        await _enable_pool(session, "gemini-aistudio", "separate")
        cred_repo = CredentialRepository(session)
        credential = await cred_repo.create("gemini-aistudio", "k1", api_key="1", is_enabled=True)
        await _task(session, "image-task", "image")
        await _task(session, "video-task", "video")
        await _task(session, "second-image", "image")
        pool_repo = CredentialPoolRepository(session)

        image = await pool_repo.acquire_lease("gemini-aistudio", "image", "image-task", "worker-1")
        video = await pool_repo.acquire_lease("gemini-aistudio", "video", "video-task", "worker-2")
        blocked = await pool_repo.acquire_lease("gemini-aistudio", "image", "second-image", "worker-3")

        assert image.acquired is True and image.credential_id == credential.id
        assert video.acquired is True and video.credential_id == credential.id
        assert blocked.acquired is False
        assert blocked.reason == "waiting_for_credential"

    async def test_acquire_round_robins_nulls_first_then_oldest(self, session: AsyncSession):
        await _enable_pool(session, "gemini-aistudio", "shared")
        cred_repo = CredentialRepository(session)
        used = await cred_repo.create("gemini-aistudio", "used", api_key="1", is_enabled=True)
        never_used = await cred_repo.create("gemini-aistudio", "never", api_key="2", is_enabled=True)
        used.last_leased_at = datetime(2026, 1, 1, tzinfo=UTC)
        await _task(session, "t1", "image")
        pool_repo = CredentialPoolRepository(session)

        result = await pool_repo.acquire_lease("gemini-aistudio", "image", "t1", "worker-1")

        assert result.acquired is True
        assert result.credential_id == never_used.id

    async def test_find_full_providers_only_returns_enabled_full_pools(self, session: AsyncSession):
        await _enable_pool(session, "gemini-aistudio", "shared")
        await _enable_pool(session, "ark", "shared")
        cred_repo = CredentialRepository(session)
        await cred_repo.create("gemini-aistudio", "k1", api_key="1", is_enabled=True)
        await _task(session, "t1", "image")
        pool_repo = CredentialPoolRepository(session)
        await pool_repo.acquire_lease("gemini-aistudio", "image", "t1", "worker-1")

        full = await pool_repo.find_full_providers("image", {"gemini-aistudio", "ark"})

        assert full == {"gemini-aistudio", "ark"}

    async def test_release_lease_is_idempotent(self, session: AsyncSession):
        await _enable_pool(session, "gemini-aistudio", "shared")
        await CredentialRepository(session).create("gemini-aistudio", "k1", api_key="1", is_enabled=True)
        await _task(session, "t1", "image")
        pool_repo = CredentialPoolRepository(session)
        await pool_repo.acquire_lease("gemini-aistudio", "image", "t1", "worker-1")

        assert await pool_repo.release_lease("t1", "succeeded") is True
        assert await pool_repo.release_lease("t1", "succeeded") is False

    async def test_recover_leases_releases_terminal_and_queued_without_binding(self, session: AsyncSession):
        await _enable_pool(session, "gemini-aistudio", "shared")
        cred_repo = CredentialRepository(session)
        await cred_repo.create("gemini-aistudio", "k1", api_key="1", is_enabled=True)
        await cred_repo.create("gemini-aistudio", "k2", api_key="2", is_enabled=True)
        terminal = await _task(session, "terminal", "image", status="running")
        queued = await _task(session, "queued", "image", status="queued")
        pool_repo = CredentialPoolRepository(session)
        await pool_repo.acquire_lease("gemini-aistudio", "image", terminal.task_id, "worker-1")
        await pool_repo.acquire_lease("gemini-aistudio", "image", queued.task_id, "worker-1")
        terminal.status = "succeeded"
        await session.flush()

        recovered = await pool_repo.recover_leases()

        assert recovered == 2
        assert await pool_repo.release_lease("terminal", "succeeded") is False
        assert await pool_repo.release_lease("queued", "cancelled") is False
