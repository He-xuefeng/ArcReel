from __future__ import annotations

import pytest

from lib.image_backends.base import ImageCapabilityError
from server.services.generation_tasks import _TASK_CHANGE_SPECS, _TASK_EXECUTORS


def test_task_executors_registered_for_reference_video():
    assert "reference_video" in _TASK_EXECUTORS


def test_task_change_specs_registered_for_reference_video():
    spec = _TASK_CHANGE_SPECS.get("reference_video")
    assert spec is not None
    entity_type, action, _label_tpl, include_script_episode = spec
    assert entity_type == "reference_video_unit"
    assert action == "reference_video_ready"
    assert include_script_episode is True


@pytest.mark.asyncio
async def test_execute_generation_task_rejects_unknown_type():
    from server.services.generation_tasks import execute_generation_task

    with pytest.raises(ValueError, match="unsupported task_type"):
        await execute_generation_task(
            {
                "task_type": "unknown_xyz",
                "project_name": "demo",
                "resource_id": "x",
                "payload": {},
            }
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("task_type", ["storyboard", "tts", "reference_video"])
async def test_execute_generation_task_passes_credential_id_to_executor(monkeypatch, task_type):
    from server.services import generation_tasks

    seen: dict[str, object] = {}

    async def fake_executor(project_name, resource_id, payload, *, user_id, task_id=None, credential_id=None):
        seen.update(
            {
                "project_name": project_name,
                "resource_id": resource_id,
                "payload": payload,
                "user_id": user_id,
                "task_id": task_id,
                "credential_id": credential_id,
            }
        )
        return {"ok": True}

    monkeypatch.setitem(generation_tasks._TASK_EXECUTORS, task_type, fake_executor)
    monkeypatch.setattr(generation_tasks, "emit_generation_success_batch", lambda **_kwargs: None)

    result = await generation_tasks.execute_generation_task(
        {
            "task_type": task_type,
            "project_name": "demo",
            "resource_id": "resource-1",
            "payload": {"prompt": "p"},
            "user_id": "user-1",
            "task_id": "queue-task-1",
            "credential_id": 123,
        }
    )

    assert result == {"ok": True}
    assert seen == {
        "project_name": "demo",
        "resource_id": "resource-1",
        "payload": {"prompt": "p"},
        "user_id": "user-1",
        "task_id": "queue-task-1",
        "credential_id": 123,
    }


@pytest.mark.asyncio
async def test_reference_video_proxy_passes_credential_id(monkeypatch):
    from server.services import reference_video_tasks
    from server.services.generation_tasks import _execute_reference_video_task_proxy

    seen: dict[str, object] = {}

    async def fake_reference_video_task(
        project_name, resource_id, payload, *, user_id, task_id=None, credential_id=None
    ):
        seen.update(
            {
                "project_name": project_name,
                "resource_id": resource_id,
                "payload": payload,
                "user_id": user_id,
                "task_id": task_id,
                "credential_id": credential_id,
            }
        )
        return {"ok": True}

    monkeypatch.setattr(reference_video_tasks, "execute_reference_video_task", fake_reference_video_task)

    result = await _execute_reference_video_task_proxy(
        "demo",
        "E1U01",
        {"script_file": "episode_1.json"},
        user_id="user-1",
        task_id="queue-task-1",
        credential_id=321,
    )

    assert result == {"ok": True}
    assert seen == {
        "project_name": "demo",
        "resource_id": "E1U01",
        "payload": {"script_file": "episode_1.json"},
        "user_id": "user-1",
        "task_id": "queue-task-1",
        "credential_id": 321,
    }


@pytest.mark.asyncio
async def test_execute_generation_task_translates_image_endpoint_mismatch(monkeypatch):
    from server.services.generation_tasks import execute_generation_task

    async def fake_executor(*_args, **_kwargs):
        raise ImageCapabilityError("image_endpoint_mismatch_no_t2i", model="gpt-image-1")

    monkeypatch.setitem(_TASK_EXECUTORS, "storyboard", fake_executor)

    with pytest.raises(RuntimeError) as exc_info:
        await execute_generation_task(
            {
                "task_type": "storyboard",
                "project_name": "demo",
                "resource_id": "scene-1",
                "payload": {},
            }
        )

    message = str(exc_info.value)
    # 必须是已翻译的 zh 文案，而不是裸 code
    assert "image_endpoint_mismatch_no_t2i" not in message
    assert "gpt-image-1" in message
    assert "图生图" in message  # zh 文案关键字


@pytest.mark.asyncio
async def test_execute_generation_task_translates_capability_missing_i2i(monkeypatch):
    from server.services.generation_tasks import execute_generation_task

    async def fake_executor(*_args, **_kwargs):
        raise ImageCapabilityError("image_capability_missing_i2i", provider="openai", model="gpt-image-1")

    monkeypatch.setitem(_TASK_EXECUTORS, "storyboard", fake_executor)

    with pytest.raises(RuntimeError) as exc_info:
        await execute_generation_task(
            {
                "task_type": "storyboard",
                "project_name": "demo",
                "resource_id": "scene-1",
                "payload": {},
            }
        )

    message = str(exc_info.value)
    assert "image_capability_missing_i2i" not in message
    assert "openai" in message
    assert "gpt-image-1" in message


@pytest.mark.asyncio
async def test_execute_generation_task_propagates_other_exceptions(monkeypatch):
    """非 ImageCapabilityError 的异常应原样冒泡，不被 i18n 分支吞掉"""
    from server.services.generation_tasks import execute_generation_task

    async def fake_executor(*_args, **_kwargs):
        raise ValueError("unrelated business error")

    monkeypatch.setitem(_TASK_EXECUTORS, "storyboard", fake_executor)

    with pytest.raises(ValueError, match="unrelated business error"):
        await execute_generation_task(
            {
                "task_type": "storyboard",
                "project_name": "demo",
                "resource_id": "scene-1",
                "payload": {},
            }
        )
