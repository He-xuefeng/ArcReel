"""Repository for provider job credential bindings."""

from __future__ import annotations

from sqlalchemy import select, update

from lib.db.base import utc_now
from lib.db.models.credential_pool import ProviderJobBinding
from lib.db.models.task import Task
from lib.db.repositories.base import BaseRepository

_RESUMABLE_TASK_STATUSES = ("queued", "running", "cancelling")


class ProviderJobBindingRepository(BaseRepository):
    async def create_binding(
        self,
        *,
        task_id: str,
        provider: str,
        provider_job_id: str,
        credential_id: int,
        media_type: str,
        model_id: str | None,
    ) -> None:
        now = utc_now()
        binding = ProviderJobBinding(
            task_id=task_id,
            provider=provider,
            provider_job_id=provider_job_id,
            credential_id=credential_id,
            media_type=media_type,
            model_id=model_id,
        )
        self.session.add(binding)
        await self.session.execute(
            update(Task)
            .where(Task.task_id == task_id)
            .values(provider_job_id=provider_job_id, credential_id=credential_id, updated_at=now)
        )
        await self.session.flush()

    async def get_by_task(self, task_id: str) -> ProviderJobBinding | None:
        result = await self.session.execute(select(ProviderJobBinding).where(ProviderJobBinding.task_id == task_id))
        return result.scalar_one_or_none()

    async def get_by_provider_job(self, provider: str, provider_job_id: str) -> ProviderJobBinding | None:
        result = await self.session.execute(
            select(ProviderJobBinding).where(
                ProviderJobBinding.provider == provider,
                ProviderJobBinding.provider_job_id == provider_job_id,
            )
        )
        return result.scalar_one_or_none()

    async def has_active_or_resumable_binding(self, credential_id: int) -> bool:
        result = await self.session.execute(
            select(ProviderJobBinding.id)
            .join(Task, Task.task_id == ProviderJobBinding.task_id)
            .where(
                ProviderJobBinding.credential_id == credential_id,
                Task.status.in_(_RESUMABLE_TASK_STATUSES),
            )
            .limit(1)
        )
        return result.first() is not None
