import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom/vitest";
import { describe, expect, it, vi } from "vitest";
import type { ChatService } from "../api/services/chatService";
import type { ChatStreamService } from "../api/services/chatStream";
import type { PipelineService } from "../api/services/pipelineService";
import { ChatPage } from "./ChatPage";

function cache() { return { get: vi.fn(), invalidateOrganization: vi.fn(), set: vi.fn() }; }
function chat(overrides: Partial<ChatService> = {}) { return { createSession: vi.fn(async () => ({ id: 2, title: "新会话" })), getMessages: vi.fn(async () => ({ items: [] })), listSessions: vi.fn(async () => ({ items: [{ id: 1, title: "客户分析" }] })), ...overrides } as unknown as ChatService; }
function stream(response: unknown = { ok: true, text: async () => "event: response.output_text.delta\ndata: {\"delta\":\"你好\"}\n\nevent: response.completed\ndata: {}" }) { return { sendMessageStream: vi.fn(async () => response) } as unknown as ChatStreamService; }
function pipeline(overrides: Partial<PipelineService> = {}) { return { createTask: vi.fn(async () => ({ id: 55, title: "AI 周报" })), runTask: vi.fn(async () => ({ id: 77, status: "queued" })), releaseRunIntent: vi.fn(), ...overrides } as unknown as PipelineService; }
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => { resolve = next; });
  return { promise, resolve };
}

describe("ChatPage", () => {
  it("loads sessions and history, then sends a streaming message", async () => {
    const service = chat({ getMessages: vi.fn(async () => ({ items: [{ id: "m1", role: "assistant", content: "历史回复" }] })) });
    const user = userEvent.setup();
    render(<ChatPage cache={cache()} organizationId={7} pipeline={pipeline()} service={service} stream={stream()} />);
    expect(await screen.findByText("历史回复")).toBeInTheDocument();
    expect(service.listSessions).toHaveBeenCalledWith({ surface: "agent" });
    await user.type(screen.getByLabelText("消息"), "你好");
    await user.click(screen.getByRole("button", { name: "发送" }));
    expect(screen.getAllByText("你好").length).toBeGreaterThanOrEqual(2);
  });

  it("keeps session B history when session A history resolves late", async () => {
    const aHistory = deferred<Record<string, unknown>>();
    const bHistory = deferred<Record<string, unknown>>();
    const service = chat({
      listSessions: vi.fn(async () => ({ items: [{ id: 1, title: "会话 A" }, { id: 2, title: "会话 B" }] })),
      getMessages: vi.fn((sessionId) => sessionId === "1" ? aHistory.promise : bHistory.promise),
    });
    const user = userEvent.setup();
    render(<ChatPage cache={cache()} organizationId={7} pipeline={pipeline()} service={service} stream={stream()} />);

    await user.click(await screen.findByRole("button", { name: "会话 B" }));
    await act(async () => { bHistory.resolve({ items: [{ id: "b1", role: "assistant", content: "B 的历史" }] }); });
    expect(await screen.findByText("B 的历史")).toBeInTheDocument();

    await act(async () => { aHistory.resolve({ items: [{ id: "a1", role: "assistant", content: "A 的迟到历史" }] }); });
    await waitFor(() => expect(screen.getByText("B 的历史")).toBeInTheDocument());
    expect(screen.queryByText("A 的迟到历史")).not.toBeInTheDocument();
  });

  it("does not apply session A SSE events after switching to session B", async () => {
    const bHistory = deferred<Record<string, unknown>>();
    const lateStream = deferred<string>();
    const service = chat({
      listSessions: vi.fn(async () => ({ items: [{ id: 1, title: "会话 A" }, { id: 2, title: "会话 B" }] })),
      getMessages: vi.fn((sessionId) => sessionId === "1" ? Promise.resolve({ items: [] }) : bHistory.promise),
    });
    const user = userEvent.setup();
    render(<ChatPage cache={cache()} organizationId={7} pipeline={pipeline()} service={service} stream={stream({ ok: true, text: () => lateStream.promise })} />);

    await screen.findByRole("button", { name: "会话 A" });
    await user.type(screen.getByLabelText("消息"), "A 的问题");
    await user.click(screen.getByRole("button", { name: "发送" }));
    await user.click(screen.getByRole("button", { name: "会话 B" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "会话 B" })).toHaveAttribute("aria-pressed", "true"));

    await act(async () => { lateStream.resolve('event: response.output_text.delta\ndata: {"delta":"A 的迟到回复"}\n\nevent: response.completed\ndata: {}'); });
    expect(screen.queryByText("A 的迟到回复")).not.toBeInTheDocument();

    await act(async () => { bHistory.resolve({ items: [{ id: "b1", role: "assistant", content: "B 的历史" }] }); });
    expect(await screen.findByText("B 的历史")).toBeInTheDocument();
  });

  it("keeps active run controls scoped to the session that started the run", async () => {
    const runCreated = deferred<void>();
    const service = chat({
      listSessions: vi.fn(async () => ({ items: [{ id: 1, title: "会话 A" }, { id: 2, title: "会话 B" }] })),
      stopRun: vi.fn(async () => ({ run_id: "run-a", status: "stopping" })),
    });
    const chatStream = {
      sendMessageStream: vi.fn(async (_sessionId, _request, options) => {
        let readCount = 0;
        return {
          ok: true,
          body: {
            getReader: () => ({
              read: async () => {
                readCount += 1;
                if (readCount === 1) {
                  runCreated.resolve();
                  return { done: false, value: new TextEncoder().encode('event: run.created\ndata: {"run_id":"run-a"}\n\n') };
                }
                return new Promise((resolve) => {
                  options.signal.addEventListener("abort", () => resolve({ done: true, value: undefined }), { once: true });
                });
              },
            }),
          },
        };
      }),
    } as unknown as ChatStreamService;
    const user = userEvent.setup();
    render(<ChatPage cache={cache()} organizationId={7} pipeline={pipeline()} service={service} stream={chatStream} />);

    await screen.findByRole("button", { name: "会话 A" });
    await user.type(screen.getByLabelText("消息"), "开始 A 运行");
    await user.click(screen.getByRole("button", { name: "发送" }));
    await runCreated.promise;
    await user.click(screen.getByRole("button", { name: "会话 B" }));
    await waitFor(() => expect(screen.getByLabelText("消息")).toBeEnabled());
    expect(screen.queryByRole("button", { name: "停止" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "会话 A" }));
    await user.click(screen.getByRole("button", { name: "停止" }));

    expect(service.stopRun).toHaveBeenCalledWith("1", "run-a");
  });

  it("keeps consecutive messages in the same window on the selected session", async () => {
    const chatStream = stream({ ok: true, text: async () => "event: response.completed\ndata: {}" });
    const user = userEvent.setup();
    render(<ChatPage cache={cache()} organizationId={7} pipeline={pipeline()} service={chat()} stream={chatStream} />);

    await screen.findByRole("button", { name: "客户分析" });
    await user.type(screen.getByLabelText("消息"), "第一条");
    await user.click(screen.getByRole("button", { name: "发送" }));
    await waitFor(() => expect(screen.getByLabelText("消息")).toBeEnabled());
    await user.type(screen.getByLabelText("消息"), "第二条");
    await user.click(screen.getByRole("button", { name: "发送" }));

    await waitFor(() => expect(chatStream.sendMessageStream).toHaveBeenCalledTimes(2));
    expect((chatStream.sendMessageStream as ReturnType<typeof vi.fn>).mock.calls.map((call) => call[0])).toEqual(["1", "1"]);
  });

  it("restores history web sources and renders only validated links", async () => {
    const service = chat({ getMessages: vi.fn(async () => ({ items: [
      { id: "m-user", role: "user", content: "最近的 AI 动态" },
      { id: "m-assistant", role: "assistant", content: "有一条动态", web_sources: [{ ordinal: 0, provider: "exa", url: "https://example.com/news", title: "可验证来源", published_at: "2026-08-22T00:00:00Z", searched_at: "2026-08-23T00:00:00Z", correlation_id: "run-1" }] },
    ] })) });
    render(<ChatPage cache={cache()} organizationId={7} pipeline={pipeline()} service={service} stream={stream()} />);
    expect(await screen.findByRole("link", { name: /可验证来源/ })).toHaveAttribute("href", "https://example.com/news");
    expect(screen.queryByTestId("freshness-evidence-notice")).not.toBeInTheDocument();
  });

  it("maps web search SSE states and keeps freshness fail-closed", async () => {
    const response = { ok: true, text: async () => [
      'event: web.search.started\ndata: {"run_id":"r1"}',
      'event: web.search.completed\ndata: {"sources":[{"url":"https://example.com/live","title":"实时来源","published_at":"2026-08-22T00:00:00Z","searched_at":"2026-08-23T00:00:00Z"}]}',
      'event: response.output_text.delta\ndata: {"delta":"最新动态"}',
      'event: response.completed\ndata: {}',
    ].join("\n\n") };
    const service = chat(); const user = userEvent.setup();
    render(<ChatPage cache={cache()} organizationId={7} pipeline={pipeline()} service={service} stream={stream(response)} />);
    await screen.findByRole("button", { name: "客户分析" });
    await user.type(screen.getByLabelText("消息"), "最近的 AI 动态");
    await user.click(screen.getByRole("button", { name: "发送" }));
    expect(await screen.findByRole("link", { name: /实时来源/ })).toHaveAttribute("href", "https://example.com/live");
    expect(screen.queryByTestId("freshness-evidence-notice")).not.toBeInTheDocument();
  });

  it("sends a client message ID and shows the platform action result", async () => {
    const response = { ok: true, text: async () => [
      'event: platform.action\ndata: {"status":"succeeded","message":"已创建定时任务并完成首次执行","task_id":12,"run_id":34}',
      'event: response.output_text.delta\ndata: {"delta":"任务已执行。"}',
      'event: response.completed\ndata: {}',
    ].join("\n\n") };
    const service = chat(); const user = userEvent.setup(); const chatStream = stream(response);
    render(<ChatPage cache={cache()} organizationId={7} pipeline={pipeline()} service={service} stream={chatStream} />);
    await screen.findByRole("button", { name: "客户分析" });
    await user.type(screen.getByLabelText("消息"), "创建每日定时任务并立即执行一次");
    await user.click(screen.getByRole("button", { name: "发送" }));

    expect(await screen.findByTestId("chat-platform-action")).toHaveTextContent("已创建定时任务并完成首次执行");
    expect(screen.getByTestId("chat-platform-action")).toHaveTextContent("任务 #12");
    expect((chatStream.sendMessageStream as ReturnType<typeof vi.fn>).mock.calls[0]?.[1]).toMatchObject({
      client_message_id: expect.stringMatching(/^m_/),
      content: "创建每日定时任务并立即执行一次",
    });
  });

  it("edits the complete chat schedule draft before creating and running the task", async () => {
    const response = { ok: true, text: async () => [
      'event: platform.action\ndata: {"status":"draft","message":"已生成定时任务草稿","run_now":true,"draft":{"title":"AI 周报","prompt":"汇总 AI 动态","task_type":"web_research","schedule":null,"timezone":"Asia/Shanghai","input_sources":[],"output_format":"markdown","approval_required":true,"approval_assignee_type":"creator","approval_reminder_after_minutes":1440,"approval_escalation_after_minutes":2880}}',
      'event: response.completed\ndata: {}',
    ].join("\n\n") };
    const pipelineService = pipeline();
    const user = userEvent.setup();
    render(<ChatPage cache={cache()} organizationId={7} pipeline={pipelineService} service={chat()} stream={stream(response)} />);
    await screen.findByRole("button", { name: "客户分析" });
    await user.type(screen.getByLabelText("消息"), "请创建每周三 AI 周报定时任务，并立即执行一次");
    await user.click(screen.getByRole("button", { name: "发送" }));
    await user.clear(await screen.findByLabelText("执行周期"));
    await user.type(screen.getByLabelText("执行周期"), "0 9 * * 1-5");
    await user.clear(screen.getByLabelText("任务内容"));
    await user.type(screen.getByLabelText("任务内容"), "读取飞书待办并生成摘要");
    await user.click(screen.getByLabelText("需要审批"));
    await user.click(await screen.findByRole("button", { name: "确认创建" }));

    expect(pipelineService.createTask).toHaveBeenCalledWith(expect.objectContaining({
      title: "AI 周报",
      prompt: "读取飞书待办并生成摘要",
      schedule: "0 9 * * 1-5",
      approval_required: false,
      confirmed: true,
    }));
    expect(pipelineService.runTask).toHaveBeenCalledWith(55);
    expect(await screen.findByTestId("chat-platform-action")).toHaveTextContent("任务 #55");
    expect(screen.getByTestId("chat-platform-action")).toHaveTextContent("运行 #77");
  });

  it("reuses the client message ID when retrying a failed request", async () => {
    const chatStream = {
      sendMessageStream: vi.fn()
        .mockRejectedValueOnce(new Error("发送失败"))
        .mockResolvedValueOnce({ ok: true, text: async () => "event: response.completed\ndata: {}" }),
    } as unknown as ChatStreamService;
    const user = userEvent.setup();
    render(<ChatPage cache={cache()} organizationId={7} pipeline={pipeline()} service={chat()} stream={chatStream} />);
    await screen.findByRole("button", { name: "客户分析" });
    await user.type(screen.getByLabelText("消息"), "创建每日定时任务并立即执行一次");
    await user.click(screen.getByRole("button", { name: "发送" }));
    await user.click(await screen.findByRole("button", { name: "重试" }));

    const send = chatStream.sendMessageStream as ReturnType<typeof vi.fn>;
    expect(send).toHaveBeenCalledTimes(2);
    expect(send.mock.calls[1]?.[1]).toMatchObject({
      client_message_id: send.mock.calls[0]?.[1].client_message_id,
    });
  });

  it("shows an actionable failure and retry affordance", async () => {
    const service = chat(); const user = userEvent.setup();
    render(<ChatPage cache={cache()} organizationId={7} pipeline={pipeline()} service={service} stream={{ sendMessageStream: vi.fn(async () => { throw new Error("发送失败"); }) } as unknown as ChatStreamService} />);
    await screen.findByText("选择会话后开始对话。");
    await screen.findByRole("button", { name: "客户分析" });
    await user.type(screen.getByLabelText("消息"), "失败请求");
    await user.click(screen.getByRole("button", { name: "发送" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("发送失败");
    await user.click(screen.getByRole("button", { name: "重试" }));
  });

  it("explains when unfinished sessions occupy the per-user run quota", async () => {
    const quotaError = Object.assign(new Error("User sandbox run quota reached"), { status: 429 });
    const user = userEvent.setup();
    render(<ChatPage cache={cache()} organizationId={7} pipeline={pipeline()} service={chat()} stream={{ sendMessageStream: vi.fn(async () => { throw quotaError; }) } as unknown as ChatStreamService} />);
    await screen.findByRole("button", { name: "客户分析" });
    await user.type(screen.getByLabelText("消息"), "开始分析");
    await user.click(screen.getByRole("button", { name: "发送" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("运行额度被未完成会话占用");
    expect(screen.getAllByText("运行额度被未完成会话占用，请等待会话结束后重试。").length).toBeGreaterThanOrEqual(2);
  });

  it("stops the active Hermes run before releasing the composer", async () => {
    let finishStop!: () => void;
    const stopResult = new Promise<void>((resolve) => { finishStop = resolve; });
    const service = chat({ stopRun: vi.fn(async () => { await stopResult; return { run_id: "run-1", status: "stopping" }; }) });
    const chatStream = {
      sendMessageStream: vi.fn(async (_sessionId, _request, options) => {
        let readCount = 0;
        return {
          ok: true,
          body: {
            getReader: () => ({
              read: async () => {
                readCount += 1;
                if (readCount === 1) {
                  return {
                    done: false,
                    value: new TextEncoder().encode('event: run.created\ndata: {"run_id":"run-1"}\n\n'),
                  };
                }
                return new Promise((resolve) => {
                  options.signal.addEventListener("abort", () => resolve({ done: true, value: undefined }), { once: true });
                });
              },
            }),
          },
        };
      }),
    } as unknown as ChatStreamService;
    const user = userEvent.setup();
    render(<ChatPage cache={cache()} organizationId={7} pipeline={pipeline()} service={service} stream={chatStream} />);
    await screen.findByRole("button", { name: "客户分析" });
    await user.type(screen.getByLabelText("消息"), "开始分析");
    await user.click(screen.getByRole("button", { name: "发送" }));
    await user.click(await screen.findByRole("button", { name: "停止" }));

    expect(service.stopRun).toHaveBeenCalledWith("1", "run-1");
    await waitFor(() => expect(screen.getByLabelText("消息")).toBeDisabled());
    finishStop();
    await waitFor(() => expect(screen.getByLabelText("消息")).toBeEnabled());
  });

  it("creates an agent session and preserves numeric API IDs", async () => {
    const service = chat({ listSessions: vi.fn(async () => ({ items: [] })) });
    const user = userEvent.setup();
    render(<ChatPage cache={cache()} organizationId={7} pipeline={pipeline()} service={service} stream={stream()} />);
    await user.click(await screen.findByRole("button", { name: "新建会话" }));
    expect(service.createSession).toHaveBeenCalledWith({ surface: "agent", title: "新会话" });
    expect(service.getMessages).not.toHaveBeenCalledWith("session-1");
  });
});
