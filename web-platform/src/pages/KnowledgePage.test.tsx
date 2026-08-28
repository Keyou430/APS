import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom/vitest";
import { describe, expect, it, vi } from "vitest";
import type { KnowledgeService } from "../api/services/knowledgeService";
import { KnowledgePage } from "./KnowledgePage";

function cache() { return { get: vi.fn(), invalidateOrganization: vi.fn(), set: vi.fn() }; }
function knowledge(overrides: Partial<KnowledgeService> = {}) { return { archiveEntry: vi.fn(async () => undefined), createEntry: vi.fn(async () => ({ id: 2, title: "新条目", type: "document" })), listCollections: vi.fn(async () => ({ items: [{ id: 11, name: "企业资料" }] })), listEntries: vi.fn(async () => ({ items: [{ id: 1, title: "员工手册", type: "document" }] })), uploadEntry: vi.fn(async () => ({ id: 3, title: "附件.pdf", type: "file" })), ...overrides } as unknown as KnowledgeService; }

describe("KnowledgePage", () => {
  it("loads entries and supports create and archive actions", async () => {
    const service = knowledge(); const user = userEvent.setup();
    render(<KnowledgePage cache={cache()} organizationId={7} service={service} />);
    expect(await screen.findByRole("heading", { name: "员工手册" })).toBeInTheDocument();
    await user.type(screen.getByLabelText("条目名称"), "新条目");
    await user.click(screen.getByRole("button", { name: "创建条目" }));
    expect(service.createEntry).toHaveBeenCalledWith({ title: "新条目", type: "document" });
    expect(await screen.findByRole("heading", { name: "新条目" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "归档 员工手册" }));
    await waitFor(() => expect(service.archiveEntry).toHaveBeenCalledWith(1));
    expect(screen.queryByRole("heading", { name: "员工手册" })).not.toBeInTheDocument();
  });

  it("shows upload progress and actionable errors", async () => {
    const service = knowledge({ uploadEntry: vi.fn(async (_form, onProgress) => { onProgress?.(50, 100); throw new Error("文件类型不支持"); }) });
    render(<KnowledgePage cache={cache()} organizationId={7} service={service} />);
    await screen.findByRole("heading", { name: "员工手册" });
    const file = new File(["data"], "附件.pdf", { type: "application/pdf" });
    fireEvent.change(screen.getByLabelText("上传文件"), { target: { files: [file] } });
    await waitFor(() => expect(service.uploadEntry).toHaveBeenCalled());
    expect(await screen.findByRole("alert")).toHaveTextContent("文件类型不支持");
  });

  it("requires and submits the selected knowledge collection", async () => {
    const service = knowledge();
    render(<KnowledgePage cache={cache()} organizationId={7} service={service} />);
    await screen.findByRole("heading", { name: "员工手册" });
    expect(screen.getByLabelText("上传文件")).toBeEnabled();
    const file = new File(["data"], "附件.pdf", { type: "application/pdf" });
    fireEvent.change(screen.getByLabelText("上传文件"), { target: { files: [file] } });
    await waitFor(() => expect(service.uploadEntry).toHaveBeenCalled());
    const [form] = (service.uploadEntry as ReturnType<typeof vi.fn>).mock.calls[0] as [FormData];
    expect(form.get("collection_id")).toBe("11");
  });
});
