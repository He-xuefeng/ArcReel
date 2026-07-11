"""Repository helpers for provider credential pooling."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from lib.db.base import utc_now
from lib.db.models.config import ProviderConfig
from lib.db.models.credential import ProviderCredential
from lib.db.models.credential_pool import ProviderCredentialLease, ProviderJobBinding
from lib.db.models.task import Task
from lib.db.repositories.base import BaseRepository, rowcount
from lib.task_failure import FAILURE_CODE_KEYS

CredentialPoolConcurrencyMode = Literal["shared", "separate"]


@dataclass(frozen=True)
class CredentialPoolSettings:
    enabled: bool
    concurrency_mode: CredentialPoolConcurrencyMode


@dataclass(frozen=True)
class CredentialLeaseResult:
    acquired: bool
    credential_id: int | None = None
    reason: str | None = None


@dataclass(frozen=True)
class CredentialPoolSummary:
    enabled: bool
    concurrency_mode: CredentialPoolConcurrencyMode
    enabled_credentials_count: int
    active_lease_count: int


class CredentialPoolRepository(BaseRepository):
    async def get_pool_settings(self, provider: str) -> CredentialPoolSettings:
        rows = await self.session.execute(
            select(ProviderConfig.key, ProviderConfig.value).where(
                ProviderConfig.provider == provider,
                ProviderConfig.key.in_(("credential_pool_enabled", "credential_pool_concurrency_mode")),
            )
        )
        values = {key: value for key, value in rows.all()}
        enabled = values.get("credential_pool_enabled", "false").strip().lower() == "true"
        mode = values.get("credential_pool_concurrency_mode", "shared").strip().lower()
        if mode not in ("shared", "separate"):
            mode = "shared"
        return CredentialPoolSettings(enabled=enabled, concurrency_mode=mode)  # type: ignore[arg-type]

    async def list_pool_summaries(
        self, providers: list[str] | tuple[str, ...] | set[str] | None = None
    ) -> dict[str, CredentialPoolSummary]:
        provider_filter = set(providers) if providers is not None else None
        provider_ids = set(provider_filter or [])

        config_stmt = select(ProviderConfig.provider, ProviderConfig.key, ProviderConfig.value).where(
            ProviderConfig.key.in_(("credential_pool_enabled", "credential_pool_concurrency_mode"))
        )
        if provider_filter is not None:
            config_stmt = config_stmt.where(ProviderConfig.provider.in_(provider_filter))
        config_rows = await self.session.execute(config_stmt)
        config_by_provider: dict[str, dict[str, str]] = {}
        for provider, key, value in config_rows.all():
            provider_ids.add(provider)
            config_by_provider.setdefault(provider, {})[key] = value

        enabled_stmt = (
            select(ProviderCredential.provider, func.count(ProviderCredential.id))
            .where(ProviderCredential.is_enabled == True)  # noqa: E712
            .group_by(ProviderCredential.provider)
        )
        if provider_filter is not None:
            enabled_stmt = enabled_stmt.where(ProviderCredential.provider.in_(provider_filter))
        enabled_rows = await self.session.execute(enabled_stmt)
        enabled_counts = {provider: count for provider, count in enabled_rows.all()}
        provider_ids.update(enabled_counts)

        lease_stmt = (
            select(ProviderCredentialLease.provider, func.count(ProviderCredentialLease.id))
            .where(ProviderCredentialLease.status == "active")
            .group_by(ProviderCredentialLease.provider)
        )
        if provider_filter is not None:
            lease_stmt = lease_stmt.where(ProviderCredentialLease.provider.in_(provider_filter))
        lease_rows = await self.session.execute(lease_stmt)
        active_counts = {provider: count for provider, count in lease_rows.all()}
        provider_ids.update(active_counts)

        summaries: dict[str, CredentialPoolSummary] = {}
        for provider in sorted(provider_ids):
            values = config_by_provider.get(provider, {})
            enabled = values.get("credential_pool_enabled", "false").strip().lower() == "true"
            mode = values.get("credential_pool_concurrency_mode", "shared").strip().lower()
            if mode not in ("shared", "separate"):
                mode = "shared"
            summaries[provider] = CredentialPoolSummary(
                enabled=enabled,
                concurrency_mode=mode,  # type: ignore[arg-type]
                enabled_credentials_count=int(enabled_counts.get(provider, 0)),
                active_lease_count=int(active_counts.get(provider, 0)),
            )
        return summaries

    async def find_full_providers(
        self,
        media_type: str,
        providers: list[str] | tuple[str, ...] | set[str] | None = None,
    ) -> set[str]:
        summaries = await self.list_pool_summaries(providers)
        full: set[str] = set()
        for provider, summary in summaries.items():
            if not summary.enabled:
                continue
            if summary.enabled_credentials_count <= 0:
                full.add(provider)
                continue
            if not await self._has_idle_credential(provider, media_type, summary.concurrency_mode):
                full.add(provider)
        return full

    async def acquire_lease(self, provider: str, media_type: str, task_id: str, owner_id: str) -> CredentialLeaseResult:
        settings = await self.get_pool_settings(provider)
        if not settings.enabled:
            return CredentialLeaseResult(acquired=False, reason="pool_disabled")

        candidate_rows = await self.session.execute(
            select(ProviderCredential)
            .where(
                ProviderCredential.provider == provider,
                ProviderCredential.is_enabled == True,  # noqa: E712
            )
            .order_by(
                ProviderCredential.last_leased_at.is_not(None),
                ProviderCredential.last_leased_at.asc(),
                ProviderCredential.id.asc(),
            )
        )
        candidates = list(candidate_rows.scalars().all())
        if not candidates:
            return CredentialLeaseResult(acquired=False, reason="waiting_for_credential")

        now = utc_now()
        for credential in candidates:
            if await self._credential_active_count(credential.id, media_type, settings.concurrency_mode) >= 1:
                continue
            lease = ProviderCredentialLease(
                task_id=task_id,
                provider=provider,
                credential_id=credential.id,
                media_type=media_type,
                status="active",
                owner_id=owner_id,
                acquired_at=now,
            )
            self.session.add(lease)
            credential.last_leased_at = now
            await self.session.execute(
                update(Task)
                .where(Task.task_id == task_id)
                .values(credential_id=credential.id, wait_reason=None, updated_at=now)
            )
            try:
                await self.session.flush()
            except IntegrityError:
                await self.session.rollback()
                return CredentialLeaseResult(acquired=False, reason="credential_lease_conflict")
            return CredentialLeaseResult(acquired=True, credential_id=credential.id)

        return CredentialLeaseResult(acquired=False, reason="waiting_for_credential")

    async def release_lease(self, task_id: str, reason: str) -> bool:
        now = utc_now()
        result = await self.session.execute(
            update(ProviderCredentialLease)
            .where(ProviderCredentialLease.task_id == task_id, ProviderCredentialLease.status == "active")
            .values(status="released", released_at=now, release_reason=reason, updated_at=now)
        )
        await self.session.flush()
        return rowcount(result) > 0

    async def active_lease_counts_by_credential(self, credential_ids: list[int] | set[int]) -> dict[int, int]:
        if not credential_ids:
            return {}
        rows = await self.session.execute(
            select(ProviderCredentialLease.credential_id, func.count(ProviderCredentialLease.id))
            .where(
                ProviderCredentialLease.credential_id.in_(set(credential_ids)),
                ProviderCredentialLease.status == "active",
            )
            .group_by(ProviderCredentialLease.credential_id)
        )
        return {int(credential_id): int(count) for credential_id, count in rows.all()}

    async def has_active_or_resumable_work(self, credential_id: int) -> bool:
        lease_rows = await self.session.execute(
            select(ProviderCredentialLease.id)
            .where(
                ProviderCredentialLease.credential_id == credential_id,
                ProviderCredentialLease.status == "active",
            )
            .limit(1)
        )
        if lease_rows.first() is not None:
            return True

        task_rows = await self.session.execute(
            select(Task.task_id)
            .where(
                Task.credential_id == credential_id,
                Task.status.in_(("queued", "running", "cancelling")),
            )
            .limit(1)
        )
        if task_rows.first() is not None:
            return True

        binding_rows = await self.session.execute(
            select(ProviderJobBinding.id)
            .join(Task, Task.task_id == ProviderJobBinding.task_id)
            .where(
                ProviderJobBinding.credential_id == credential_id,
                Task.status.in_(("queued", "running", "cancelling")),
            )
            .limit(1)
        )
        return binding_rows.first() is not None

    async def recover_leases(self, limit: int = 500) -> int:
        limit = max(1, min(limit, 5000))
        rows = await self.session.execute(
            select(ProviderCredentialLease)
            .where(ProviderCredentialLease.status == "active")
            .order_by(ProviderCredentialLease.updated_at.asc())
            .limit(limit)
        )
        leases = list(rows.scalars().all())
        recovered = 0
        now = utc_now()
        for lease in leases:
            task = await self.session.get(Task, lease.task_id)
            if task is None or task.status in ("succeeded", "failed", "cancelled"):
                should_release = True
            elif task.status == "queued":
                binding = await self._get_binding_for_task(lease.task_id)
                should_release = binding is None
            else:
                should_release = False

            if not should_release:
                continue
            lease.status = "released"
            lease.released_at = now
            lease.release_reason = "recovered"
            lease.updated_at = now
            recovered += 1
        await self.session.flush()
        return recovered

    async def _has_idle_credential(
        self,
        provider: str,
        media_type: str,
        concurrency_mode: CredentialPoolConcurrencyMode,
    ) -> bool:
        rows = await self.session.execute(
            select(ProviderCredential.id).where(
                ProviderCredential.provider == provider,
                ProviderCredential.is_enabled == True,  # noqa: E712
            )
        )
        credential_ids = [row[0] for row in rows.all()]
        for credential_id in credential_ids:
            if await self._credential_active_count(credential_id, media_type, concurrency_mode) < 1:
                return True
        return False

    async def _credential_active_count(
        self,
        credential_id: int,
        media_type: str,
        concurrency_mode: CredentialPoolConcurrencyMode,
    ) -> int:
        conditions = [
            ProviderCredentialLease.credential_id == credential_id,
            ProviderCredentialLease.status == "active",
        ]
        if concurrency_mode == "separate":
            conditions.append(ProviderCredentialLease.media_type == media_type)
        result = await self.session.execute(
            select(func.count()).select_from(ProviderCredentialLease).where(*conditions)
        )
        return int(result.scalar_one())

    async def _get_binding_for_task(self, task_id: str) -> ProviderJobBinding | None:
        result = await self.session.execute(select(ProviderJobBinding).where(ProviderJobBinding.task_id == task_id))
        return result.scalar_one_or_none()


for _code in (
    "waiting_for_credential",
    "credential_lease_conflict",
):
    assert _code in FAILURE_CODE_KEYS
