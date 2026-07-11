import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { API, ApiError } from "@/api";
import type { ProviderCredential } from "@/types";

import { CredentialList } from "./CredentialList";

const mockCred = (overrides: Partial<ProviderCredential> = {}): ProviderCredential => ({
  id: 1,
  provider: "dashscope",
  name: "默认账号",
  api_key_masked: "sk-x...abcd",
  credentials_filename: null,
  base_url: null,
  is_active: false,
  is_enabled: false,
  active_lease_count: 0,
  created_at: "2026-06-01T00:00:00Z",
  ...overrides,
});

function mockEmptyList() {
  vi.spyOn(API, "listCredentials").mockResolvedValue({ credentials: [] });
}

describe("pages/CredentialList base_url gating", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders Base URL input in add form when provider supports it", async () => {
    mockEmptyList();
    render(<CredentialList providerId="dashscope" supportsBaseUrl />);

    fireEvent.click(await screen.findByRole("button", { name: /添加供应商/ }));

    expect(await screen.findByText("Base URL（可选）")).toBeInTheDocument();
  });

  it("omits Base URL input in add form when provider does not support it", async () => {
    mockEmptyList();
    render(<CredentialList providerId="ark" supportsBaseUrl={false} />);

    fireEvent.click(await screen.findByRole("button", { name: /添加供应商/ }));

    expect(await screen.findByText("名称")).toBeInTheDocument();
    expect(screen.queryByText("Base URL（可选）")).not.toBeInTheDocument();
  });

  it("renders Base URL input in edit form when provider supports it", async () => {
    vi.spyOn(API, "listCredentials").mockResolvedValue({ credentials: [mockCred()] });
    render(<CredentialList providerId="dashscope" supportsBaseUrl />);

    fireEvent.click(await screen.findByRole("button", { name: /编辑 默认账号/ }));

    expect(await screen.findByText("Base URL（可选）")).toBeInTheDocument();
  });
});

describe("pages/CredentialList two-secret (Kling)", () => {
  const KLING_SECRET_FIELDS = [
    { key: "access_key", label: "Access Key" },
    { key: "secret_key", label: "Secret Key" },
  ];

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders two secret inputs in the add form by required_keys", async () => {
    mockEmptyList();
    render(
      <CredentialList providerId="kling" supportsBaseUrl secretFields={KLING_SECRET_FIELDS} />,
    );

    fireEvent.click(await screen.findByRole("button", { name: /添加供应商/ }));

    expect(await screen.findByLabelText(/Access Key/)).toBeInTheDocument();
    expect(await screen.findByLabelText(/Secret Key/)).toBeInTheDocument();
  });

  it("submits both secrets on create", async () => {
    mockEmptyList();
    const createSpy = vi.spyOn(API, "createCredential").mockResolvedValue({} as never);
    render(
      <CredentialList providerId="kling" supportsBaseUrl={false} secretFields={KLING_SECRET_FIELDS} />,
    );

    fireEvent.click(await screen.findByRole("button", { name: /添加供应商/ }));
    fireEvent.change(await screen.findByLabelText(/名称/), { target: { value: "可灵账号" } });
    fireEvent.change(await screen.findByLabelText(/Access Key/), { target: { value: "AK-1" } });
    fireEvent.change(await screen.findByLabelText(/Secret Key/), { target: { value: "SK-1" } });
    fireEvent.click(screen.getByRole("button", { name: /添加$/ }));

    await waitFor(() => {
      expect(createSpy).toHaveBeenCalledWith("kling", expect.objectContaining({
        name: "可灵账号",
        access_key: "AK-1",
        secret_key: "SK-1",
      }));
    });
  });

  it("trims surrounding whitespace from secrets on create", async () => {
    mockEmptyList();
    const createSpy = vi.spyOn(API, "createCredential").mockResolvedValue({} as never);
    render(
      <CredentialList providerId="kling" supportsBaseUrl={false} secretFields={KLING_SECRET_FIELDS} />,
    );

    fireEvent.click(await screen.findByRole("button", { name: /添加供应商/ }));
    fireEvent.change(await screen.findByLabelText(/名称/), { target: { value: "可灵账号" } });
    fireEvent.change(await screen.findByLabelText(/Access Key/), { target: { value: "  AK-1\n" } });
    fireEvent.change(await screen.findByLabelText(/Secret Key/), { target: { value: "\tSK-1 " } });
    fireEvent.click(screen.getByRole("button", { name: /添加$/ }));

    await waitFor(() => {
      expect(createSpy).toHaveBeenCalledWith("kling", expect.objectContaining({
        access_key: "AK-1",
        secret_key: "SK-1",
      }));
    });
  });

  it("does not overwrite a stored secret with a whitespace-only edit", async () => {
    vi.spyOn(API, "listCredentials").mockResolvedValue({
      credentials: [
        mockCred({
          id: 7,
          provider: "kling",
          name: "可灵账号",
          api_key_masked: null,
          access_key_masked: "AKfa...678",
          secret_key_masked: "SKse...321",
          is_active: true,
        }),
      ],
    });
    const updateSpy = vi.spyOn(API, "updateCredential").mockResolvedValue({} as never);
    render(
      <CredentialList providerId="kling" supportsBaseUrl={false} secretFields={KLING_SECRET_FIELDS} />,
    );

    fireEvent.click(await screen.findByRole("button", { name: /编辑 可灵账号/ }));
    fireEvent.change(await screen.findByLabelText(/Secret Key/), { target: { value: "   " } });
    fireEvent.click(screen.getByRole("button", { name: /保存/ }));

    await waitFor(() => {
      expect(updateSpy).not.toHaveBeenCalled();
    });
  });

  it("shows each masked secret independently in the row", async () => {
    vi.spyOn(API, "listCredentials").mockResolvedValue({
      credentials: [
        mockCred({
          id: 7,
          provider: "kling",
          name: "可灵账号",
          api_key_masked: null,
          access_key_masked: "AKfa...678",
          secret_key_masked: "SKse...321",
          is_active: true,
        }),
      ],
    });
    render(
      <CredentialList providerId="kling" supportsBaseUrl={false} secretFields={KLING_SECRET_FIELDS} />,
    );

    expect(await screen.findByText(/AKfa...678/)).toBeInTheDocument();
    expect(await screen.findByText(/SKse...321/)).toBeInTheDocument();
  });
});

describe("pages/CredentialList credential groups (api_key OR access_key+secret_key)", () => {
  const KLING_SECRET_FIELDS = [
    { key: "api_key", label: "API Key" },
    { key: "access_key", label: "Access Key" },
    { key: "secret_key", label: "Secret Key" },
  ];
  const KLING_SECRET_FIELD_GROUPS = [["api_key"], ["access_key", "secret_key"]];

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("shows an OR hint describing the two credential groups", async () => {
    mockEmptyList();
    render(
      <CredentialList
        providerId="kling"
        supportsBaseUrl
        secretFields={KLING_SECRET_FIELDS}
        secretFieldGroups={KLING_SECRET_FIELD_GROUPS}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: /添加供应商/ }));

    expect(await screen.findByText("API Key 或 Access Key + Secret Key")).toBeInTheDocument();
  });

  it("renders all three secret inputs regardless of grouping", async () => {
    mockEmptyList();
    render(
      <CredentialList
        providerId="kling"
        supportsBaseUrl
        secretFields={KLING_SECRET_FIELDS}
        secretFieldGroups={KLING_SECRET_FIELD_GROUPS}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: /添加供应商/ }));

    expect(await screen.findByLabelText(/^API Key/)).toBeInTheDocument();
    expect(await screen.findByLabelText(/Access Key/)).toBeInTheDocument();
    expect(await screen.findByLabelText(/Secret Key/)).toBeInTheDocument();
  });

  it("submits with only api_key filled", async () => {
    mockEmptyList();
    const createSpy = vi.spyOn(API, "createCredential").mockResolvedValue({} as never);
    render(
      <CredentialList
        providerId="kling"
        supportsBaseUrl={false}
        secretFields={KLING_SECRET_FIELDS}
        secretFieldGroups={KLING_SECRET_FIELD_GROUPS}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: /添加供应商/ }));
    fireEvent.change(await screen.findByLabelText(/名称/), { target: { value: "可灵账号" } });
    fireEvent.change(await screen.findByLabelText(/^API Key/), { target: { value: "sk-api-1" } });
    fireEvent.click(screen.getByRole("button", { name: /添加$/ }));

    await waitFor(() => {
      expect(createSpy).toHaveBeenCalledWith(
        "kling",
        expect.objectContaining({ name: "可灵账号", api_key: "sk-api-1" }),
      );
    });
  });

  it("submits with only access_key+secret_key filled", async () => {
    mockEmptyList();
    const createSpy = vi.spyOn(API, "createCredential").mockResolvedValue({} as never);
    render(
      <CredentialList
        providerId="kling"
        supportsBaseUrl={false}
        secretFields={KLING_SECRET_FIELDS}
        secretFieldGroups={KLING_SECRET_FIELD_GROUPS}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: /添加供应商/ }));
    fireEvent.change(await screen.findByLabelText(/名称/), { target: { value: "可灵账号" } });
    fireEvent.change(await screen.findByLabelText(/Access Key/), { target: { value: "AK-1" } });
    fireEvent.change(await screen.findByLabelText(/Secret Key/), { target: { value: "SK-1" } });
    fireEvent.click(screen.getByRole("button", { name: /添加$/ }));

    await waitFor(() => {
      expect(createSpy).toHaveBeenCalledWith(
        "kling",
        expect.objectContaining({ name: "可灵账号", access_key: "AK-1", secret_key: "SK-1" }),
      );
    });
  });

  it("rejects submit when no group is fully filled", async () => {
    mockEmptyList();
    const createSpy = vi.spyOn(API, "createCredential").mockResolvedValue({} as never);
    render(
      <CredentialList
        providerId="kling"
        supportsBaseUrl={false}
        secretFields={KLING_SECRET_FIELDS}
        secretFieldGroups={KLING_SECRET_FIELD_GROUPS}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: /添加供应商/ }));
    fireEvent.change(await screen.findByLabelText(/名称/), { target: { value: "可灵账号" } });
    fireEvent.change(await screen.findByLabelText(/Access Key/), { target: { value: "AK-1" } });
    fireEvent.click(screen.getByRole("button", { name: /添加$/ }));

    expect(await screen.findByText("请至少完整填写一组鉴权字段")).toBeInTheDocument();
    expect(createSpy).not.toHaveBeenCalled();
  });

  it("does not mark any single field as required when multiple groups exist", async () => {
    mockEmptyList();
    render(
      <CredentialList
        providerId="kling"
        supportsBaseUrl={false}
        secretFields={KLING_SECRET_FIELDS}
        secretFieldGroups={KLING_SECRET_FIELD_GROUPS}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: /添加供应商/ }));
    await screen.findByLabelText(/^API Key/);

    expect(screen.getAllByText("*")).toHaveLength(1);
  });
});

describe("pages/CredentialList credential pooling", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("keeps active radio semantics when pooling is disabled", async () => {
    vi.spyOn(API, "listCredentials").mockResolvedValue({ credentials: [mockCred()] });
    render(<CredentialList providerId="dashscope" supportsBaseUrl={false} poolEnabled={false} />);

    expect(await screen.findByRole("button", { name: /激活 默认账号/ })).toBeInTheDocument();
    expect(screen.queryByText("参与池化")).not.toBeInTheDocument();
  });

  it("shows pool participation controls and default badge when pooling is enabled", async () => {
    vi.spyOn(API, "listCredentials").mockResolvedValue({
      credentials: [mockCred({ is_active: true, is_enabled: true, active_lease_count: 2 })],
    });
    render(<CredentialList providerId="dashscope" supportsBaseUrl={false} poolEnabled poolConcurrencyMode="shared" />);

    expect(await screen.findByRole("checkbox", { name: /让 默认账号 参与池化/ })).toBeChecked();
    expect(screen.getByText("默认")).toBeInTheDocument();
    expect(screen.getByText("2 个租约")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /激活 默认账号/ })).not.toBeInTheDocument();
  });

  it("patches pool participation idempotently", async () => {
    vi.spyOn(API, "listCredentials").mockResolvedValue({ credentials: [mockCred()] });
    const updateSpy = vi.spyOn(API, "updateCredential").mockResolvedValue(undefined);
    render(<CredentialList providerId="dashscope" supportsBaseUrl={false} poolEnabled />);

    fireEvent.click(await screen.findByRole("checkbox", { name: /让 默认账号 参与池化/ }));

    await waitFor(() => {
      expect(updateSpy).toHaveBeenCalledWith("dashscope", 1, { is_enabled: true });
    });
  });

  it("shows no-enabled warning when pooling has credentials but none participate", async () => {
    vi.spyOn(API, "listCredentials").mockResolvedValue({ credentials: [mockCred()] });
    render(<CredentialList providerId="dashscope" supportsBaseUrl={false} poolEnabled />);

    expect(await screen.findByText("当前没有可用池化凭证。")).toBeInTheDocument();
  });

  it("creates a new credential as non-participating by default when pooling is enabled", async () => {
    mockEmptyList();
    const createSpy = vi.spyOn(API, "createCredential").mockResolvedValue({} as never);
    render(<CredentialList providerId="dashscope" supportsBaseUrl={false} poolEnabled />);

    fireEvent.click(await screen.findByRole("button", { name: /添加供应商/ }));
    expect(screen.getByLabelText("参与池化")).not.toBeChecked();
    fireEvent.change(await screen.findByLabelText(/名称/), { target: { value: "新账号" } });
    fireEvent.change(await screen.findByLabelText(/^API Key/), { target: { value: "sk-new" } });
    fireEvent.click(screen.getByRole("button", { name: /添加$/ }));

    await waitFor(() => {
      expect(createSpy).toHaveBeenCalledWith("dashscope", expect.objectContaining({
        name: "新账号",
        api_key: "sk-new",
        is_enabled: false,
      }));
    });
  });

  it("shows a localized credential-in-use message when delete returns 409 code", async () => {
    vi.spyOn(API, "listCredentials").mockResolvedValue({ credentials: [mockCred()] });
    vi.spyOn(API, "deleteCredential").mockRejectedValue(new ApiError("server detail", "credential_in_use", 409));
    render(<CredentialList providerId="dashscope" supportsBaseUrl={false} poolEnabled />);

    fireEvent.click(await screen.findByRole("button", { name: /删除 默认账号/ }));
    fireEvent.click(screen.getByRole("button", { name: /确认/ }));

    expect(await screen.findByText("凭证仍有关联运行中或可恢复任务，无法删除。")).toBeInTheDocument();
  });
});
