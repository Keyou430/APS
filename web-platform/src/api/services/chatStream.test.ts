import { describe, expect, it } from "vitest";
import { createChatStreamService, parseSseFrames } from "./chatStream";

describe("chat stream", () => {
  it("parses SSE frames with event names and JSON payloads", () => {
    const frames = parseSseFrames(
      'event: response.output_text.delta\ndata: {"delta":"Hi"}\n\n' +
        'event: response.completed\ndata: {"run_id":"r1"}\n\n',
    );

    expect(frames).toEqual([
      { event: "response.output_text.delta", data: { delta: "Hi" } },
      { event: "response.completed", data: { run_id: "r1" } },
    ]);
  });

  it("reserves the SSE message endpoint with event-stream accept header", async () => {
    const calls: unknown[] = [];
    const service = createChatStreamService({
      fetchFn: async (url, init) => {
        calls.push([url, init]);
        return new Response("", {
          headers: { "content-type": "text/event-stream" },
          status: 200,
        });
      },
      getAccessToken: () => "token",
    });

    await service.sendMessageStream("s1", { content: "hello" });

    expect(calls).toEqual([
      [
        "/api/chat/sessions/s1/messages",
        {
          body: JSON.stringify({ content: "hello" }),
          headers: {
            Accept: "text/event-stream",
            Authorization: "Bearer token",
            "Content-Type": "application/json",
          },
          method: "POST",
          signal: undefined,
        },
      ],
    ]);
  });

  it("refreshes once and replays a stream after an expired access token", async () => {
    let token = "expired";
    const refresh = async () => {
      token = "fresh";
    };
    const calls: Array<Record<string, unknown>> = [];
    const service = createChatStreamService({
      getAccessToken: () => token,
      refresh,
      fetchFn: async (_url, init) => {
        calls.push(init?.headers as Record<string, unknown>);
        if (calls.length === 1) return new Response(null, { status: 401 });
        return new Response("", { status: 200, headers: { "content-type": "text/event-stream" } });
      },
    });

    await expect(service.sendMessageStream("s1", { content: "hello" })).resolves.toMatchObject({ status: 200 });
    expect(calls).toEqual([
      expect.objectContaining({ Authorization: "Bearer expired" }),
      expect.objectContaining({ Authorization: "Bearer fresh" }),
    ]);
  });
});
