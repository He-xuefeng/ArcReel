"""Generation task backend cache tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from server.services import generation_tasks


class _Resolver:
    pass


@pytest.fixture(autouse=True)
def clear_backend_cache():
    generation_tasks.invalidate_backend_cache()
    yield
    generation_tasks.invalidate_backend_cache()


async def test_backend_cache_is_partitioned_by_credential_id(monkeypatch):
    calls: list[tuple[str, int | None]] = []

    async def fake_assemble_backend(**kwargs):
        calls.append((kwargs["provider_id"], kwargs.get("credential_id")))
        return SimpleNamespace(credential_id=kwargs.get("credential_id"))

    monkeypatch.setattr(generation_tasks, "assemble_backend", fake_assemble_backend)

    first = await generation_tasks._get_or_create_image_backend(
        "ark",
        {"model": "doubao-x"},
        _Resolver(),
        credential_id=1,
    )
    first_again = await generation_tasks._get_or_create_image_backend(
        "ark",
        {"model": "doubao-x"},
        _Resolver(),
        credential_id=1,
    )
    second = await generation_tasks._get_or_create_image_backend(
        "ark",
        {"model": "doubao-x"},
        _Resolver(),
        credential_id=2,
    )
    active_path = await generation_tasks._get_or_create_image_backend(
        "ark",
        {"model": "doubao-x"},
        _Resolver(),
        credential_id=None,
    )

    assert first is first_again
    assert first is not second
    assert first is not active_path
    assert [credential_id for _, credential_id in calls] == [1, 2, None]


async def test_video_backend_passes_credential_id_to_assembly(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_assemble_backend(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(generation_tasks, "assemble_backend", fake_assemble_backend)

    await generation_tasks._get_or_create_video_backend(
        "ark",
        {"model": "seedance"},
        _Resolver(),
        credential_id=42,
    )

    assert captured["credential_id"] == 42
