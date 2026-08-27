import { describe, expect, it } from "vitest";
import { isScheduledAiNewsPrompt, parseAiReportSchedule } from "./aiReportSchedule";

describe("AI report schedule parser", () => {
  it.each([
    ["每周三生成 AI 周报", 3],
    ["每周的星期三发送 AI 周报", 3],
    ["每星期星期五发送人工智能报告", 5],
    ["每逢礼拜日整理 AI 周报", 0],
    ["every Wednesday send an AI weekly report", 3],
    ["weekly on Monday: AI report", 1],
  ])("recognizes %s", (prompt, weekday) => {
    expect(parseAiReportSchedule(prompt)?.weekday).toBe(weekday);
    expect(isScheduledAiNewsPrompt(prompt)).toBe(true);
  });

  it.each(["本周三生成 AI 周报", "每月三号生成 AI 周报", "每周三整理销售周报"])(
    "rejects non-matching prompt %s",
    (prompt) => {
      expect(parseAiReportSchedule(prompt)).toBeNull();
      expect(isScheduledAiNewsPrompt(prompt)).toBe(false);
    },
  );
});
