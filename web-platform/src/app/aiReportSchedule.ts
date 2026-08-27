const CHINESE_WEEKDAYS: Record<string, number> = {
  一: 1,
  二: 2,
  三: 3,
  四: 4,
  五: 5,
  六: 6,
  日: 0,
  天: 0,
};

const ENGLISH_WEEKDAYS: Record<string, number> = {
  sun: 0,
  sunday: 0,
  mon: 1,
  monday: 1,
  tue: 2,
  tues: 2,
  tuesday: 2,
  wed: 3,
  weds: 3,
  wednesday: 3,
  thu: 4,
  thurs: 4,
  thursday: 4,
  fri: 5,
  friday: 5,
  sat: 6,
  saturday: 6,
};

function normalizePrompt(prompt: string): string {
  return String(prompt || "")
    .toLowerCase()
    .replace(/[，。！？；：、]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function parseWeekday(prompt: string): number | null {
  const chinese = prompt.match(
    /(?:每\s*(?:个\s*)?(?:周|星期|礼拜)|每逢\s*(?:周|星期|礼拜))\s*(?:的\s*)?(?:星期\s*)?([一二三四五六日天])/u,
  );
  if (chinese) return CHINESE_WEEKDAYS[chinese[1]] ?? null;

  const english = prompt.match(
    /(?:every\s+|weekly(?:\s+on)?\s+)(sun(?:day)?|mon(?:day)?|t(?:ue|ues)(?:sday)?|wed(?:nesday)?|th(?:u|urs)(?:rsday)?|fri(?:day)?|sat(?:urday)?)(?:s)?\b/u,
  );
  if (english) return ENGLISH_WEEKDAYS[english[1]] ?? null;

  return null;
}

export type AiReportSchedule = { weekday: number };

export function parseAiReportSchedule(prompt: string): AiReportSchedule | null {
  const normalized = normalizePrompt(prompt);
  if (!normalized) return null;

  const hasAiTopic = /(?:\bai\b|人工智能)/u.test(normalized);
  const hasReport = /(?:周报|报告|weekly\s+report|ai\s+report)/u.test(normalized);
  if (!hasAiTopic || !hasReport) return null;

  const weekday = parseWeekday(normalized);
  return weekday === null ? null : { weekday };
}

export function isScheduledAiNewsPrompt(prompt: string): boolean {
  return parseAiReportSchedule(prompt) !== null;
}
