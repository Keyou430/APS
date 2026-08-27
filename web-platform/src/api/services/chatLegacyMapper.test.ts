import { describe, expect, it } from "vitest";
import {
  mapChatMessagesToLegacyMessages,
  mapChatSessionsToLegacySessions,
} from "./chatLegacyMapper";

describe("chat legacy mapper", () => {
  it("maps contract sessions to legacy sessions", () => {
    const sessions = mapChatSessionsToLegacySessions({
      items: [
        {
          id: "s1",
          title: "契约联调",
          created_at: "2026-08-12T01:02:03Z",
          updated_at: "2026-08-12T02:03:04Z",
        },
      ],
    });

    expect(sessions).toEqual([
      {
        createdAt: "2026-08-12 01:02",
        id: "s1",
        messages: [],
        title: "契约联调",
        updatedAt: "2026-08-12 02:03",
      },
    ]);
  });

  it("maps contract messages to legacy transcript messages", () => {
    const messages = mapChatMessagesToLegacyMessages({
      items: [
        {
          id: 7,
          role: "assistant",
          content: "完成",
          created_at: "2026-08-12T02:03:04Z",
        },
      ],
    });

    expect(messages).toEqual([
      {
        content: "完成",
        createdAt: "02:03",
        id: "m_bk_7",
        role: "assistant",
        status: "completed",
      },
    ]);
  });
});
