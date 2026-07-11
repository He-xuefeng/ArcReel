"""供应商凭证管理 API 测试。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from lib.db import get_async_session
from lib.db.models.credential import ProviderCredential
from lib.db.repositories.credential_repository import CredentialRepository
from server.routers import providers


@pytest.fixture(autouse=True)
def _mock_pool_repo(monkeypatch):
    repo = MagicMock()
    repo.list_pool_summaries = AsyncMock(return_value={})
    repo.active_lease_counts_by_credential = AsyncMock(return_value={})
    repo.has_active_or_resumable_work = AsyncMock(return_value=False)
    monkeypatch.setattr(providers, "CredentialPoolRepository", lambda _session: repo)
    return repo


def _make_app() -> tuple[FastAPI, MagicMock]:
    app = FastAPI()
    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()

    async def _override():
        yield mock_session

    app.dependency_overrides[get_async_session] = _override
    app.include_router(providers.router, prefix="/api/v1")
    return app, mock_session


def _fake_cred(
    id: int = 1,
    provider: str = "gemini-aistudio",
    name: str = "测试Key",
    api_key: str = "AIzaSyFAKE12345678",
    is_active: bool = True,
    base_url: str | None = None,
    credentials_path: str | None = None,
    is_enabled: bool = False,
) -> ProviderCredential:
    cred = ProviderCredential(
        provider=provider,
        name=name,
        api_key=api_key,
        is_active=is_active,
        base_url=base_url,
        credentials_path=credentials_path,
        is_enabled=is_enabled,
    )
    cred.id = id
    cred.created_at = datetime.now(UTC)
    cred.updated_at = datetime.now(UTC)
    return cred


class TestListCredentials:
    def test_returns_200(self):
        app, _ = _make_app()
        mock_repo = MagicMock(spec=CredentialRepository)
        mock_repo.list_by_provider = AsyncMock(return_value=[_fake_cred()])
        with patch("server.routers.providers.CredentialRepository", return_value=mock_repo):
            with TestClient(app) as client:
                resp = client.get("/api/v1/providers/gemini-aistudio/credentials")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["credentials"]) == 1
        assert body["credentials"][0]["name"] == "测试Key"
        assert body["credentials"][0]["api_key_masked"] is not None
        assert "FAKE" not in body["credentials"][0]["api_key_masked"]
        assert body["credentials"][0]["is_enabled"] is False
        assert body["credentials"][0]["active_lease_count"] == 0

    def test_returns_pool_fields(self, _mock_pool_repo):
        app, _ = _make_app()
        mock_repo = MagicMock(spec=CredentialRepository)
        mock_repo.list_by_provider = AsyncMock(return_value=[_fake_cred(id=7, is_enabled=True)])
        _mock_pool_repo.active_lease_counts_by_credential = AsyncMock(return_value={7: 3})
        with patch("server.routers.providers.CredentialRepository", return_value=mock_repo):
            with TestClient(app) as client:
                resp = client.get("/api/v1/providers/gemini-aistudio/credentials")
        cred = resp.json()["credentials"][0]
        assert cred["is_enabled"] is True
        assert cred["active_lease_count"] == 3

    def test_returns_404_for_unknown_provider(self):
        app, _ = _make_app()
        with TestClient(app) as client:
            resp = client.get("/api/v1/providers/nonexistent/credentials")
        assert resp.status_code == 404


class TestCreateCredential:
    def test_returns_201(self):
        app, _ = _make_app()
        mock_repo = MagicMock(spec=CredentialRepository)
        mock_repo.create = AsyncMock(return_value=_fake_cred())
        with patch("server.routers.providers.CredentialRepository", return_value=mock_repo):
            with TestClient(app) as client:
                resp = client.post(
                    "/api/v1/providers/gemini-aistudio/credentials",
                    json={"name": "测试Key", "api_key": "AIza-new"},
                )
        assert resp.status_code == 201
        assert mock_repo.create.await_args.kwargs["is_enabled"] is False

    def test_vertex_upload_persists_is_enabled(self, tmp_path: Path):
        app, _ = _make_app()
        mock_repo = MagicMock(spec=CredentialRepository)
        cred = _fake_cred(id=9, provider="gemini-vertex", api_key=None, credentials_path=None, is_enabled=True)
        mock_repo.create = AsyncMock(return_value=cred)
        mock_repo.update = AsyncMock()
        with (
            patch("server.routers.providers.CredentialRepository", return_value=mock_repo),
            patch("server.routers.providers.app_data_dir", return_value=tmp_path / "data"),
        ):
            with TestClient(app) as client:
                resp = client.post(
                    "/api/v1/providers/gemini-vertex/credentials/upload?name=Vertex&is_enabled=true",
                    files={"file": ("vertex.json", b'{"project_id":"demo"}', "application/json")},
                )
        assert resp.status_code == 201
        assert mock_repo.create.await_args.kwargs["is_enabled"] is True
        assert mock_repo.update.await_args.args[0] == 9
        assert "credentials_path" in mock_repo.update.await_args.kwargs

    def test_requires_name(self):
        app, _ = _make_app()
        mock_repo = MagicMock(spec=CredentialRepository)
        with patch("server.routers.providers.CredentialRepository", return_value=mock_repo):
            with TestClient(app) as client:
                resp = client.post(
                    "/api/v1/providers/gemini-aistudio/credentials",
                    json={"api_key": "AIza-new"},
                )
        assert resp.status_code == 422


def _fake_kling_cred(
    id: int = 1,
    access_key: str = "AKfake12345678",
    secret_key: str = "SKsecret87654321",
) -> ProviderCredential:
    cred = ProviderCredential(
        provider="kling",
        name="可灵账号",
        api_key=None,
        access_key=access_key,
        secret_key=secret_key,
        is_active=True,
    )
    cred.id = id
    cred.created_at = datetime.now(UTC)
    cred.updated_at = datetime.now(UTC)
    return cred


class TestKlingTwoSecretCredential:
    def test_create_persists_two_secrets(self):
        app, _ = _make_app()
        mock_repo = MagicMock(spec=CredentialRepository)
        mock_repo.create = AsyncMock(return_value=_fake_kling_cred())
        with patch("server.routers.providers.CredentialRepository", return_value=mock_repo):
            with TestClient(app) as client:
                resp = client.post(
                    "/api/v1/providers/kling/credentials",
                    json={"name": "可灵账号", "access_key": "AK-new", "secret_key": "SK-new"},
                )
        assert resp.status_code == 201
        mock_repo.create.assert_awaited_once()
        kwargs = mock_repo.create.await_args.kwargs
        assert kwargs["access_key"] == "AK-new"
        assert kwargs["secret_key"] == "SK-new"

    def test_create_strips_whitespace_from_secrets(self):
        app, _ = _make_app()
        mock_repo = MagicMock(spec=CredentialRepository)
        mock_repo.create = AsyncMock(return_value=_fake_kling_cred())
        with patch("server.routers.providers.CredentialRepository", return_value=mock_repo):
            with TestClient(app) as client:
                resp = client.post(
                    "/api/v1/providers/kling/credentials",
                    json={"name": "  可灵账号  ", "access_key": "  AK-new\n", "secret_key": "\tSK-new "},
                )
        assert resp.status_code == 201
        kwargs = mock_repo.create.await_args.kwargs
        # 粘贴密钥常带首尾空白/换行，边界处统一 strip，避免静默鉴权失败
        assert kwargs["name"] == "可灵账号"
        assert kwargs["access_key"] == "AK-new"
        assert kwargs["secret_key"] == "SK-new"

    def test_response_masks_each_secret_independently(self):
        app, _ = _make_app()
        mock_repo = MagicMock(spec=CredentialRepository)
        mock_repo.list_by_provider = AsyncMock(return_value=[_fake_kling_cred()])
        with patch("server.routers.providers.CredentialRepository", return_value=mock_repo):
            with TestClient(app) as client:
                resp = client.get("/api/v1/providers/kling/credentials")
        assert resp.status_code == 200
        cred = resp.json()["credentials"][0]
        # 两段各自独立脱敏，互不混用，且不泄漏明文
        assert cred["access_key_masked"] is not None
        assert cred["secret_key_masked"] is not None
        assert cred["access_key_masked"] != cred["secret_key_masked"]
        assert "fake" not in cred["access_key_masked"]
        assert "secret" not in cred["secret_key_masked"]
        assert cred["api_key_masked"] is None

    def test_update_persists_only_provided_secret(self):
        app, _ = _make_app()
        mock_repo = MagicMock(spec=CredentialRepository)
        mock_repo.get_by_id = AsyncMock(return_value=_fake_kling_cred())
        mock_repo.update = AsyncMock()
        with patch("server.routers.providers.CredentialRepository", return_value=mock_repo):
            with TestClient(app) as client:
                resp = client.patch(
                    "/api/v1/providers/kling/credentials/1",
                    json={"secret_key": "SK-rotated"},
                )
        assert resp.status_code == 204
        kwargs = mock_repo.update.await_args.kwargs
        assert kwargs["secret_key"] == "SK-rotated"
        assert "access_key" not in kwargs

    def test_update_persists_is_enabled(self):
        app, _ = _make_app()
        mock_repo = MagicMock(spec=CredentialRepository)
        mock_repo.get_by_id = AsyncMock(return_value=_fake_kling_cred())
        mock_repo.update = AsyncMock()
        with patch("server.routers.providers.CredentialRepository", return_value=mock_repo):
            with TestClient(app) as client:
                resp = client.patch(
                    "/api/v1/providers/kling/credentials/1",
                    json={"is_enabled": True},
                )
        assert resp.status_code == 204
        assert mock_repo.update.await_args.kwargs["is_enabled"] is True

    def test_update_strips_whitespace_and_omits_unset_secret(self):
        app, _ = _make_app()
        mock_repo = MagicMock(spec=CredentialRepository)
        mock_repo.get_by_id = AsyncMock(return_value=_fake_kling_cred())
        mock_repo.update = AsyncMock()
        with patch("server.routers.providers.CredentialRepository", return_value=mock_repo):
            with TestClient(app) as client:
                resp = client.patch(
                    "/api/v1/providers/kling/credentials/1",
                    json={"secret_key": "  SK-rotated\n"},
                )
        assert resp.status_code == 204
        kwargs = mock_repo.update.await_args.kwargs
        # 提供的密钥 strip 首尾空白；未提供的字段不进 kwargs（保留既有值）
        assert kwargs["secret_key"] == "SK-rotated"
        assert "access_key" not in kwargs


class TestActivateCredential:
    def test_returns_204(self):
        app, _ = _make_app()
        mock_repo = MagicMock(spec=CredentialRepository)
        mock_repo.get_by_id = AsyncMock(return_value=_fake_cred(provider="gemini-aistudio"))
        mock_repo.activate = AsyncMock()
        with patch("server.routers.providers.CredentialRepository", return_value=mock_repo):
            with TestClient(app) as client:
                resp = client.post("/api/v1/providers/gemini-aistudio/credentials/1/activate")
        assert resp.status_code == 204

    def test_returns_404_for_nonexistent(self):
        app, _ = _make_app()
        mock_repo = MagicMock(spec=CredentialRepository)
        mock_repo.get_by_id = AsyncMock(return_value=None)
        with patch("server.routers.providers.CredentialRepository", return_value=mock_repo):
            with TestClient(app) as client:
                resp = client.post("/api/v1/providers/gemini-aistudio/credentials/999/activate")
        assert resp.status_code == 404


class TestDeleteCredential:
    def test_returns_204(self):
        app, _ = _make_app()
        mock_repo = MagicMock(spec=CredentialRepository)
        mock_repo.get_by_id = AsyncMock(return_value=_fake_cred())
        mock_repo.delete = AsyncMock()
        with patch("server.routers.providers.CredentialRepository", return_value=mock_repo):
            with TestClient(app) as client:
                resp = client.delete("/api/v1/providers/gemini-aistudio/credentials/1")
        assert resp.status_code == 204

    def test_in_use_returns_structured_409(self, _mock_pool_repo):
        app, _ = _make_app()
        mock_repo = MagicMock(spec=CredentialRepository)
        mock_repo.get_by_id = AsyncMock(return_value=_fake_cred())
        mock_repo.delete = AsyncMock()
        _mock_pool_repo.has_active_or_resumable_work = AsyncMock(return_value=True)
        with patch("server.routers.providers.CredentialRepository", return_value=mock_repo):
            with TestClient(app) as client:
                resp = client.delete("/api/v1/providers/gemini-aistudio/credentials/1")
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "credential_in_use"
        mock_repo.delete.assert_not_awaited()
