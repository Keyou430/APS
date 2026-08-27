import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom/vitest";
import { describe, expect, it, vi } from "vitest";
import type { ChatService } from "../api/services/chatService";
import type { ChatStreamService } from "../api/services/chatStream";
import type { KnowledgeService } from "../api/services/knowledgeService";
import { ChatPage } from "./ChatPage";

function cache() { return { get: vi.fn(), invalidateOrganization: vi.fn(), set: vi.fn() }; }
function chat(overrides: Partial<ChatService> = {}) { return { createSession: vi.fn(async () => ({ id: 2, title: "新会话" })), deleteSession: vi.fn(async () => undefined), getMessages: vi.fn(async () => ({ items: [] })), listSessions: vi.fn(async () => ({ items: [{ id: 1, title: "客户分析" }] })), setKnowledgeScope: vi.fn(async () => ({})), ...overrides } as unknown as ChatService; }
function knowledge(overrides: Partial<KnowledgeService> = {}) { return { listEntries: vi.fn(async () => ({ items: [{ id: 11, title: "员工手册" }] })), ...overrides } as unknown as KnowledgeService; }
function stream(response: unknown = { ok: true, text: async () => "event: response.output_text.delta\ndata: {\"delta\":\"你好\"}\n\nevent: response.completed\ndata: {}" }) { return { sendMessageStream: vi.fn(async () => response) } as unknown as ChatStreamService; }

describe("ChatPage", () => {
  it("prefers initialSurface and otherwise reads the knowledge surface from the URL", async () => {
    const originalUrl = window.location.href;
    window.history.pushState({}, "", "/chat?surface=knowledge");
    try {
      const explicitService = chat();
      const explicit = render(<ChatPage cache={cache()} initialSurface="agent" knowledgeService={knowledge()} organizationId={7} service={explicitService} stream={stream()} />);
      await screen.findByRole("button", { name: "客户分析" });
      expect(explicitService.listSessions).toHaveBeenCalledWith({ surface: "agent" });
      explicit.unmount();

      const urlService = chat();
      render(<ChatPage cache={cache()} knowledgeService={knowledge()} organizationId={7} service={urlService} stream={stream()} />);
      await screen.findByRole("button", { name: "客户分析" });
      expect(urlService.listSessions).toHaveBeenCalledWith({ surface: "knowledge" });
    } finally {
      window.history.pushState({}, "", originalUrl);
    }
  });

  it("ignores delayed sessions from a previous organization after access is removed", async () => {
    let resolveSessions!: (value: { items: unknown[] }) => void;
    const delayedSessions = new Promise<{ items: unknown[] }>((resolve) => { resolveSessions = resolve; });
    const service = chat({ listSessions: vi.fn(async () => delayedSessions) });
    const view = render(<ChatPage cache={cache()} knowledgeService={knowledge()} organizationId={7} service={service} stream={stream()} />);

    await waitFor(() => expect(service.listSessions).toHaveBeenCalledWith({ surface: "agent" }));
    view.rerender(<ChatPage cache={cache()} knowledgeService={knowledge()} organizationId={null} service={service} stream={stream()} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("没有会话访问权限");

    await act(async () => { resolveSessions({ items: [{ id: 7, title: "组织 7 延迟会话", surface: "agent" }] }); });
    expect(screen.queryByRole("button", { name: "组织 7 延迟会话" })).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("没有会话访问权限");
  });

  it("clears the previous organization while its selected session messages are delayed", async () => {
    let resolveOldMessages!: (value: { items: unknown[] }) => void;
    let resolveNewSessions!: (value: { items: unknown[] }) => void;
    const oldMessages = new Promise<{ items: unknown[] }>((resolve) => { resolveOldMessages = resolve; });
    const newSessions = new Promise<{ items: unknown[] }>((resolve) => { resolveNewSessions = resolve; });
    const service = chat({
      getMessages: vi.fn()
        .mockImplementationOnce(() => oldMessages)
        .mockResolvedValueOnce({ items: [{ id: "org-8-message", role: "assistant", content: "组织 8 当前消息" }] }),
      listSessions: vi.fn()
        .mockResolvedValueOnce({ items: [{ id: 7, title: "组织 7 会话", surface: "agent" }] })
        .mockImplementationOnce(() => newSessions),
    });
    const view = render(<ChatPage cache={cache()} knowledgeService={knowledge()} organizationId={7} service={service} stream={stream()} />);

    await screen.findByRole("button", { name: "组织 7 会话" });
    view.rerender(<ChatPage cache={cache()} knowledgeService={knowledge()} organizationId={8} service={service} stream={stream()} />);
    expect(screen.queryByRole("button", { name: "组织 7 会话" })).not.toBeInTheDocument();

    await act(async () => { resolveNewSessions({ items: [{ id: 8, title: "组织 8 会话", surface: "agent" }] }); });
    expect(await screen.findByText("组织 8 当前消息")).toBeInTheDocument();
    await act(async () => { resolveOldMessages({ items: [{ id: "org-7-message", role: "assistant", content: "组织 7 延迟消息" }] }); });
    expect(screen.getByText("组织 8 当前消息")).toBeInTheDocument();
    expect(screen.queryByText("组织 7 延迟消息")).not.toBeInTheDocument();
    expect(screen.queryByText("正在加载会话")).not.toBeInTheDocument();
  });

  it("loads sessions and history, then sends a streaming message", async () => {
    const service = chat({ getMessages: vi.fn(async () => ({ items: [{ id: "m1", role: "assistant", content: "历史回复" }] })) });
    const user = userEvent.setup();
    render(<ChatPage cache={cache()} knowledgeService={knowledge()} organizationId={7} service={service} stream={stream()} />);
    expect(await screen.findByText("历史回复")).toBeInTheDocument();
    expect(service.listSessions).toHaveBeenCalledWith({ surface: "agent" });
    await user.type(screen.getByLabelText("消息"), "你好");
    await user.click(screen.getByRole("button", { name: "发送" }));
    expect(screen.getAllByText("你好").length).toBeGreaterThanOrEqual(2);
  });

  it("preserves knowledge session fields and conservatively defaults missing fields", async () => {
    const pageCache = cache();
    const service = chat({ listSessions: vi.fn(async () => ({ items: [
      { id: 4, title: "指定知识", surface: "knowledge", knowledge_scope: "selected", source_ids: [11] },
      { id: 5, title: "旧知识会话" },
    ] })) });
    render(<ChatPage cache={pageCache} initialSurface="knowledge" knowledgeService={knowledge()} organizationId={7} service={service} stream={stream()} />);

    await screen.findByRole("button", { name: "指定知识" });
    expect(pageCache.set).toHaveBeenCalledWith(7, ["chat", "sessions", "knowledge"], [
      expect.objectContaining({ id: "4", surface: "knowledge", knowledge_scope: "selected", source_ids: [11] }),
      expect.objectContaining({ id: "5", surface: "knowledge", knowledge_scope: "none", source_ids: [] }),
    ]);
  });

  it("switches surfaces by aborting the active stream and loading an isolated session cache", async () => {
    const pageCache = cache();
    let resolveKnowledgeSessions!: (value: { items: unknown[] }) => void;
    const knowledgeSessions = new Promise<{ items: unknown[] }>((resolve) => { resolveKnowledgeSessions = resolve; });
    const service = chat({
      listSessions: vi.fn(async (query) => query?.surface === "knowledge"
        ? knowledgeSessions
        : { items: [{ id: 1, title: "普通历史", surface: "agent" }] }),
    });
    const activeSignals: AbortSignal[] = [];
    const rejectStreams: Array<(reason: Error) => void> = [];
    const chatStream = {
      sendMessageStream: vi.fn((_sessionId, _request, options) => {
        if (options?.signal) activeSignals.push(options.signal);
        return new Promise<Response>((_resolve, reject) => { rejectStreams.push(reject); });
      }),
    } as ChatStreamService;
    const user = userEvent.setup();
    render(<ChatPage cache={pageCache} knowledgeService={knowledge()} organizationId={7} service={service} stream={chatStream} />);

    await screen.findByRole("button", { name: "普通历史" });
    expect(screen.getByRole("button", { name: "普通对话" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "知识问答" })).toHaveAttribute("aria-pressed", "false");
    await user.type(screen.getByLabelText("消息"), "进行中的问题");
    await user.click(screen.getByRole("button", { name: "发送" }));
    await waitFor(() => expect(chatStream.sendMessageStream).toHaveBeenCalled());

    await user.click(screen.getByRole("button", { name: "知识问答" }));
    expect(activeSignals[0]?.aborted).toBe(true);
    expect(screen.queryByRole("button", { name: "普通历史" })).not.toBeInTheDocument();
    expect(screen.queryByText("进行中的问题")).not.toBeInTheDocument();
    expect(pageCache.get).toHaveBeenCalledWith(7, ["chat", "sessions", "agent"]);
    expect(pageCache.get).toHaveBeenCalledWith(7, ["chat", "sessions", "knowledge"]);
    expect(service.listSessions).toHaveBeenCalledWith({ surface: "knowledge" });

    act(() => resolveKnowledgeSessions({ items: [{ id: 2, title: "知识历史", surface: "knowledge", knowledge_scope: "all_visible", source_ids: [] }] }));
    expect(await screen.findByRole("button", { name: "知识历史" })).toBeInTheDocument();
    await user.type(screen.getByLabelText("消息"), "新的知识问题");
    await user.click(screen.getByRole("button", { name: "发送" }));
    await waitFor(() => expect(chatStream.sendMessageStream).toHaveBeenCalledTimes(2));

    await act(async () => { rejectStreams[0]?.(new Error("旧流已终止")); });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByText("新的知识问题")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "停止" })).toBeInTheDocument();
    expect(activeSignals[1]?.aborted).toBe(false);

    await user.click(screen.getByRole("button", { name: "停止" }));
    expect(activeSignals[1]?.aborted).toBe(true);
    await act(async () => { rejectStreams[1]?.(new Error("当前流已终止")); });
    expect(screen.getByText("已中断")).toBeInTheDocument();
  });

  it("ignores successful frames from an old stream that continues after switching surfaces", async () => {
    let resolveOldStream!: (response: Response) => void;
    const oldStream = new Promise<Response>((resolve) => { resolveOldStream = resolve; });
    const chatStream = {
      sendMessageStream: vi.fn()
        .mockImplementationOnce(() => oldStream)
        .mockImplementationOnce(() => new Promise<Response>(() => undefined)),
    } as unknown as ChatStreamService;
    const service = chat({
      listSessions: vi.fn(async (query) => ({ items: [{
        id: 1,
        title: query?.surface === "knowledge" ? "知识当前会话" : "普通当前会话",
        surface: query?.surface,
        knowledge_scope: query?.surface === "knowledge" ? "all_visible" : undefined,
        source_ids: [],
      }] })),
    });
    const dateNow = vi.spyOn(Date, "now").mockReturnValue(123);
    const user = userEvent.setup();
    try {
      render(<ChatPage cache={cache()} knowledgeService={knowledge()} organizationId={7} service={service} stream={chatStream} />);

      await screen.findByRole("button", { name: "普通当前会话" });
      await user.type(screen.getByLabelText("消息"), "旧问题");
      await user.click(screen.getByRole("button", { name: "发送" }));
      await waitFor(() => expect(chatStream.sendMessageStream).toHaveBeenCalledTimes(1));

      await user.click(screen.getByRole("button", { name: "知识问答" }));
      await screen.findByRole("button", { name: "知识当前会话" });
      await user.type(screen.getByLabelText("消息"), "新问题");
      await user.click(screen.getByRole("button", { name: "发送" }));
      await waitFor(() => expect(chatStream.sendMessageStream).toHaveBeenCalledTimes(2));

      await act(async () => { resolveOldStream({
        ok: true,
        text: async () => [
          'event: knowledge.context\ndata: {"references":[{"id":99}]}',
          'event: response.output_text.delta\ndata: {"delta":"旧回答"}',
          'event: response.completed\ndata: {}',
        ].join("\n\n"),
      } as Response); });

      expect(screen.queryByText("旧回答")).not.toBeInTheDocument();
      expect(screen.getByText("新问题")).toBeInTheDocument();
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "停止" })).toBeInTheDocument();
    } finally {
      dateNow.mockRestore();
    }
  });

  it("ignores old stream chunks received after reader.read has started and the surface changes", async () => {
    let oldStreamController!: ReadableStreamDefaultController<Uint8Array>;
    let releasePull!: () => void;
    let markReaderStarted!: () => void;
    const readerStarted = new Promise<void>((resolve) => { markReaderStarted = resolve; });
    const heldPull = new Promise<void>((resolve) => { releasePull = resolve; });
    const readable = new ReadableStream<Uint8Array>({
      pull(controller) {
        oldStreamController = controller;
        markReaderStarted();
        return heldPull;
      },
    }, { highWaterMark: 0 });
    const chatStream = {
      sendMessageStream: vi.fn(async () => new Response(readable, {
        headers: { "Content-Type": "text/event-stream" },
        status: 200,
      })),
    } as unknown as ChatStreamService;
    const service = chat({
      getMessages: vi.fn(async () => ({ items: [] })),
      listSessions: vi.fn(async (query) => ({ items: [{
        id: query?.surface === "knowledge" ? 2 : 1,
        title: query?.surface === "knowledge" ? "知识当前会话" : "普通当前会话",
        surface: query?.surface,
      }] })),
    });
    const user = userEvent.setup();
    render(<ChatPage cache={cache()} knowledgeService={knowledge()} organizationId={7} service={service} stream={chatStream} />);

    await screen.findByRole("button", { name: "普通当前会话" });
    await user.type(screen.getByLabelText("消息"), "等待旧流");
    await user.click(screen.getByRole("button", { name: "发送" }));
    await readerStarted;

    await user.click(screen.getByRole("button", { name: "知识问答" }));
    expect(await screen.findByRole("button", { name: "知识当前会话" })).toBeInTheDocument();
    expect(screen.getByText("选择会话后开始对话。")).toBeInTheDocument();

    await act(async () => {
      oldStreamController.enqueue(new TextEncoder().encode([
        'event: response.output_text.delta\ndata: {"delta":"旧流迟到内容"}',
        'event: response.completed\ndata: {}',
      ].join("\n\n")));
      oldStreamController.close();
      releasePull();
    });

    expect(screen.queryByText("旧流迟到内容")).not.toBeInTheDocument();
    expect(screen.getByText("选择会话后开始对话。")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "停止" })).not.toBeInTheDocument();
  });

  it("aborts an active stream on unmount and ignores its late completion", async () => {
    let oldStreamController!: ReadableStreamDefaultController<Uint8Array>;
    let releasePull!: () => void;
    let markReaderStarted!: () => void;
    let activeSignal: AbortSignal | undefined;
    const readerStarted = new Promise<void>((resolve) => { markReaderStarted = resolve; });
    const heldPull = new Promise<void>((resolve) => { releasePull = resolve; });
    const readable = new ReadableStream<Uint8Array>({
      pull(controller) {
        oldStreamController = controller;
        markReaderStarted();
        return heldPull;
      },
    }, { highWaterMark: 0 });
    const chatStream = {
      sendMessageStream: vi.fn(async (_sessionId, _request, options) => {
        activeSignal = options?.signal;
        return new Response(readable, { status: 200 });
      }),
    } as unknown as ChatStreamService;
    const pageCache = cache();
    const user = userEvent.setup();
    const view = render(<ChatPage cache={pageCache} knowledgeService={knowledge()} organizationId={7} service={chat()} stream={chatStream} />);

    await screen.findByRole("button", { name: "客户分析" });
    await user.type(screen.getByLabelText("消息"), "卸载前消息");
    await user.click(screen.getByRole("button", { name: "发送" }));
    await readerStarted;
    const cacheWritesBeforeUnmount = pageCache.set.mock.calls.length;

    view.unmount();
    expect(activeSignal?.aborted).toBe(true);
    await act(async () => {
      oldStreamController.enqueue(new TextEncoder().encode('event: response.output_text.delta\ndata: {"delta":"卸载后迟到"}\n\nevent: response.completed\ndata: {}'));
      oldStreamController.close();
      releasePull();
    });
    expect(pageCache.set).toHaveBeenCalledTimes(cacheWritesBeforeUnmount);
  });

  it("ignores delayed messages from an old selected session after switching surfaces", async () => {
    let resolveAgentMessages!: (value: { items: unknown[] }) => void;
    const agentMessages = new Promise<{ items: unknown[] }>((resolve) => { resolveAgentMessages = resolve; });
    const service = chat({
      getMessages: vi.fn()
        .mockImplementationOnce(() => agentMessages)
        .mockResolvedValueOnce({ items: [{ id: "knowledge-message", role: "assistant", content: "知识当前消息" }] }),
      listSessions: vi.fn(async (query) => ({ items: [{
        id: 1,
        title: query?.surface === "knowledge" ? "知识当前会话" : "普通当前会话",
        surface: query?.surface,
      }] })),
    });
    const user = userEvent.setup();
    render(<ChatPage cache={cache()} knowledgeService={knowledge()} organizationId={7} service={service} stream={stream()} />);

    await waitFor(() => expect(service.getMessages).toHaveBeenCalledTimes(1));
    await user.click(screen.getByRole("button", { name: "知识问答" }));
    expect(await screen.findByText("知识当前消息")).toBeInTheDocument();
    expect(screen.queryByText("正在加载会话")).not.toBeInTheDocument();

    await act(async () => { resolveAgentMessages({ items: [{ id: "agent-message", role: "assistant", content: "普通延迟消息" }] }); });
    expect(screen.getByText("知识当前消息")).toBeInTheDocument();
    expect(screen.queryByText("普通延迟消息")).not.toBeInTheDocument();
    expect(screen.queryByText("正在加载会话")).not.toBeInTheDocument();
  });

  it("aborts the current stream before selecting another session", async () => {
    let rejectOldStream!: (reason: Error) => void;
    let activeSignal: AbortSignal | undefined;
    const chatStream = {
      sendMessageStream: vi.fn((_sessionId, _request, options) => {
        activeSignal = options?.signal;
        return new Promise<Response>((_resolve, reject) => { rejectOldStream = reject; });
      }),
    } as unknown as ChatStreamService;
    const service = chat({
      getMessages: vi.fn(async () => ({ items: [] })),
      listSessions: vi.fn(async () => ({ items: [
        { id: 1, title: "会话一", surface: "agent" },
        { id: 2, title: "会话二", surface: "agent" },
      ] })),
    });
    const user = userEvent.setup();
    render(<ChatPage cache={cache()} knowledgeService={knowledge()} organizationId={7} service={service} stream={chatStream} />);

    await screen.findByRole("button", { name: "会话一" });
    await user.type(screen.getByLabelText("消息"), "会话一进行中");
    await user.click(screen.getByRole("button", { name: "发送" }));
    await waitFor(() => expect(chatStream.sendMessageStream).toHaveBeenCalledTimes(1));
    await user.click(screen.getByRole("button", { name: "会话二" }));

    expect(activeSignal?.aborted).toBe(true);
    expect(screen.getByLabelText("消息")).toBeEnabled();
    await user.type(screen.getByLabelText("消息"), "会话二输入");
    await act(async () => { rejectOldStream(new Error("旧会话流迟到错误")); });
    expect(screen.getByLabelText("消息")).toHaveValue("会话二输入");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByText("会话一进行中")).not.toBeInTheDocument();
  });

  it("ignores a delayed old-surface session list after switching surfaces", async () => {
    let resolveAgentSessions!: (value: { items: unknown[] }) => void;
    const agentSessions = new Promise<{ items: unknown[] }>((resolve) => { resolveAgentSessions = resolve; });
    const service = chat({
      listSessions: vi.fn(async (query) => query?.surface === "agent"
        ? agentSessions
        : { items: [{ id: 2, title: "知识当前会话", surface: "knowledge" }] }),
    });
    const user = userEvent.setup();
    render(<ChatPage cache={cache()} knowledgeService={knowledge()} organizationId={7} service={service} stream={stream()} />);

    await waitFor(() => expect(service.listSessions).toHaveBeenCalledWith({ surface: "agent" }));
    await user.click(screen.getByRole("button", { name: "知识问答" }));
    expect(await screen.findByRole("button", { name: "知识当前会话" })).toBeInTheDocument();

    await act(async () => { resolveAgentSessions({ items: [] }); });
    expect(screen.getByRole("button", { name: "知识当前会话" })).toBeInTheDocument();
    expect(screen.queryByText("暂无会话，请新建一个会话。")).not.toBeInTheDocument();
  });

  it("ignores a delayed old-surface session creation after switching surfaces", async () => {
    let resolveAgentCreation!: (value: { id: number; title: string }) => void;
    const agentCreation = new Promise<{ id: number; title: string }>((resolve) => { resolveAgentCreation = resolve; });
    const service = chat({
      createSession: vi.fn(async () => agentCreation),
      listSessions: vi.fn(async () => ({ items: [] })),
    });
    const user = userEvent.setup();
    render(<ChatPage cache={cache()} knowledgeService={knowledge()} organizationId={7} service={service} stream={stream()} />);

    await screen.findByText("暂无会话，请新建一个会话。");
    await user.click(screen.getByRole("button", { name: "新建会话" }));
    expect(service.createSession).toHaveBeenCalledWith({ surface: "agent", title: "新会话" });
    await user.click(screen.getByRole("button", { name: "知识问答" }));
    await screen.findByText("暂无会话，请新建一个会话。");

    await act(async () => { resolveAgentCreation({ id: 9, title: "普通延迟会话" }); });
    expect(screen.queryByRole("button", { name: "普通延迟会话" })).not.toBeInTheDocument();
    expect(screen.getByText("暂无会话，请新建一个会话。")).toBeInTheDocument();
  });

  it("invalidates the originating organization cache when a stale agent creation succeeds", async () => {
    let resolveAgentCreation!: (value: { id: number; title: string }) => void;
    const agentCreation = new Promise<{ id: number; title: string }>((resolve) => { resolveAgentCreation = resolve; });
    const pageCache = cache();
    const service = chat({
      createSession: vi.fn(async () => agentCreation),
      listSessions: vi.fn(async () => ({ items: [] })),
    });
    const user = userEvent.setup();
    render(<ChatPage cache={pageCache} knowledgeService={knowledge()} organizationId={7} service={service} stream={stream()} />);

    await screen.findByText("暂无会话，请新建一个会话。");
    await user.click(screen.getByRole("button", { name: "新建会话" }));
    await user.click(screen.getByRole("button", { name: "知识问答" }));
    await screen.findByText("暂无会话，请新建一个会话。");
    await act(async () => { resolveAgentCreation({ id: 9, title: "普通延迟创建" }); });

    expect(pageCache.invalidateOrganization).toHaveBeenCalledWith(7);
    expect(screen.queryByRole("button", { name: "普通延迟创建" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "普通对话" }));
    await waitFor(() => expect((service.listSessions as ReturnType<typeof vi.fn>).mock.calls.filter(([query]) => query?.surface === "agent")).toHaveLength(2));
  });

  it("restores history web sources and renders only validated links", async () => {
    const service = chat({ getMessages: vi.fn(async () => ({ items: [
      { id: "m-user", role: "user", content: "最近的 AI 动态" },
      { id: "m-assistant", role: "assistant", content: "有一条动态", web_sources: [{ ordinal: 0, provider: "exa", url: "https://example.com/news", title: "可验证来源", published_at: "2026-08-22T00:00:00Z", searched_at: "2026-08-23T00:00:00Z", correlation_id: "run-1" }] },
    ] })) });
    render(<ChatPage cache={cache()} knowledgeService={knowledge()} organizationId={7} service={service} stream={stream()} />);
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
    render(<ChatPage cache={cache()} knowledgeService={knowledge()} organizationId={7} service={service} stream={stream(response)} />);
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
    render(<ChatPage cache={cache()} knowledgeService={knowledge()} organizationId={7} service={service} stream={chatStream} />);
    await screen.findByRole("button", { name: "客户分析" });
    await user.type(screen.getByLabelText("消息"), "创建每日定时任务并立即执行一次");
    await user.click(screen.getByRole("button", { name: "发送" }));

    expect(await screen.findByTestId("chat-platform-action")).toHaveTextContent("已创建定时任务并完成首次执行");
    expect(screen.getByTestId("chat-platform-action")).toHaveTextContent("任务 #12");
    const request = (chatStream.sendMessageStream as ReturnType<typeof vi.fn>).mock.calls[0]?.[1];
    expect(request).toMatchObject({
      client_message_id: expect.stringMatching(/^m_/),
      content: "创建每日定时任务并立即执行一次",
    });
    expect(request).not.toHaveProperty("source_ids");
  });

  it("reuses the client message ID when retrying a failed request", async () => {
    const chatStream = {
      sendMessageStream: vi.fn()
        .mockRejectedValueOnce(new Error("发送失败"))
        .mockResolvedValueOnce({ ok: true, text: async () => "event: response.completed\ndata: {}" }),
    } as unknown as ChatStreamService;
    const user = userEvent.setup();
    render(<ChatPage cache={cache()} knowledgeService={knowledge()} organizationId={7} service={chat()} stream={chatStream} />);
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
    render(<ChatPage cache={cache()} knowledgeService={knowledge()} organizationId={7} service={service} stream={{ sendMessageStream: vi.fn(async () => { throw new Error("发送失败"); }) } as unknown as ChatStreamService} />);
    await screen.findByText("选择会话后开始对话。");
    await screen.findByRole("button", { name: "客户分析" });
    await user.type(screen.getByLabelText("消息"), "失败请求");
    await user.click(screen.getByRole("button", { name: "发送" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("发送失败");
    await user.click(screen.getByRole("button", { name: "重试" }));
  });

  it("creates an agent session and preserves numeric API IDs", async () => {
    const service = chat({ listSessions: vi.fn(async () => ({ items: [] })) });
    const user = userEvent.setup();
    render(<ChatPage cache={cache()} knowledgeService={knowledge()} organizationId={7} service={service} stream={stream()} />);
    await user.click(await screen.findByRole("button", { name: "新建会话" }));
    expect(service.createSession).toHaveBeenCalledWith({ surface: "agent", title: "新会话" });
    expect(service.setKnowledgeScope).not.toHaveBeenCalled();
    expect(service.getMessages).not.toHaveBeenCalledWith("session-1");
  });

  it("loads and creates knowledge sessions with an all-visible scope", async () => {
    const service = chat({ listSessions: vi.fn(async () => ({ items: [] })) });
    const pageCache = cache();
    const user = userEvent.setup();
    render(<ChatPage cache={pageCache} initialSurface="knowledge" knowledgeService={knowledge()} organizationId={7} service={service} stream={stream()} />);

    expect(await screen.findByRole("button", { name: "新建会话" })).toBeInTheDocument();
    expect(service.listSessions).toHaveBeenCalledWith({ surface: "knowledge" });
    await user.click(screen.getByRole("button", { name: "新建会话" }));
    expect(service.createSession).toHaveBeenCalledWith({ surface: "knowledge", title: "新会话" });
    expect(service.setKnowledgeScope).toHaveBeenCalledWith("2", { mode: "all_visible", source_ids: [] });
    expect(pageCache.set).toHaveBeenLastCalledWith(7, ["chat", "sessions", "knowledge"], [
      expect.objectContaining({ id: "2", surface: "knowledge", knowledge_scope: "all_visible", source_ids: [] }),
    ]);
    expect(screen.getByRole("radio", { name: "全部可见知识" })).toBeChecked();
  });

  it("does not retain a knowledge session when all-visible scope initialization fails", async () => {
    const pageCache = cache();
    const service = chat({
      listSessions: vi.fn(async () => ({ items: [] })),
      setKnowledgeScope: vi.fn(async () => { throw new Error("知识范围初始化失败"); }),
    });
    const user = userEvent.setup();
    render(<ChatPage cache={pageCache} initialSurface="knowledge" knowledgeService={knowledge()} organizationId={7} service={service} stream={stream()} />);

    await screen.findByText("暂无会话，请新建一个会话。");
    await user.click(screen.getByRole("button", { name: "新建会话" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("知识范围初始化失败");
    expect(service.deleteSession).toHaveBeenCalledWith("2");
    expect(screen.queryByRole("button", { name: "新会话" })).not.toBeInTheDocument();
    expect(pageCache.invalidateOrganization).toHaveBeenCalledWith(7);
    expect(pageCache.set).toHaveBeenCalledTimes(1);
    expect(pageCache.set).toHaveBeenLastCalledWith(7, ["chat", "sessions", "knowledge"], []);
  });

  it("keeps the scope initialization error when compensating deletion also fails", async () => {
    const pageCache = cache();
    const service = chat({
      deleteSession: vi.fn(async () => { throw new Error("补偿删除失败"); }),
      listSessions: vi.fn(async () => ({ items: [] })),
      setKnowledgeScope: vi.fn(async () => { throw new Error("知识范围初始化失败"); }),
    });
    const user = userEvent.setup();
    render(<ChatPage cache={pageCache} initialSurface="knowledge" knowledgeService={knowledge()} organizationId={7} service={service} stream={stream()} />);

    await screen.findByText("暂无会话，请新建一个会话。");
    await user.click(screen.getByRole("button", { name: "新建会话" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("知识范围初始化失败");
    expect(screen.getByRole("alert")).toHaveTextContent("会话清理未完成，请刷新会话列表");
    expect(screen.getByRole("alert")).not.toHaveTextContent("补偿删除失败");
    expect(service.deleteSession).toHaveBeenCalledWith("2");
    expect(pageCache.invalidateOrganization).toHaveBeenCalledWith(7);
    expect(screen.queryByRole("button", { name: "新会话" })).not.toBeInTheDocument();
    expect(pageCache.set).toHaveBeenCalledTimes(1);
  });

  it("loads knowledge entries and persists an applied selected scope", async () => {
    const pageCache = cache();
    const service = chat({ listSessions: vi.fn(async () => ({ items: [
      { id: 1, title: "知识会话一", surface: "knowledge", knowledge_scope: "all_visible", source_ids: [] },
      { id: 2, title: "知识会话二", surface: "knowledge", knowledge_scope: "all_visible", source_ids: [] },
    ] })) });
    const knowledgeService = knowledge();
    const user = userEvent.setup();
    render(<ChatPage cache={pageCache} initialSurface="knowledge" knowledgeService={knowledgeService} organizationId={7} service={service} stream={stream()} />);

    await screen.findByRole("button", { name: "知识会话一" });
    expect(knowledgeService.listEntries).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole("radio", { name: "指定知识" }));
    await user.click(screen.getByRole("checkbox", { name: "员工手册" }));
    await user.click(screen.getByRole("button", { name: "应用知识范围" }));

    await waitFor(() => expect(service.setKnowledgeScope).toHaveBeenCalledWith("1", { mode: "selected", source_ids: [11] }));
    expect(pageCache.set).toHaveBeenLastCalledWith(7, ["chat", "sessions", "knowledge"], expect.arrayContaining([
      expect.objectContaining({ id: "1", knowledge_scope: "selected", source_ids: [11] }),
    ]));
    await user.click(screen.getByRole("button", { name: "知识会话二" }));
    await user.click(screen.getByRole("button", { name: "知识会话一" }));
    expect(screen.getByRole("radio", { name: "指定知识" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "员工手册" })).toBeChecked();
  });

  it("keeps knowledge sending blocked until an all-visible draft is applied", async () => {
    const service = chat({ listSessions: vi.fn(async () => ({ items: [
      { id: 1, title: "未设置范围", surface: "knowledge", knowledge_scope: "none", source_ids: [] },
    ] })) });
    const user = userEvent.setup();
    render(<ChatPage cache={cache()} initialSurface="knowledge" knowledgeService={knowledge()} organizationId={7} service={service} stream={stream()} />);

    await screen.findByRole("button", { name: "未设置范围" });
    expect(screen.getByLabelText("消息")).toBeDisabled();
    expect(screen.getByRole("button", { name: "发送" })).toBeDisabled();
    expect(screen.getByText("请先设置知识范围")).toBeInTheDocument();

    await user.click(screen.getByRole("radio", { name: "全部可见知识" }));
    expect(screen.getByLabelText("消息")).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "应用知识范围" }));
    await waitFor(() => expect(screen.getByLabelText("消息")).toBeEnabled());
    await user.type(screen.getByLabelText("消息"), "现在可以发送");
    expect(screen.getByRole("button", { name: "发送" })).toBeEnabled();
  });

  it("restores the confirmed scope and leaves cache unchanged when saving fails", async () => {
    const pageCache = cache();
    const service = chat({
      listSessions: vi.fn(async () => ({ items: [
        { id: 1, title: "已确认范围", surface: "knowledge", knowledge_scope: "all_visible", source_ids: [] },
      ] })),
      setKnowledgeScope: vi.fn(async () => { throw new Error("范围保存失败"); }),
    });
    const user = userEvent.setup();
    render(<ChatPage cache={pageCache} initialSurface="knowledge" knowledgeService={knowledge()} organizationId={7} service={service} stream={stream()} />);

    await screen.findByRole("button", { name: "已确认范围" });
    const cacheWritesBeforeSave = pageCache.set.mock.calls.length;
    await user.click(screen.getByRole("radio", { name: "指定知识" }));
    await user.click(screen.getByRole("checkbox", { name: "员工手册" }));
    await user.click(screen.getByRole("button", { name: "应用知识范围" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("范围保存失败");
    expect(screen.getByRole("radio", { name: "全部可见知识" })).toBeChecked();
    expect(screen.queryByRole("checkbox", { name: "员工手册" })).not.toBeInTheDocument();
    expect(pageCache.set).toHaveBeenCalledTimes(cacheWritesBeforeSave);
  });

  it("restores each knowledge session draft from its persisted scope", async () => {
    const service = chat({ listSessions: vi.fn(async () => ({ items: [
      { id: 1, title: "手册会话", surface: "knowledge", knowledge_scope: "selected", source_ids: [11] },
      { id: 2, title: "制度会话", surface: "knowledge", knowledge_scope: "selected", source_ids: [12] },
    ] })) });
    const knowledgeService = knowledge({ listEntries: vi.fn(async () => ({ items: [
      { id: 11, title: "员工手册" },
      { id: 12, title: "考勤制度" },
    ] })) });
    const user = userEvent.setup();
    render(<ChatPage cache={cache()} initialSurface="knowledge" knowledgeService={knowledgeService} organizationId={7} service={service} stream={stream()} />);

    await screen.findByRole("button", { name: "手册会话" });
    expect(screen.getByRole("checkbox", { name: "员工手册" })).toBeChecked();
    await user.click(screen.getByRole("checkbox", { name: "员工手册" }));
    await user.click(screen.getByRole("checkbox", { name: "考勤制度" }));

    await user.click(screen.getByRole("button", { name: "制度会话" }));
    expect(screen.getByRole("checkbox", { name: "员工手册" })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: "考勤制度" })).toBeChecked();
    await user.click(screen.getByRole("button", { name: "手册会话" }));
    expect(screen.getByRole("checkbox", { name: "员工手册" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "考勤制度" })).not.toBeChecked();
  });

  it("rejects a fifty-first selected knowledge entry", async () => {
    const selectedIds = Array.from({ length: 50 }, (_, index) => index + 1);
    const service = chat({ listSessions: vi.fn(async () => ({ items: [
      { id: 1, title: "五十条知识", surface: "knowledge", knowledge_scope: "selected", source_ids: selectedIds },
    ] })) });
    const knowledgeService = knowledge({ listEntries: vi.fn(async () => ({ items: Array.from({ length: 51 }, (_, index) => ({ id: index + 1, title: `知识 ${index + 1}` })) })) });
    const user = userEvent.setup();
    render(<ChatPage cache={cache()} initialSurface="knowledge" knowledgeService={knowledgeService} organizationId={7} service={service} stream={stream()} />);

    await screen.findByRole("button", { name: "五十条知识" });
    const fiftyFirst = screen.getByRole("checkbox", { name: "知识 51" });
    expect(fiftyFirst).not.toBeChecked();
    await user.click(fiftyFirst);

    expect(fiftyFirst).not.toBeChecked();
    expect(screen.getByRole("alert")).toHaveTextContent("最多选择 50 条知识");
  });

  it("loads every visible knowledge page before validating a selected scope", async () => {
    const service = chat({ listSessions: vi.fn(async () => ({ items: [
      { id: 1, title: "跨页知识", surface: "knowledge", knowledge_scope: "selected", source_ids: [101] },
    ] })) });
    const knowledgeService = knowledge({
      listEntries: vi.fn(async (query) => query?.page === 2
        ? { items: [{ id: 101, title: "知识 101" }], total: 101, page: 2, page_size: 100 }
        : {
            items: Array.from({ length: 100 }, (_, index) => ({ id: index + 1, title: `知识 ${index + 1}` })),
            total: 101,
            page: 1,
            page_size: 100,
          }),
    });

    render(<ChatPage cache={cache()} initialSurface="knowledge" knowledgeService={knowledgeService} organizationId={7} service={service} stream={stream()} />);

    expect(await screen.findByRole("checkbox", { name: "知识 101" })).toBeChecked();
    expect(knowledgeService.listEntries).toHaveBeenNthCalledWith(1, { page: 1, page_size: 100 });
    expect(knowledgeService.listEntries).toHaveBeenNthCalledWith(2, { page: 2, page_size: 100 });
  });

  it("does not load knowledge entries on the agent surface and keeps normal sending available", async () => {
    const knowledgeService = knowledge();
    const chatStream = stream();
    const user = userEvent.setup();
    render(<ChatPage cache={cache()} initialSurface="agent" knowledgeService={knowledgeService} organizationId={7} service={chat()} stream={chatStream} />);

    await screen.findByRole("button", { name: "客户分析" });
    expect(knowledgeService.listEntries).not.toHaveBeenCalled();
    expect(screen.getByLabelText("消息")).toBeEnabled();
    await user.type(screen.getByLabelText("消息"), "普通消息");
    await user.click(screen.getByRole("button", { name: "发送" }));
    expect(chatStream.sendMessageStream).toHaveBeenCalledTimes(1);
  });

  it("uploads an agent attachment and sends its parsed content", async () => {
    const service = chat({
      prepareAttachment: vi.fn(async () => ({ title: "会议纪要.txt", content: "已解析的会议内容" })),
    });
    const chatStream = stream();
    const user = userEvent.setup();
    render(<ChatPage cache={cache()} initialSurface="agent" knowledgeService={knowledge()} organizationId={7} service={service} stream={chatStream} />);

    await screen.findByRole("button", { name: "客户分析" });
    await user.upload(screen.getByLabelText("添加附件"), new File(["会议内容"], "会议纪要.txt", { type: "text/plain" }));
    await waitFor(() => expect(service.prepareAttachment).toHaveBeenCalledTimes(1));
    await user.type(screen.getByLabelText("消息"), "总结附件");
    await user.click(screen.getByRole("button", { name: "发送" }));

    const request = (chatStream.sendMessageStream as ReturnType<typeof vi.fn>).mock.calls[0]?.[1];
    expect(request).toMatchObject({ attachments: [{ title: "会议纪要.txt", content: "已解析的会议内容" }] });
    expect(request).not.toHaveProperty("source_ids");
  });

  it("filters archived and disabled knowledge entries from the selectable list", async () => {
    const service = chat({ listSessions: vi.fn(async () => ({ items: [
      { id: 1, title: "筛选知识", surface: "knowledge", knowledge_scope: "selected", source_ids: [11] },
    ] })) });
    const knowledgeService = knowledge({ listEntries: vi.fn(async () => ({ items: [
      { id: 11, title: "员工手册" },
      { id: 12, title: "归档制度", status: "archived" },
      { id: 13, title: "停用制度", enabled: false },
      { id: 14, title: "默认可用制度" },
    ] })) });
    render(<ChatPage cache={cache()} initialSurface="knowledge" knowledgeService={knowledgeService} organizationId={7} service={service} stream={stream()} />);

    await screen.findByRole("button", { name: "筛选知识" });
    expect(screen.getByRole("checkbox", { name: "员工手册" })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "默认可用制度" })).toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: "归档制度" })).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: "停用制度" })).not.toBeInTheDocument();
  });

  it("prunes unavailable IDs from a selected draft without changing the persisted scope", async () => {
    let resolveEntries!: (value: { items: unknown[] }) => void;
    const delayedEntries = new Promise<{ items: unknown[] }>((resolve) => { resolveEntries = resolve; });
    const service = chat({ listSessions: vi.fn(async () => ({ items: [
      { id: 1, title: "包含失效知识", surface: "knowledge", knowledge_scope: "selected", source_ids: [11, 12, 13, 99] },
    ] })) });
    const knowledgeService = knowledge({ listEntries: vi.fn(async () => delayedEntries) });
    const user = userEvent.setup();
    render(<ChatPage cache={cache()} initialSurface="knowledge" knowledgeService={knowledgeService} organizationId={7} service={service} stream={stream()} />);

    await screen.findByRole("button", { name: "包含失效知识" });
    expect(await screen.findByText("知识条目加载中")).toBeInTheDocument();
    expect(screen.queryByText("暂无可选知识")).not.toBeInTheDocument();
    await act(async () => { resolveEntries({ items: [
      { id: 11, title: "员工手册" },
      { id: 12, title: "归档制度", status: "archived" },
      { id: 13, title: "停用制度", enabled: false },
    ] }); });

    expect(await screen.findByRole("checkbox", { name: "员工手册" })).toBeChecked();
    expect(service.setKnowledgeScope).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "应用知识范围" }));
    expect(service.setKnowledgeScope).toHaveBeenCalledWith("1", { mode: "selected", source_ids: [11] });
  });

  it("blocks sending until an invalid persisted selected scope is cleaned and applied", async () => {
    const service = chat({ listSessions: vi.fn(async () => ({ items: [
      { id: 1, title: "失效范围", surface: "knowledge", knowledge_scope: "selected", source_ids: [99] },
    ] })) });
    const user = userEvent.setup();
    render(<ChatPage cache={cache()} initialSurface="knowledge" knowledgeService={knowledge()} organizationId={7} service={service} stream={stream()} />);

    await screen.findByRole("button", { name: "失效范围" });
    expect(await screen.findByRole("checkbox", { name: "员工手册" })).not.toBeChecked();
    expect(screen.getByLabelText("消息")).toBeDisabled();
    expect(screen.getByRole("button", { name: "应用知识范围" })).toBeDisabled();

    await user.click(screen.getByRole("checkbox", { name: "员工手册" }));
    await user.click(screen.getByRole("button", { name: "应用知识范围" }));
    expect(service.setKnowledgeScope).toHaveBeenCalledWith("1", { mode: "selected", source_ids: [11] });
    await waitFor(() => expect(screen.getByLabelText("消息")).toBeEnabled());
  });

  it("blocks session creation while the session list is loading", async () => {
    let resolveSessions!: (value: { items: unknown[] }) => void;
    const delayedSessions = new Promise<{ items: unknown[] }>((resolve) => { resolveSessions = resolve; });
    const service = chat({ listSessions: vi.fn(async () => delayedSessions) });
    render(<ChatPage cache={cache()} knowledgeService={knowledge()} organizationId={7} service={service} stream={stream()} />);

    await waitFor(() => expect(service.listSessions).toHaveBeenCalled());
    const createButton = screen.getByRole("button", { name: "新建会话" });
    expect(createButton).toBeDisabled();
    createButton.click();
    expect(service.createSession).not.toHaveBeenCalled();

    await act(async () => { resolveSessions({ items: [] }); });
    expect(createButton).toBeEnabled();
  });

  it("blocks sending while selected-session messages are loading", async () => {
    let resolveMessages!: (value: { items: unknown[] }) => void;
    const delayedMessages = new Promise<{ items: unknown[] }>((resolve) => { resolveMessages = resolve; });
    const service = chat({ getMessages: vi.fn(async () => delayedMessages) });
    render(<ChatPage cache={cache()} knowledgeService={knowledge()} organizationId={7} service={service} stream={stream()} />);

    await screen.findByRole("button", { name: "客户分析" });
    expect(screen.getByLabelText("消息")).toBeDisabled();
    expect(screen.getByRole("button", { name: "发送" })).toBeDisabled();

    await act(async () => { resolveMessages({ items: [] }); });
    expect(screen.getByLabelText("消息")).toBeEnabled();
  });

  it("disables knowledge scope editing and rejects applying it while a message is sending", async () => {
    let resolveStream!: (response: Response) => void;
    const delayedStream = new Promise<Response>((resolve) => { resolveStream = resolve; });
    const service = chat({ listSessions: vi.fn(async () => ({ items: [
      { id: 1, title: "发送中会话", surface: "knowledge", knowledge_scope: "all_visible", source_ids: [] },
    ] })) });
    const chatStream = { sendMessageStream: vi.fn(async () => delayedStream) } as unknown as ChatStreamService;
    const user = userEvent.setup();
    render(<ChatPage cache={cache()} initialSurface="knowledge" knowledgeService={knowledge()} organizationId={7} service={service} stream={chatStream} />);

    await screen.findByRole("button", { name: "发送中会话" });
    await user.click(screen.getByRole("radio", { name: "指定知识" }));
    await user.click(await screen.findByRole("checkbox", { name: "员工手册" }));
    const applyButton = screen.getByRole("button", { name: "应用知识范围" });
    expect(applyButton).toBeEnabled();
    await user.type(screen.getByLabelText("消息"), "使用当前范围回答");
    await user.click(screen.getByRole("button", { name: "发送" }));

    expect(screen.getByRole("radio", { name: "全部可见知识" })).toBeDisabled();
    expect(screen.getByRole("radio", { name: "指定知识" })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: "员工手册" })).toBeDisabled();
    expect(applyButton).toBeDisabled();
    applyButton.click();
    expect(service.setKnowledgeScope).not.toHaveBeenCalled();

    await act(async () => { resolveStream(new Response("event: response.completed\ndata: {}\n\n")); });
  });

  it("does not reload the current session while its answer is streaming", async () => {
    let resolveStream!: (response: Response) => void;
    const delayedStream = new Promise<Response>((resolve) => { resolveStream = resolve; });
    const service = chat();
    const chatStream = { sendMessageStream: vi.fn(async () => delayedStream) } as unknown as ChatStreamService;
    const user = userEvent.setup();
    render(<ChatPage cache={cache()} knowledgeService={knowledge()} organizationId={7} service={service} stream={chatStream} />);

    const currentSession = await screen.findByRole("button", { name: "客户分析" });
    await user.type(screen.getByLabelText("消息"), "保持当前生成");
    await user.click(screen.getByRole("button", { name: "发送" }));
    expect(screen.getByText("正在生成...")).toBeInTheDocument();

    await user.click(currentSession);
    expect(service.getMessages).toHaveBeenCalledTimes(1);
    expect(screen.getByText("正在生成...")).toBeInTheDocument();

    await act(async () => { resolveStream(new Response("event: response.completed\ndata: {}\n\n")); });
  });

  it("disables and rejects session creation while a knowledge scope save is pending", async () => {
    let resolveScope!: (value: Record<string, unknown>) => void;
    const delayedScope = new Promise<Record<string, unknown>>((resolve) => { resolveScope = resolve; });
    const service = chat({
      listSessions: vi.fn(async () => ({ items: [
        { id: 1, title: "保存范围中", surface: "knowledge", knowledge_scope: "all_visible", source_ids: [] },
      ] })),
      setKnowledgeScope: vi.fn(async () => delayedScope),
    });
    const user = userEvent.setup();
    render(<ChatPage cache={cache()} initialSurface="knowledge" knowledgeService={knowledge()} organizationId={7} service={service} stream={stream()} />);

    await screen.findByRole("button", { name: "保存范围中" });
    await user.click(screen.getByRole("radio", { name: "指定知识" }));
    await user.click(await screen.findByRole("checkbox", { name: "员工手册" }));
    await user.click(screen.getByRole("button", { name: "应用知识范围" }));
    const createButton = screen.getByRole("button", { name: "新建会话" });
    expect(createButton).toBeDisabled();
    createButton.click();
    expect(service.createSession).not.toHaveBeenCalled();

    await act(async () => { resolveScope({}); });
    expect(createButton).toBeEnabled();
  });

  it("blocks sending to the previous session while a new session is being created", async () => {
    let resolveCreate!: (value: Record<string, unknown>) => void;
    const delayedCreate = new Promise<Record<string, unknown>>((resolve) => { resolveCreate = resolve; });
    const service = chat({ createSession: vi.fn(async () => delayedCreate) });
    const chatStream = stream();
    const user = userEvent.setup();
    render(<ChatPage cache={cache()} knowledgeService={knowledge()} organizationId={7} service={service} stream={chatStream} />);

    await screen.findByRole("button", { name: "客户分析" });
    await user.click(screen.getByRole("button", { name: "新建会话" }));

    expect(screen.getByLabelText("消息")).toBeDisabled();
    expect(screen.getByRole("button", { name: "发送" })).toBeDisabled();
    expect(chatStream.sendMessageStream).not.toHaveBeenCalled();

    await act(async () => { resolveCreate({ id: 2, title: "新会话", surface: "agent" }); });
    expect(screen.getByLabelText("消息")).toBeEnabled();
  });

  it("does not initialize an old organization knowledge session with new organization credentials", async () => {
    let resolveCreate!: (value: Record<string, unknown>) => void;
    const delayedCreate = new Promise<Record<string, unknown>>((resolve) => { resolveCreate = resolve; });
    const service = chat({
      createSession: vi.fn(async () => delayedCreate),
      listSessions: vi.fn(async () => ({ items: [] })),
    });
    const user = userEvent.setup();
    const view = render(<ChatPage cache={cache()} initialSurface="knowledge" knowledgeService={knowledge()} organizationId={7} service={service} stream={stream()} />);

    await user.click(await screen.findByRole("button", { name: "新建会话" }));
    view.rerender(<ChatPage cache={cache()} initialSurface="knowledge" knowledgeService={knowledge()} organizationId={8} service={service} stream={stream()} />);
    await act(async () => { resolveCreate({ id: 7, title: "组织 7 新会话", surface: "knowledge", knowledge_scope: "none", source_ids: [] }); });

    expect(service.setKnowledgeScope).not.toHaveBeenCalled();
    expect(service.deleteSession).not.toHaveBeenCalled();
  });

  it("clears the selected session when initial message loading fails", async () => {
    const service = chat({ getMessages: vi.fn(async () => { throw new Error("消息接口异常"); }) });
    const chatStream = stream();
    render(<ChatPage cache={cache()} knowledgeService={knowledge()} organizationId={7} service={service} stream={chatStream} />);

    expect(await screen.findByRole("alert")).toHaveTextContent("聊天会话加载失败");
    expect(screen.getByLabelText("消息")).toBeDisabled();
    expect(screen.getByRole("button", { name: "发送" })).toBeDisabled();
    expect(chatStream.sendMessageStream).not.toHaveBeenCalled();
  });

  it("clears the selected session when switching to a session whose messages fail to load", async () => {
    const service = chat({
      getMessages: vi.fn()
        .mockResolvedValueOnce({ items: [] })
        .mockRejectedValueOnce(new Error("消息接口异常")),
      listSessions: vi.fn(async () => ({ items: [
        { id: 1, title: "可用会话", surface: "agent" },
        { id: 2, title: "故障会话", surface: "agent" },
      ] })),
    });
    const chatStream = stream();
    const user = userEvent.setup();
    render(<ChatPage cache={cache()} knowledgeService={knowledge()} organizationId={7} service={service} stream={chatStream} />);

    await screen.findByRole("button", { name: "可用会话" });
    await user.click(screen.getByRole("button", { name: "故障会话" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("聊天会话加载失败");
    expect(screen.getByRole("button", { name: "可用会话" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "故障会话" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByLabelText("消息")).toBeDisabled();
    expect(screen.getByRole("button", { name: "发送" })).toBeDisabled();
    expect(chatStream.sendMessageStream).not.toHaveBeenCalled();
  });

  it("keeps a scope save owned by its session until the result is reconciled", async () => {
    let resolveScope!: (value: Record<string, unknown>) => void;
    const delayedScope = new Promise<Record<string, unknown>>((resolve) => { resolveScope = resolve; });
    const pageCache = cache();
    const service = chat({
      listSessions: vi.fn(async () => ({ items: [
        { id: 1, title: "迟到会话", surface: "knowledge", knowledge_scope: "all_visible", source_ids: [] },
        { id: 2, title: "当前会话", surface: "knowledge", knowledge_scope: "all_visible", source_ids: [] },
      ] })),
      setKnowledgeScope: vi.fn(async () => delayedScope),
    });
    const user = userEvent.setup();
    render(<ChatPage cache={pageCache} initialSurface="knowledge" knowledgeService={knowledge()} organizationId={7} service={service} stream={stream()} />);

    await screen.findByRole("button", { name: "迟到会话" });
    const cacheWritesBeforeSave = pageCache.set.mock.calls.length;
    await user.click(screen.getByRole("radio", { name: "指定知识" }));
    await user.click(screen.getByRole("checkbox", { name: "员工手册" }));
    await user.click(screen.getByRole("button", { name: "应用知识范围" }));
    const currentSession = screen.getByRole("button", { name: "当前会话" });
    expect(currentSession).toBeDisabled();
    currentSession.click();
    expect(screen.getByRole("button", { name: "迟到会话" })).toHaveAttribute("aria-pressed", "true");

    await act(async () => { resolveScope({}); });
    expect(screen.getByRole("radio", { name: "指定知识" })).toBeChecked();
    await user.click(currentSession);
    expect(screen.getByRole("radio", { name: "全部可见知识" })).toBeChecked();
    await user.click(screen.getByRole("button", { name: "迟到会话" }));
    expect(screen.getByRole("radio", { name: "指定知识" })).toBeChecked();
    expect(pageCache.set).toHaveBeenCalledTimes(cacheWritesBeforeSave + 1);
    expect(pageCache.set).toHaveBeenLastCalledWith(7, ["chat", "sessions", "knowledge"], [
      expect.objectContaining({ id: "1", knowledge_scope: "selected", source_ids: [11] }),
      expect.objectContaining({ id: "2", knowledge_scope: "all_visible", source_ids: [] }),
    ]);
  });

  it("ignores a delayed scope failure from a previous organization", async () => {
    let rejectScope!: (reason: Error) => void;
    const delayedScope = new Promise<Record<string, unknown>>((_resolve, reject) => { rejectScope = reject; });
    const pageCache = cache();
    const service = chat({
      listSessions: vi.fn()
        .mockResolvedValueOnce({ items: [{ id: 1, title: "组织 7 知识", surface: "knowledge", knowledge_scope: "all_visible", source_ids: [] }] })
        .mockResolvedValueOnce({ items: [{ id: 2, title: "组织 8 知识", surface: "knowledge", knowledge_scope: "all_visible", source_ids: [] }] }),
      setKnowledgeScope: vi.fn(async () => delayedScope),
    });
    const knowledgeService = knowledge();
    const chatStream = stream();
    const user = userEvent.setup();
    const view = render(<ChatPage cache={pageCache} initialSurface="knowledge" knowledgeService={knowledgeService} organizationId={7} service={service} stream={chatStream} />);

    await screen.findByRole("button", { name: "组织 7 知识" });
    await user.click(screen.getByRole("radio", { name: "指定知识" }));
    await user.click(screen.getByRole("checkbox", { name: "员工手册" }));
    await user.click(screen.getByRole("button", { name: "应用知识范围" }));
    view.rerender(<ChatPage cache={pageCache} initialSurface="knowledge" knowledgeService={knowledgeService} organizationId={8} service={service} stream={chatStream} />);
    await screen.findByRole("button", { name: "组织 8 知识" });
    const cacheWritesBeforeRejection = pageCache.set.mock.calls.length;

    await act(async () => { rejectScope(new Error("旧组织范围保存失败")); });
    expect(screen.queryByText("旧组织范围保存失败")).not.toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "全部可见知识" })).toBeChecked();
    expect(pageCache.set).toHaveBeenCalledTimes(cacheWritesBeforeRejection);
  });

  it("keeps sessions usable when loading knowledge entries fails", async () => {
    const service = chat({ listSessions: vi.fn(async () => ({ items: [
      { id: 1, title: "可用知识会话", surface: "knowledge", knowledge_scope: "all_visible", source_ids: [] },
    ] })) });
    const knowledgeService = knowledge({ listEntries: vi.fn(async () => { throw new Error("知识条目接口失败"); }) });
    render(<ChatPage cache={cache()} initialSurface="knowledge" knowledgeService={knowledgeService} organizationId={7} service={service} stream={stream()} />);

    expect(await screen.findByRole("button", { name: "可用知识会话" })).toBeInTheDocument();
    expect(await screen.findByRole("alert")).toHaveTextContent("知识条目加载失败");
    expect(screen.getByRole("alert")).not.toHaveTextContent("知识条目接口失败");
    expect(screen.getByLabelText("消息")).toBeEnabled();
  });

  it("shows a permission-specific knowledge entry error without exposing its detail", async () => {
    const service = chat({ listSessions: vi.fn(async () => ({ items: [
      { id: 1, title: "无知识权限", surface: "knowledge", knowledge_scope: "all_visible", source_ids: [] },
    ] })) });
    const forbidden = Object.assign(new Error("内部权限策略详情"), { status: 403 });
    const knowledgeService = knowledge({ listEntries: vi.fn(async () => { throw forbidden; }) });
    render(<ChatPage cache={cache()} initialSurface="knowledge" knowledgeService={knowledgeService} organizationId={7} service={service} stream={stream()} />);

    await screen.findByRole("button", { name: "无知识权限" });
    expect(await screen.findByRole("alert")).toHaveTextContent("没有知识库访问权限");
    expect(screen.getByRole("alert")).not.toHaveTextContent("内部权限策略详情");
  });

  it("blocks sending while a knowledge scope save is pending", async () => {
    let resolveScope!: (value: Record<string, unknown>) => void;
    const delayedScope = new Promise<Record<string, unknown>>((resolve) => { resolveScope = resolve; });
    const service = chat({
      listSessions: vi.fn(async () => ({ items: [
        { id: 1, title: "待保存范围", surface: "knowledge", knowledge_scope: "all_visible", source_ids: [] },
      ] })),
      setKnowledgeScope: vi.fn(async () => delayedScope),
    });
    const user = userEvent.setup();
    render(<ChatPage cache={cache()} initialSurface="knowledge" knowledgeService={knowledge()} organizationId={7} service={service} stream={stream()} />);

    await screen.findByRole("button", { name: "待保存范围" });
    await user.click(screen.getByRole("radio", { name: "指定知识" }));
    await user.click(screen.getByRole("checkbox", { name: "员工手册" }));
    await user.click(screen.getByRole("button", { name: "应用知识范围" }));
    expect(screen.getByLabelText("消息")).toBeDisabled();
    expect(screen.getByRole("button", { name: "发送" })).toBeDisabled();

    await act(async () => { resolveScope({}); });
    expect(screen.getByLabelText("消息")).toBeEnabled();
  });

  it("renders streamed knowledge citations and resolves the authorized source before previewing it", async () => {
    const response = { ok: true, text: async () => [
      'event: knowledge.context\ndata: {"turn_id":9,"mode":"hybrid","rejected_source_count":2,"citations":[{"ordinal":0,"entry_id":11,"title":"员工手册","content_sha256":"snapshot-sha","source_locator":"第 2 页"}]}',
      'event: response.output_text.delta\ndata: {"delta":"请假需要提前申请。"}',
      'event: response.completed\ndata: {}',
    ].join("\n\n") };
    const service = chat({ listSessions: vi.fn(async () => ({ items: [
      { id: 1, title: "知识引用会话", surface: "knowledge", knowledge_scope: "all_visible", source_ids: [] },
    ] })) });
    const knowledgeService = knowledge({
      resolveCitation: vi.fn(async () => ({
        turn_id: 9,
        ordinal: 0,
        entry_id: 22,
        title: "员工手册",
        content_sha256: "authorized-sha",
        source_locator: "第 3 页",
      })),
      previewContent: vi.fn(async () => ({
        entry_id: 22,
        title: "员工手册（当前授权版本）",
        content: "员工请假应提前提交申请。",
      })),
    });
    const chatStream = stream(response);
    const user = userEvent.setup();
    render(<ChatPage cache={cache()} initialSurface="knowledge" knowledgeService={knowledgeService} organizationId={7} service={service} stream={chatStream} />);

    await screen.findByRole("button", { name: "知识引用会话" });
    await user.type(screen.getByLabelText("消息"), "如何请假？");
    await user.click(screen.getByRole("button", { name: "发送" }));

    expect((chatStream.sendMessageStream as ReturnType<typeof vi.fn>).mock.calls[0]?.[1]).not.toHaveProperty("source_ids");

    expect(await screen.findByText("知识来源")).toBeInTheDocument();
    expect(screen.getByText("检索方式：混合检索")).toBeInTheDocument();
    expect(screen.getByText("有 2 个来源当前不可用")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "员工手册" }));

    expect(knowledgeService.resolveCitation).toHaveBeenCalledWith("9", 0);
    expect(knowledgeService.previewContent).toHaveBeenCalledWith(22);
    const resolveOrder = (knowledgeService.resolveCitation as ReturnType<typeof vi.fn>).mock.invocationCallOrder[0];
    const previewOrder = (knowledgeService.previewContent as ReturnType<typeof vi.fn>).mock.invocationCallOrder[0];
    expect(resolveOrder).toBeLessThan(previewOrder);
    expect(await screen.findByText("员工手册（当前授权版本）")).toBeInTheDocument();
    expect(screen.getByText("员工请假应提前提交申请。")).toBeInTheDocument();
    expect(screen.getByText("第 3 页")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "关闭来源预览" }));
    expect(screen.queryByText("员工请假应提前提交申请。")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "员工手册" })).toHaveFocus();
  });

  it("restores historical knowledge citations and retrieval metadata", async () => {
    const service = chat({
      getMessages: vi.fn(async () => ({ items: [
        { id: "history-user", role: "user", content: "制度是什么？" },
        {
          id: "history-assistant",
          role: "assistant",
          content: "制度摘要。",
          turn_id: 18,
          citations: [{ ordinal: 1, entry_id: null, title: "制度文件", content_sha256: "history-sha", source_locator: null }],
          retrieval_mode: "degraded_full_text",
          rejected_source_count: 1,
        },
      ] })),
      listSessions: vi.fn(async () => ({ items: [
        { id: 1, title: "历史知识会话", surface: "knowledge", knowledge_scope: "all_visible", source_ids: [] },
      ] })),
    });
    const knowledgeService = knowledge({
      resolveCitation: vi.fn(async () => ({ entry_id: 28, source_locator: "历史第 4 页" })),
      previewContent: vi.fn(async () => ({ entry_id: 28, title: "制度文件（当前版本）", content: "历史来源正文" })),
    });
    const user = userEvent.setup();
    render(<ChatPage cache={cache()} initialSurface="knowledge" knowledgeService={knowledgeService} organizationId={7} service={service} stream={stream()} />);

    await waitFor(() => expect(screen.getByText("制度摘要。")).toBeInTheDocument());
    expect(screen.getByText("知识来源")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "制度文件" })).toBeInTheDocument();
    expect(screen.getByText("检索方式：全文检索（降级）")).toBeInTheDocument();
    expect(screen.getByText("有 1 个来源当前不可用")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "制度文件" }));
    expect(knowledgeService.resolveCitation).toHaveBeenCalledWith("18", 1);
    expect(knowledgeService.previewContent).toHaveBeenCalledWith(28);
    expect(await screen.findByText("历史来源正文")).toBeInTheDocument();
  });

  it("clears the previous preview immediately and reports a citation permission failure safely", async () => {
    let rejectForbidden!: (reason: Error) => void;
    const forbiddenRequest = new Promise<Record<string, unknown>>((_resolve, reject) => { rejectForbidden = reject; });
    const service = chat({
      getMessages: vi.fn(async () => ({ items: [{
        id: "history-assistant",
        role: "assistant",
        content: "引用回答",
        turn_id: 21,
        citations: [
          { ordinal: 0, entry_id: 11, title: "可用来源", content_sha256: "sha-1", source_locator: "第 1 页" },
          { ordinal: 1, entry_id: 12, title: "无权来源", content_sha256: "sha-2", source_locator: "第 2 页" },
        ],
        retrieval_mode: "hybrid",
        rejected_source_count: 0,
      }] })),
      listSessions: vi.fn(async () => ({ items: [
        { id: 1, title: "权限测试会话", surface: "knowledge", knowledge_scope: "all_visible", source_ids: [] },
      ] })),
    });
    const knowledgeService = knowledge({
      resolveCitation: vi.fn()
        .mockResolvedValueOnce({ entry_id: 31, source_locator: "当前第 1 页" })
        .mockImplementationOnce(() => forbiddenRequest),
      previewContent: vi.fn(async () => ({ entry_id: 31, title: "已打开来源", content: "旧预览正文" })),
    });
    const user = userEvent.setup();
    render(<ChatPage cache={cache()} initialSurface="knowledge" knowledgeService={knowledgeService} organizationId={7} service={service} stream={stream()} />);

    await user.click(await screen.findByRole("button", { name: "可用来源" }));
    expect(await screen.findByText("旧预览正文")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "无权来源" }));
    expect(screen.queryByText("旧预览正文")).not.toBeInTheDocument();

    const forbidden = Object.assign(new Error("内部授权策略详情"), { status: 403 });
    await act(async () => { rejectForbidden(forbidden); });
    expect(await screen.findByRole("alert")).toHaveTextContent("没有知识来源访问权限");
    expect(screen.getByRole("alert")).not.toHaveTextContent("内部授权策略详情");
  });

  it("shows a generic citation error without exposing service details", async () => {
    const service = chat({
      getMessages: vi.fn(async () => ({ items: [{
        id: "history-assistant",
        role: "assistant",
        content: "引用回答",
        turn_id: 22,
        citations: [{ ordinal: 0, entry_id: 11, title: "故障来源", content_sha256: "sha" }],
        retrieval_mode: "hybrid",
      }] })),
      listSessions: vi.fn(async () => ({ items: [
        { id: 1, title: "故障测试会话", surface: "knowledge", knowledge_scope: "all_visible", source_ids: [] },
      ] })),
    });
    const knowledgeService = knowledge({ resolveCitation: vi.fn(async () => { throw new Error("对象存储内部错误"); }) });
    const user = userEvent.setup();
    render(<ChatPage cache={cache()} initialSurface="knowledge" knowledgeService={knowledgeService} organizationId={7} service={service} stream={stream()} />);

    await user.click(await screen.findByRole("button", { name: "故障来源" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("知识来源当前不可用");
    expect(screen.getByRole("alert")).not.toHaveTextContent("对象存储内部错误");
  });

  it("clears an existing preview when current content preview fails", async () => {
    const service = chat({
      getMessages: vi.fn(async () => ({ items: [{
        id: "history-assistant",
        role: "assistant",
        content: "两个正文来源",
        turn_id: 29,
        citations: [
          { ordinal: 0, entry_id: 11, title: "已打开正文", content_sha256: "sha-1" },
          { ordinal: 1, entry_id: 12, title: "失效正文", content_sha256: "sha-2" },
        ],
        retrieval_mode: "hybrid",
      }] })),
      listSessions: vi.fn(async () => ({ items: [{ id: 1, title: "正文失败会话", surface: "knowledge", knowledge_scope: "all_visible", source_ids: [] }] })),
    });
    const missing = Object.assign(new Error("内部存储详情"), { status: 404 });
    const knowledgeService = knowledge({
      resolveCitation: vi.fn()
        .mockResolvedValueOnce({ entry_id: 61 })
        .mockResolvedValueOnce({ entry_id: 62 }),
      previewContent: vi.fn()
        .mockResolvedValueOnce({ entry_id: 61, title: "已打开正文", content: "必须清空的旧正文" })
        .mockRejectedValueOnce(missing),
    });
    const user = userEvent.setup();
    render(<ChatPage cache={cache()} initialSurface="knowledge" knowledgeService={knowledgeService} organizationId={7} service={service} stream={stream()} />);

    await user.click(await screen.findByRole("button", { name: "已打开正文" }));
    expect(await screen.findByText("必须清空的旧正文")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "失效正文" }));
    expect(screen.queryByText("必须清空的旧正文")).not.toBeInTheDocument();
    expect(await screen.findByRole("alert")).toHaveTextContent("知识来源当前不可用");
    expect(screen.getByRole("alert")).not.toHaveTextContent("内部存储详情");
  });

  it("renders incomplete citation metadata as explained text instead of a disabled control", async () => {
    const service = chat({
      getMessages: vi.fn(async () => ({ items: [{
        id: "incomplete-assistant",
        role: "assistant",
        content: "不完整引用回答",
        citations: [{ ordinal: 0, entry_id: 11, title: "缺少轮次的来源", content_sha256: "sha" }],
        retrieval_mode: "hybrid",
      }] })),
      listSessions: vi.fn(async () => ({ items: [{ id: 1, title: "不完整引用会话", surface: "knowledge", knowledge_scope: "all_visible", source_ids: [] }] })),
    });
    render(<ChatPage cache={cache()} initialSurface="knowledge" knowledgeService={knowledge()} organizationId={7} service={service} stream={stream()} />);

    expect(await screen.findByText("缺少轮次的来源")).toBeInTheDocument();
    expect(screen.getByText("来源详情当前不可用")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "缺少轮次的来源" })).not.toBeInTheDocument();
  });

  it("lets a later citation click supersede a delayed content preview", async () => {
    let resolveFirstPreview!: (value: Record<string, unknown>) => void;
    const firstPreview = new Promise<Record<string, unknown>>((resolve) => { resolveFirstPreview = resolve; });
    const service = chat({
      getMessages: vi.fn(async () => ({ items: [{
        id: "history-assistant",
        role: "assistant",
        content: "两个预览来源",
        turn_id: 30,
        citations: [
          { ordinal: 0, entry_id: 11, title: "迟到正文", content_sha256: "sha-1" },
          { ordinal: 1, entry_id: 12, title: "当前正文", content_sha256: "sha-2" },
        ],
        retrieval_mode: "hybrid",
      }] })),
      listSessions: vi.fn(async () => ({ items: [{ id: 1, title: "正文代次会话", surface: "knowledge", knowledge_scope: "all_visible", source_ids: [] }] })),
    });
    const knowledgeService = knowledge({
      resolveCitation: vi.fn()
        .mockResolvedValueOnce({ entry_id: 71 })
        .mockResolvedValueOnce({ entry_id: 72 }),
      previewContent: vi.fn()
        .mockImplementationOnce(() => firstPreview)
        .mockResolvedValueOnce({ entry_id: 72, title: "当前正文", content: "当前正文内容" }),
    });
    const user = userEvent.setup();
    render(<ChatPage cache={cache()} initialSurface="knowledge" knowledgeService={knowledgeService} organizationId={7} service={service} stream={stream()} />);

    await user.click(await screen.findByRole("button", { name: "迟到正文" }));
    await waitFor(() => expect(knowledgeService.previewContent).toHaveBeenCalledWith(71));
    await user.click(screen.getByRole("button", { name: "当前正文" }));
    expect(await screen.findByText("当前正文内容")).toBeInTheDocument();

    await act(async () => { resolveFirstPreview({ entry_id: 71, title: "迟到正文", content: "不应出现的迟到正文" }); });
    expect(screen.getByText("当前正文内容")).toBeInTheDocument();
    expect(screen.queryByText("不应出现的迟到正文")).not.toBeInTheDocument();
  });

  it("lets a later citation click supersede a delayed resolve request", async () => {
    let resolveFirst!: (value: Record<string, unknown>) => void;
    const firstRequest = new Promise<Record<string, unknown>>((resolve) => { resolveFirst = resolve; });
    const service = chat({
      getMessages: vi.fn(async () => ({ items: [{
        id: "history-assistant",
        role: "assistant",
        content: "两个来源",
        turn_id: 23,
        citations: [
          { ordinal: 0, entry_id: 11, title: "迟到来源", content_sha256: "sha-1" },
          { ordinal: 1, entry_id: 12, title: "当前来源", content_sha256: "sha-2" },
        ],
        retrieval_mode: "hybrid",
      }] })),
      listSessions: vi.fn(async () => ({ items: [
        { id: 1, title: "点击代次会话", surface: "knowledge", knowledge_scope: "all_visible", source_ids: [] },
      ] })),
    });
    const knowledgeService = knowledge({
      resolveCitation: vi.fn()
        .mockImplementationOnce(() => firstRequest)
        .mockResolvedValueOnce({ entry_id: 42, source_locator: "当前位置" }),
      previewContent: vi.fn(async (entryId) => ({ entry_id: entryId, title: "当前预览", content: "当前预览正文" })),
    });
    const user = userEvent.setup();
    render(<ChatPage cache={cache()} initialSurface="knowledge" knowledgeService={knowledgeService} organizationId={7} service={service} stream={stream()} />);

    await user.click(await screen.findByRole("button", { name: "迟到来源" }));
    await user.click(screen.getByRole("button", { name: "当前来源" }));
    expect(await screen.findByText("当前预览正文")).toBeInTheDocument();

    await act(async () => { resolveFirst({ entry_id: 41, source_locator: "迟到位置" }); });
    expect(screen.getByText("当前预览正文")).toBeInTheDocument();
    expect(knowledgeService.previewContent).toHaveBeenCalledTimes(1);
    expect(knowledgeService.previewContent).toHaveBeenCalledWith(42);
  });

  it("invalidates delayed citation resolution when its session, organization, surface, or mount ownership changes", async () => {
    for (const invalidation of ["session", "organization", "surface", "unmount"] as const) {
      let resolveCitation!: (value: Record<string, unknown>) => void;
      const delayedCitation = new Promise<Record<string, unknown>>((resolve) => { resolveCitation = resolve; });
      const service = chat({
        getMessages: vi.fn(async (sessionId) => ({ items: sessionId === "1" ? [{
          id: `assistant-${invalidation}`,
          role: "assistant",
          content: "延迟引用回答",
          turn_id: 24,
          citations: [{ ordinal: 0, entry_id: 11, title: `延迟来源-${invalidation}`, content_sha256: "sha" }],
          retrieval_mode: "hybrid",
        }] : [] })),
        listSessions: vi.fn(async (query) => ({ items: query?.surface === "agent" ? [
          { id: 3, title: "普通会话", surface: "agent" },
        ] : [
          { id: 1, title: "知识会话一", surface: "knowledge", knowledge_scope: "all_visible", source_ids: [] },
          { id: 2, title: "知识会话二", surface: "knowledge", knowledge_scope: "all_visible", source_ids: [] },
        ] })),
      });
      const knowledgeService = knowledge({
        resolveCitation: vi.fn(async () => delayedCitation),
        previewContent: vi.fn(async () => ({ entry_id: 51, title: "不应出现", content: "迟到预览正文" })),
      });
      const user = userEvent.setup();
      const view = render(<ChatPage cache={cache()} initialSurface="knowledge" knowledgeService={knowledgeService} organizationId={7} service={service} stream={stream()} />);

      await user.click(await screen.findByRole("button", { name: `延迟来源-${invalidation}` }));
      await waitFor(() => expect(knowledgeService.resolveCitation).toHaveBeenCalledTimes(1));
      if (invalidation === "session") await user.click(screen.getByRole("button", { name: "知识会话二" }));
      if (invalidation === "organization") view.rerender(<ChatPage cache={cache()} initialSurface="knowledge" knowledgeService={knowledgeService} organizationId={8} service={service} stream={stream()} />);
      if (invalidation === "surface") await user.click(screen.getByRole("button", { name: "普通对话" }));
      if (invalidation === "unmount") view.unmount();

      await act(async () => { resolveCitation({ entry_id: 51, source_locator: "迟到位置" }); });
      expect(knowledgeService.previewContent).not.toHaveBeenCalled();
      if (invalidation !== "unmount") {
        expect(screen.queryByText("迟到预览正文")).not.toBeInTheDocument();
        view.unmount();
      }
    }
  });

  it("invalidates delayed content preview when session, organization, surface, or mount ownership changes", async () => {
    for (const invalidation of ["session", "organization", "surface", "unmount"] as const) {
      let resolvePreview!: (value: Record<string, unknown>) => void;
      const delayedPreview = new Promise<Record<string, unknown>>((resolve) => { resolvePreview = resolve; });
      const service = chat({
        getMessages: vi.fn(async (sessionId) => ({ items: sessionId === "1" ? [{
          id: `preview-assistant-${invalidation}`,
          role: "assistant",
          content: "延迟正文回答",
          turn_id: 31,
          citations: [{ ordinal: 0, entry_id: 11, title: `延迟正文-${invalidation}`, content_sha256: "sha" }],
          retrieval_mode: "hybrid",
        }] : [] })),
        listSessions: vi.fn(async (query) => ({ items: query?.surface === "agent" ? [
          { id: 3, title: "普通会话", surface: "agent" },
        ] : [
          { id: 1, title: "正文知识会话一", surface: "knowledge", knowledge_scope: "all_visible", source_ids: [] },
          { id: 2, title: "正文知识会话二", surface: "knowledge", knowledge_scope: "all_visible", source_ids: [] },
        ] })),
      });
      const knowledgeService = knowledge({
        resolveCitation: vi.fn(async () => ({ entry_id: 81 })),
        previewContent: vi.fn(async () => delayedPreview),
      });
      const user = userEvent.setup();
      const view = render(<ChatPage cache={cache()} initialSurface="knowledge" knowledgeService={knowledgeService} organizationId={7} service={service} stream={stream()} />);

      await user.click(await screen.findByRole("button", { name: `延迟正文-${invalidation}` }));
      await waitFor(() => expect(knowledgeService.previewContent).toHaveBeenCalledWith(81));
      if (invalidation === "session") await user.click(screen.getByRole("button", { name: "正文知识会话二" }));
      if (invalidation === "organization") view.rerender(<ChatPage cache={cache()} initialSurface="knowledge" knowledgeService={knowledgeService} organizationId={8} service={service} stream={stream()} />);
      if (invalidation === "surface") await user.click(screen.getByRole("button", { name: "普通对话" }));
      if (invalidation === "unmount") view.unmount();

      await act(async () => { resolvePreview({ entry_id: 81, title: "不应出现", content: "不应出现的延迟正文" }); });
      if (invalidation !== "unmount") {
        expect(screen.queryByText("不应出现的延迟正文")).not.toBeInTheDocument();
        view.unmount();
      }
    }
  });

  it("cancels a loading content preview and restores focus to its citation", async () => {
    let resolvePreview!: (value: Record<string, unknown>) => void;
    const delayedPreview = new Promise<Record<string, unknown>>((resolve) => { resolvePreview = resolve; });
    const service = chat({
      getMessages: vi.fn(async () => ({ items: [{
        id: "cancel-preview-assistant",
        role: "assistant",
        content: "可取消预览",
        turn_id: 32,
        citations: [{ ordinal: 0, entry_id: 11, title: "可取消来源", content_sha256: "sha" }],
        retrieval_mode: "hybrid",
      }] })),
      listSessions: vi.fn(async () => ({ items: [{ id: 1, title: "取消预览会话", surface: "knowledge", knowledge_scope: "all_visible", source_ids: [] }] })),
    });
    const knowledgeService = knowledge({
      resolveCitation: vi.fn(async () => ({ entry_id: 91 })),
      previewContent: vi.fn(async () => delayedPreview),
    });
    const user = userEvent.setup();
    render(<ChatPage cache={cache()} initialSurface="knowledge" knowledgeService={knowledgeService} organizationId={7} service={service} stream={stream()} />);

    const trigger = await screen.findByRole("button", { name: "可取消来源" });
    await user.click(trigger);
    expect(await screen.findByRole("status", { name: "知识来源预览" })).toHaveTextContent("知识来源加载中");
    await user.click(screen.getByRole("button", { name: "关闭来源预览" }));
    expect(trigger).toHaveFocus();

    await act(async () => { resolvePreview({ entry_id: 91, title: "不应出现", content: "取消后迟到正文" }); });
    expect(screen.queryByText("取消后迟到正文")).not.toBeInTheDocument();
  });

  it("does not render knowledge citation metadata on an agent conversation", async () => {
    const service = chat({ getMessages: vi.fn(async () => ({ items: [{
      id: "agent-assistant",
      role: "assistant",
      content: "普通回答",
      turn_id: 25,
      citations: [{ ordinal: 0, entry_id: 11, title: "不应展示的知识来源", content_sha256: "sha" }],
      retrieval_mode: "hybrid",
      rejected_source_count: 2,
    }] })) });
    const knowledgeService = knowledge({ resolveCitation: vi.fn(), previewContent: vi.fn() });
    render(<ChatPage cache={cache()} initialSurface="agent" knowledgeService={knowledgeService} organizationId={7} service={service} stream={stream()} />);

    await waitFor(() => expect(screen.getByText("普通回答")).toBeInTheDocument());
    expect(screen.queryByText("知识来源")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "不应展示的知识来源" })).not.toBeInTheDocument();
    expect(screen.queryByText("检索方式：混合检索")).not.toBeInTheDocument();
    expect(screen.queryByText("有 2 个来源当前不可用")).not.toBeInTheDocument();
    expect(knowledgeService.resolveCitation).not.toHaveBeenCalled();
    expect(knowledgeService.previewContent).not.toHaveBeenCalled();
  });
});
