import { describe, expect, it } from "vitest"
import { getFreshnessNotice, hasFreshnessEvidence, isFreshAiRequest } from "./chatEvidence"

describe("chat freshness evidence", () => {
  it("recognizes recent AI requests", () => {
    expect(isFreshAiRequest("最近的 AI 动态")).toBe(true)
    expect(isFreshAiRequest("请总结本周会议纪要")).toBe(false)
  })

  it("only platform-validated web evidence proves freshness", () => {
    // Model text can never prove freshness: URLs written into the answer body
    // are model-generated and must not count.
    expect(hasFreshnessEvidence({ content: "来源：https://example.com/news" })).toBe(false)
    expect(
      hasFreshnessEvidence({ content: "来源：IT之家，检索时间：2026-08-22 00:00" }),
    ).toBe(false)
    // Knowledge citations are not web freshness proof either.
    expect(hasFreshnessEvidence({ content: "概览", references: [{ title: "来源" }] })).toBe(false)
    expect(hasFreshnessEvidence({ content: "概览" })).toBe(false)
    expect(
      hasFreshnessEvidence({
        content: "概览",
        webEvidence: [{ url: "https://example.com/news", searched_at: "2026-08-22T01:00:00Z" }],
      }),
    ).toBe(true)
  })

  it("distinguishes a missing source after web search from no search", () => {
    const answer = { status: "completed", content: "一些动态概览" }
    expect(getFreshnessNotice({ userContent: "最近的 AI 动态", answer, webSearchUsed: true })).toContain(
      "已执行联网检索",
    )
    expect(getFreshnessNotice({ userContent: "最近的 AI 动态", answer, webSearchUsed: true })).toContain(
      "平台校验的来源引用",
    )
    expect(getFreshnessNotice({ userContent: "最近的 AI 动态", answer })).toContain(
      "未检测到联网来源",
    )
    expect(
      getFreshnessNotice({
        userContent: "最近的 AI 动态",
        answer: { ...answer, content: "来源：IT之家，检索时间：2026-08-22 00:00" },
      }),
    ).toContain("不能证明")
  })

  it("a validated web source removes the freshness warning even if the model also wrote a URL", () => {
    expect(
      getFreshnessNotice({
        userContent: "最近的 AI 动态",
        answer: {
          status: "completed",
          content: "来源：https://example.com",
          webEvidence: [{ url: "https://example.com/news", searched_at: "2026-08-22T01:00:00Z" }],
        },
        webSearchUsed: true,
      }),
    ).toBe("")
  })

  it("a failed web search keeps the warning visible", () => {
    expect(
      getFreshnessNotice({
        userContent: "最近的 AI 动态",
        answer: { status: "completed", content: "概览" },
        webSearchUsed: true,
        webSearchFailed: true,
      }),
    ).not.toBe("")
  })
})
