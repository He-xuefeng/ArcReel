import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { API } from "@/api";
import type { ProviderConfigDetail } from "@/types";

import { ProviderDetail } from "./ProviderDetail";

vi.mock("@/components/ui/ProviderIcon", () => ({
  ProviderIcon: () => <span data-testid="provider-icon" />,
}));

const credentialListMock = vi.fn((props: { refreshKey?: number; poolEnabled?: boolean }) => (
  <div data-testid="credential-list" data-refresh-key={props.refreshKey} data-pool-enabled={String(props.poolEnabled)} />
));

vi.mock("@/components/pages/CredentialList", () => ({
  CredentialList: (props: { refreshKey?: number; poolEnabled?: boolean }) => credentialListMock(props),
}));

const providerDetail = (overrides: Partial<ProviderConfigDetail> = {}): ProviderConfigDetail => ({
  id: "dashscope",
  display_name: "DashScope",
  description: "test provider",
  status: "ready",
  media_types: ["image", "video"],
  fields: [],
  credential_pool_enabled: false,
  credential_pool_concurrency_mode: "shared",
  credential_pool_summary: {
    enabled_credentials_count: 0,
    active_lease_count: 0,
  },
  supports_base_url: false,
  secret_fields: [{ key: "api_key", label: "API Key" }],
  secret_field_groups: [["api_key"]],
  ...overrides,
});

describe("pages/ProviderDetail credential pool controls", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    credentialListMock.mockClear();
  });

  it("patches pool enabled and refreshes provider plus credential list", async () => {
    const getConfig = vi.spyOn(API, "getProviderConfig")
      .mockResolvedValueOnce(providerDetail())
      .mockResolvedValueOnce(providerDetail({
        credential_pool_enabled: true,
        credential_pool_summary: { enabled_credentials_count: 1, active_lease_count: 0 },
      }));
    const patch = vi.spyOn(API, "patchProviderConfig").mockResolvedValue(undefined);

    render(<ProviderDetail providerId="dashscope" />);

    const toggle = await screen.findByRole("checkbox", { name: /启用凭证池化/ });
    fireEvent.click(toggle);

    await waitFor(() => {
      expect(patch).toHaveBeenCalledWith("dashscope", { credential_pool_enabled: true });
      expect(getConfig).toHaveBeenCalledTimes(2);
    });
    await waitFor(() => {
      expect(screen.getByTestId("credential-list")).toHaveAttribute("data-refresh-key", "1");
      expect(screen.getByTestId("credential-list")).toHaveAttribute("data-pool-enabled", "true");
    });
  });

  it("refreshes backend state after a pool patch failure", async () => {
    const getConfig = vi.spyOn(API, "getProviderConfig")
      .mockResolvedValueOnce(providerDetail())
      .mockResolvedValueOnce(providerDetail());
    vi.spyOn(API, "patchProviderConfig").mockRejectedValue(new Error("保存失败"));

    render(<ProviderDetail providerId="dashscope" />);

    fireEvent.click(await screen.findByRole("checkbox", { name: /启用凭证池化/ }));

    expect(await screen.findByText("保存失败")).toBeInTheDocument();
    await waitFor(() => {
      expect(getConfig).toHaveBeenCalledTimes(2);
      expect(screen.getByTestId("credential-list")).toHaveAttribute("data-refresh-key", "1");
    });
  });

  it("shows a warning when pooling is enabled but no credentials participate", async () => {
    vi.spyOn(API, "getProviderConfig").mockResolvedValue(providerDetail({ credential_pool_enabled: true }));

    render(<ProviderDetail providerId="dashscope" />);

    expect(await screen.findByText("当前没有可用池化凭证。")).toBeInTheDocument();
  });
});
