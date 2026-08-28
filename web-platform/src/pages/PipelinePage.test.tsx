import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom/vitest";
import { describe, expect, it, vi } from "vitest";
import type { PipelineService } from "../api/services/pipelineService";
import { PipelinePage } from "./PipelinePage";

function createCache() {
  return {
    get: vi.fn(),
    invalidateOrganization: vi.fn(),
    set: vi.fn(),
  };
}

function createService(
  overrides: Partial<PipelineService> = {},
): PipelineService {
  return {
    approveDecision: vi.fn(async (id) => ({
      id,
      status: "approved",
      title: "预算审批",
    })),
    createDraft: vi.fn(async () => ({
      id: "draft",
      title: "行业趋势日报",
      prompt: "每天17:30搜索行业趋势，整理成Markdown日报",
      task_type: "web_research",
      schedule: "30 17 * * *",
      timezone: "Asia/Shanghai",
      input_sources: ["web"],
      output_format: "markdown",
    })),
    createTask: vi.fn(async (request) => ({
      ...request,
      id: "task-created",
      status: "ready",
    })),
    downloadOutput: vi.fn(async () => new Blob(["# 周报"], { type: "text/markdown" })),
    getOutput: vi.fn(async () => ({
      id: "output-1",
      markdown: "# 周报\n[项目链接](https://example.com)",
      title: "周报草稿",
    })),
    getRun: vi.fn(async () => ({
      id: "run-1",
      status: "completed",
      output_id: "output-1",
    })),
    getTask: vi.fn(async (id) => ({
      id,
      title: "周报生成",
      status: "ready",
      description: "生成固定模板周报",
      output_id: "output-1",
    })),
    listDecisions: vi.fn(async () => ({
      items: [
        {
          id: "decision-1",
          status: "pending",
          title: "预算审批",
          summary: "需要主管确认预算",
        },
      ],
    })),
    listTasks: vi.fn(async () => ({
      items: [
        {
          id: "task-1",
          title: "周报生成",
          status: "ready",
          description: "生成固定模板周报",
          output_id: "output-1",
        },
      ],
    })),
    releaseRunIntent: vi.fn(),
    requestChanges: vi.fn(async (id) => ({
      id,
      status: "changes_requested",
      title: "预算审批",
    })),
    runTask: vi.fn(async () => ({
      id: "run-1",
      status: "queued",
      output_id: "output-1",
    })),
    ...overrides,
  } as PipelineService;
}

describe("PipelinePage", () => {
  it("creates a confirmed task from an AI-generated draft and refreshes the list", async () => {
    const service = createService();
    const user = userEvent.setup();

    render(<PipelinePage cache={createCache()} organizationId={7} service={service} />);

    await user.type(
      await screen.findByLabelText("任务描述"),
      "每天17:30搜索行业趋势，整理成Markdown日报",
    );
    await user.click(screen.getByRole("button", { name: "生成任务草稿" }));

    await user.clear(await screen.findByLabelText("任务标题"));
    await user.type(screen.getByLabelText("任务标题"), "行业趋势工作日报");
    await user.selectOptions(screen.getByLabelText("审批人"), "role");
    await user.type(screen.getByLabelText("审批角色"), "admin");
    await user.type(screen.getByLabelText("升级角色"), "admin");
    await user.click(screen.getByRole("button", { name: "确认创建任务" }));

    expect(service.createDraft).toHaveBeenCalledWith({
      prompt: "每天17:30搜索行业趋势，整理成Markdown日报",
    });
    expect(service.createTask).toHaveBeenCalledWith(
      expect.objectContaining({
        confirmed: true,
        title: "行业趋势工作日报",
        schedule: "30 17 * * *",
        approval_assignee_type: "role",
        approval_role_name: "admin",
        approval_escalation_role_name: "admin",
      }),
    );
    await waitFor(() => expect(service.listTasks).toHaveBeenCalledTimes(2));
  });

  it("loads tasks, detail, decisions and markdown output for the current organization", async () => {
    const cache = createCache();
    const service = createService();

    render(<PipelinePage cache={cache} organizationId={7} service={service} />);

    expect(screen.getByText("正在加载 Pipeline")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Pipeline" })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "周报生成" })).toBeInTheDocument();
    expect(screen.getByText("生成固定模板周报")).toBeInTheDocument();
    expect(screen.getByText("预算审批")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "周报草稿" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "项目链接" })).toHaveAttribute(
      "href",
      "https://example.com",
    );
    expect(service.listTasks).toHaveBeenCalledWith({ limit: 20 });
    expect(service.getTask).toHaveBeenCalledWith("task-1");
    expect(service.listDecisions).toHaveBeenCalledWith();
    expect(service.getOutput).toHaveBeenCalledWith("output-1");
    expect(cache.get).toHaveBeenCalledWith(7, ["pipeline", "tasks"]);
    expect(cache.set).toHaveBeenCalledWith(7, ["pipeline", "tasks"], expect.any(Array));
  });

  it("runs the selected task and refreshes the output", async () => {
    const service = createService({
      getRun: vi.fn(async () => ({
        id: "run-1",
        status: "completed",
        output_id: "output-2",
      })),
      getOutput: vi.fn(async (id) => ({
        id,
        markdown: "## 更新后的周报",
        title: "更新后的周报",
      })),
    });
    const user = userEvent.setup();

    render(<PipelinePage cache={createCache()} organizationId={7} service={service} />);

    await screen.findByRole("button", { name: "运行任务" });
    await user.click(screen.getByRole("button", { name: "运行任务" }));

    await waitFor(() => expect(service.runTask).toHaveBeenCalledWith("task-1"));
    expect(service.getRun).toHaveBeenCalledWith("run-1");
    expect(await screen.findByRole("heading", { name: "更新后的周报" })).toBeInTheDocument();
  });

  it("shows an in-progress notice instead of faking completion when polling times out", async () => {
    const service = createService({
      getRun: vi.fn(async () => ({
        id: "run-1",
        status: "running",
        output_id: null,
      })),
    });

    render(<PipelinePage cache={createCache()} organizationId={7} service={service} />);
    const runButton = await screen.findByRole("button", { name: "运行任务" });

    vi.useFakeTimers();
    await act(async () => {
      fireEvent.click(runButton);
      await vi.runAllTimersAsync();
    });
    // Restore real timers before DOM queries: testing-library polling itself
    // relies on timers.
    vi.useRealTimers();

    const notice = await screen.findByTestId("pipeline-run-notice");
    expect(notice.textContent).toContain("执行中");
    expect(notice.textContent).toContain("running");
    expect(service.runTask).toHaveBeenCalledWith("task-1");
    expect(service.getRun).toHaveBeenCalledTimes(181);
  });

  it("handles approval and request-changes from the approval drawer", async () => {
    const service = createService();
    const user = userEvent.setup();

    render(<PipelinePage cache={createCache()} organizationId={7} service={service} />);

    await user.click(await screen.findByRole("button", { name: "查看审批" }));
    expect(screen.getByRole("dialog", { name: "审批抽屉" })).toBeInTheDocument();
    await user.type(screen.getByLabelText("同意意见（选填）"), "已核对来源，可以发布");
    await user.click(screen.getByRole("button", { name: "批准 预算审批" }));
    await user.type(screen.getByLabelText("修改说明"), "请补充数据来源");
    await user.click(screen.getByRole("button", { name: "要求修改 预算审批" }));

    expect(service.approveDecision).toHaveBeenCalledWith("decision-1", {
      comment: "已核对来源，可以发布",
    });
    expect(service.requestChanges).toHaveBeenCalledWith("decision-1", {
      reason: "请补充数据来源",
    });
  });

  it("downloads the selected markdown output", async () => {
    const service = createService();
    const user = userEvent.setup();

    render(<PipelinePage cache={createCache()} organizationId={7} service={service} />);

    await user.click(await screen.findByRole("button", { name: "下载 Markdown" }));

    expect(service.downloadOutput).toHaveBeenCalledWith("output-1");
  });

  it("fails closed when organization context is missing", async () => {
    const service = createService();

    render(<PipelinePage cache={createCache()} organizationId={null} service={service} />);

    expect(await screen.findByText("没有 Pipeline 访问权限")).toBeInTheDocument();
    expect(service.listTasks).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "刷新 Pipeline" })).toBeDisabled();
  });
});
