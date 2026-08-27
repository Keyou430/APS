export interface ChatEvidenceAnswer {
  content?: string
  /** Knowledge citations; never freshness proof. */
  references?: unknown[]
  /** Platform-validated web evidence (web.search.completed / history web_sources). */
  webEvidence?: unknown[]
  status?: string
}

const FRESH_AI_REQUEST = /(?:最近|最新|近期).{0,12}(?:AI|人工智能)|(?:AI|人工智能).{0,12}(?:最近|最新|近期)/u
const LIVE_RETRIEVAL_TIME = /检索时间|搜索时间|检索于|retrieved(?: at| on)|searched(?: at| on)/iu

export function isFreshAiRequest(content: string): boolean {
  return FRESH_AI_REQUEST.test(String(content || ""))
}

export function hasFreshnessEvidence(answer: ChatEvidenceAnswer): boolean {
  // Only platform-validated web evidence proves freshness. Model-written URLs,
  // retrieval-time strings, and knowledge citations are not proof.
  return Array.isArray(answer.webEvidence) && answer.webEvidence.length > 0
}

export function getFreshnessNotice({
  userContent,
  answer,
  webSearchUsed = false,
  webSearchFailed = false,
}: {
  userContent: string
  answer: ChatEvidenceAnswer
  webSearchUsed?: boolean
  webSearchFailed?: boolean
}): string {
  if (answer.status !== "completed" || !isFreshAiRequest(userContent) || hasFreshnessEvidence(answer)) {
    return ""
  }
  if (webSearchFailed) {
    return "联网搜索已执行但失败；本回答没有可验证来源，不能证明“最近”或“最新”。"
  }
  if (webSearchUsed) {
    return "已执行联网检索，但未收到平台校验的来源引用；本回答不能证明“最近”或“最新”。"
  }
  if (LIVE_RETRIEVAL_TIME.test(String(answer.content || ""))) {
    return "检测到检索时间字样，但没有平台校验的来源引用；本回答不能证明“最近”或“最新”。"
  }
  return "未检测到联网来源或检索时间；本回答不是实时动态，不能证明“最近”或“最新”。"
}
