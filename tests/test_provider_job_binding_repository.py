"""Provider job binding repository tests."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from lib.db.base import DEFAULT_USER_ID, Base, utc_now
from lib.db.models.task import Task
from lib.db.repositories.credential_repository import CredentialRepository
from lib.db.repositories.provider_job_binding_repository import ProviderJobBindingRepository


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as s:
        yield s
    await engine.dispose()


async def _task(session: AsyncSession, task_id: str, status: str = "running") -> Task:
    now = utc_now()
    task = Task(
        task_id=task_id,
        project_name="proj",
        task_type="generate_video",
        media_type="video",
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


class TestProviderJobBindingRepository:
    async def test_create_binding_updates_task_and_persists_binding(self, session: AsyncSession):
        credential = await CredentialRepository(session).create("gemini-aistudio", "key", api_key="1")
        task = await _task(session, "task-1")
        repo = ProviderJobBindingRepository(session)

        await repo.create_binding(
            task_id=task.task_id,
            provider="gemini-aistudio",
            provider_job_id="job-1",
            credential_id=credential.id,
            media_type="video",
            model_id="veo",
        )
        await session.refresh(task)
        binding = await repo.get_by_task(task.task_id)

        assert binding is not None
        assert binding.provider_job_id == "job-1"
        assert binding.credential_id == credential.id
        assert binding.model_id == "veo"
        assert task.provider_job_id == "job-1"
        assert task.credential_id == credential.id

    async def test_get_by_provider_job(self, session: AsyncSession):
        credential = await CredentialRepository(session).create("gemini-aistudio", "key", api_key="1")
        task = await _task(session, "task-1")
        repo = ProviderJobBindingRepository(session)
        await repo.create_binding(
            task_id=task.task_id,
            provider="gemini-aistudio",
            provider_job_id="job-1",
            credential_id=credential.id,
            media_type="video",
            model_id=None,
        )

        assert await repo.get_by_provider_job("gemini-aistudio", "job-1") is not None
        assert await repo.get_by_provider_job("ark", "job-1") is None

    @pytest.mark.parametrize("status", ["queued", "running", "cancelling"])
    async def test_has_active_or_resumable_binding_true_for_non_terminal_tasks(
        self, session: AsyncSession, status: str
    ):
        credential = await CredentialRepository(session).create("gemini-aistudio", "key", api_key="1")
        task = await _task(session, f"task-{status}", status=status)
        repo = ProviderJobBindingRepository(session)
        await repo.create_binding(
            task_id=task.task_id,
            provider="gemini-aistudio",
            provider_job_id=f"job-{status}",
            credential_id=credential.id,
            media_type="video",
            model_id=None,
        )

        assert await repo.has_active_or_resumable_binding(credential.id) is True

    @pytest.mark.parametrize("status", ["succeeded", "failed", "cancelled"])
    async def test_has_active_or_resumable_binding_false_for_terminal_tasks(self, session: AsyncSession, status: str):
        credential = await CredentialRepository(session).create("gemini-aistudio", "key", api_key="1")
        task = await _task(session, f"task-{status}", status=status)
        repo = ProviderJobBindingRepository(session)
        await repo.create_binding(
            task_id=task.task_id,
            provider="gemini-aistudio",
            provider_job_id=f"job-{status}",
            credential_id=credential.id,
            media_type="video",
            model_id=None,
        )

        assert await repo.has_active_or_resumable_binding(credential.id) is False
