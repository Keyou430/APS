import { useCallback, useEffect, useMemo, useState } from "react";
import type {
  PipelineDecision,
  PipelineOutput,
  PipelineService,
  PipelineTask,
  PipelineTaskDraft,
} from "../api/services/pipelineService";
import { renderSafeAssistantMarkdown } from "../security/safeMarkdown";
import {
  asObject,
  errorStatus,
  readArray,
  readString,
  type PageCache,
} from "./pageUtils";

type PipelinePageProps = {
  cache: PageCache;
  organizationId: number | null;
  service: PipelineService;
};

type PageStatus = "loading" | "empty" | "error" | "forbidden" | "success";

type PipelineTaskView = {
  description: string;
  id: string;
  outputId: string | null;
  status: string;
  title: string;
};

type PipelineDecisionView = {
  id: string;
  status: string;
  summary: string;
  title: string;
};

type PipelineOutputView = {
  id: string;
  markdown: string;
  sources: Array<{
    publishedAt: string;
    searchedAt: string;
    title: string;
    url: string;
  }>;
  title: string;
};

const TERMINAL_RUN_STATUSES = new Set(["completed", "failed", "cancelled", "missed"]);

function scheduleTime(schedule: string | null | undefined): string {
  const [minute, hour] = schedule?.split(" ") ?? [];
  if (!minute || !hour) return "立即运行";
  return `${hour.padStart(2, "0")}:${minute.padStart(2, "0")}`;
}

async function waitForRun(service: PipelineService, runId: number | string) {
  let run = await service.getRun(runId);
  for (let attempt = 0; attempt < 20 && !TERMINAL_RUN_STATUSES.has(String(run.status)); attempt += 1) {
    await new Promise((resolve) => window.setTimeout(resolve, 1_000));
    run = await service.getRun(runId);
  }
  return run;
}

function readId(value: unknown, fallback: string): string {
  return typeof value === "number" || typeof value === "string"
    ? String(value)
    : fallback;
}

function mapTask(value: PipelineTask | unknown, index: number): PipelineTaskView {
  const item = asObject(value);
  const id = readId(item.id, `task-${index + 1}`);
  return {
    description: readString(item.description, ""),
    id,
    outputId: readId(item.output_id ?? item.outputId, ""),
    status: readString(item.status, "draft"),
    title: readString(item.title, `任务 ${index + 1}`),
  };
}

function mapDecision(
  value: PipelineDecision | unknown,
  index: number,
): PipelineDecisionView {
  const item = asObject(value);
  return {
    id: readId(item.id, `decision-${index + 1}`),
    status: readString(item.status, "pending"),
    summary: readString(item.summary, ""),
    title: readString(item.title, `审批 ${index + 1}`),
  };
}

function mapOutput(value: PipelineOutput | unknown): PipelineOutputView | null {
  const item = asObject(value);
  const id = readId(item.id, "");
  if (!id) return null;
  return {
    id,
    markdown: readString(item.markdown, ""),
    sources: readArray(item.sources).flatMap((source) => {
      const record = asObject(source);
      const url = readString(record.url, "");
      if (!url || !/^https?:\/\//i.test(url)) return [];
      return [{
        publishedAt: readString(record.published_at, "未提供"),
        searchedAt: readString(record.searched_at, "未提供"),
        title: readString(record.title, url),
        url,
      }];
    }),
    title: readString(item.title, "Markdown 预览"),
  };
}

function renderPipelineMarkdown(output: PipelineOutputView): string {
  const firstHeading = output.markdown.match(/^\s*#{1,6}\s+([^\n]+)\s*(?:\n|$)/);
  const content =
    firstHeading && firstHeading[1].trim() === output.title.trim()
      ? output.markdown.slice(firstHeading[0].length)
      : output.markdown;
  return renderSafeAssistantMarkdown(content);
}

function outputIdFrom(value: unknown): string | null {
  const item = asObject(value);
  const id = readId(item.output_id ?? item.outputId, "");
  return id || null;
}

function messageForError(error: unknown) {
  return errorStatus(error) === 403
    ? "没有 Pipeline 访问权限"
    : "Pipeline 加载失败";
}

export function PipelinePage({
  cache,
  organizationId,
  service,
}: PipelinePageProps) {
  const [approvalOpen, setApprovalOpen] = useState(false);
  const [actionPending, setActionPending] = useState<string | null>(null);
  const [changeReason, setChangeReason] = useState("");
  const [composerPending, setComposerPending] = useState(false);
  const [decisions, setDecisions] = useState<PipelineDecisionView[]>([]);
  const [draft, setDraft] = useState<PipelineTaskDraft | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [output, setOutput] = useState<PipelineOutputView | null>(null);
  const [prompt, setPrompt] = useState("");
  const [runNotice, setRunNotice] = useState<string | null>(null);
  const [runPending, setRunPending] = useState(false);
  const [selectedTask, setSelectedTask] = useState<PipelineTaskView | null>(null);
  const [status, setStatus] = useState<PageStatus>(
    organizationId === null ? "forbidden" : "loading",
  );
  const [tasks, setTasks] = useState<PipelineTaskView[]>([]);
  const cacheKey = useMemo(() => ["pipeline", "tasks"], []);

  const loadOutput = useCallback(
    async (outputId: string | null) => {
      if (!outputId) {
        setOutput(null);
        return;
      }
      setOutput(mapOutput(await service.getOutput(outputId)));
    },
    [service],
  );

  const loadPipeline = useCallback(async () => {
    if (organizationId === null) {
      setStatus("forbidden");
      setErrorMessage("没有 Pipeline 访问权限");
      setTasks([]);
      setSelectedTask(null);
      setDecisions([]);
      setOutput(null);
      return;
    }

    setErrorMessage(null);
    setStatus("loading");
    try {
      const cached = cache.get<PipelineTaskView[]>(organizationId, cacheKey);
      const tasksPromise = cached
        ? Promise.resolve(cached)
        : service
            .listTasks({ limit: 20 })
            .then((result) => readArray(result.items).map(mapTask));
      const [nextTasks, decisionResponse] = await Promise.all([
        tasksPromise,
        service.listDecisions(),
      ]);
      if (!cached) cache.set(organizationId, cacheKey, nextTasks);

      const nextSelected =
        nextTasks.length > 0
          ? mapTask(await service.getTask(nextTasks[0].id), 0)
          : null;
      const nextDecisions = readArray(decisionResponse.items).map(mapDecision);

      setTasks(nextTasks);
      setSelectedTask(nextSelected);
      setDecisions(nextDecisions);
      await loadOutput(nextSelected?.outputId ?? null);
      setStatus(nextTasks.length || nextDecisions.length ? "success" : "empty");
    } catch (error) {
      setStatus(errorStatus(error) === 403 ? "forbidden" : "error");
      setErrorMessage(messageForError(error));
      setSelectedTask(null);
      setOutput(null);
    }
  }, [cache, cacheKey, loadOutput, organizationId, service]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadPipeline();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [loadPipeline]);

  async function refreshPipeline() {
    if (organizationId === null) return;
    cache.invalidateOrganization(organizationId);
    await loadPipeline();
  }

  async function selectTask(task: PipelineTaskView) {
    setErrorMessage(null);
    try {
      const next = mapTask(await service.getTask(task.id), 0);
      setSelectedTask(next);
      await loadOutput(next.outputId);
    } catch (error) {
      setErrorMessage(messageForError(error));
    }
  }

  async function runSelectedTask() {
    if (!selectedTask) return;
    setErrorMessage(null);
    setRunPending(true);
    setRunNotice(null);
    try {
      const run = await service.runTask(selectedTask.id);
      const finishedRun = await waitForRun(service, run.id);
      // The intent finished; the next manual run is a new intent with a fresh
      // idempotency key, while retries of this intent already reused one key.
      service.releaseRunIntent(String(selectedTask.id));
      if (!TERMINAL_RUN_STATUSES.has(String(finishedRun.status))) {
        // A 202 that has not reached a terminal state stays honestly
        // in-progress; queued/running must never display as completed.
        setRunNotice(
          `任务仍在执行中（状态：${String(finishedRun.status)}）；运行已提交，稍后刷新查看结果。`,
        );
      } else {
        setRunNotice(null);
      }
      await loadOutput(outputIdFrom(finishedRun) ?? outputIdFrom(run));
    } catch (error) {
      setErrorMessage(messageForError(error));
    } finally {
      setRunPending(false);
    }
  }

  async function generateDraft() {
    const description = prompt.trim();
    if (!description) return;
    setComposerPending(true);
    setErrorMessage(null);
    try {
      setDraft(await service.createDraft({ prompt: description }));
    } catch (error) {
      setErrorMessage(messageForError(error));
    } finally {
      setComposerPending(false);
    }
  }

  async function confirmDraft() {
    if (!draft || organizationId === null) return;
    setComposerPending(true);
    setErrorMessage(null);
    try {
      await service.createTask({ ...draft, confirmed: true });
      setDraft(null);
      setPrompt("");
      cache.invalidateOrganization(organizationId);
      await loadPipeline();
    } catch (error) {
      setErrorMessage(messageForError(error));
    } finally {
      setComposerPending(false);
    }
  }

  async function approveDecision(decision: PipelineDecisionView) {
    setActionPending(decision.id);
    setErrorMessage(null);
    try {
      await service.approveDecision(decision.id);
      await refreshPipeline();
    } catch (error) {
      setErrorMessage(messageForError(error));
    } finally {
      setActionPending(null);
    }
  }

  async function requestChanges(decision: PipelineDecisionView) {
    const reason = changeReason.trim();
    if (!reason) return;
    setActionPending(decision.id);
    setErrorMessage(null);
    try {
      await service.requestChanges(decision.id, { reason });
      setChangeReason("");
      await refreshPipeline();
    } catch (error) {
      setErrorMessage(messageForError(error));
    } finally {
      setActionPending(null);
    }
  }

  async function downloadOutput() {
    if (!output) return;
    const blob = await service.downloadOutput(output.id);
    if (
      typeof navigator !== "undefined" &&
      navigator.userAgent.toLowerCase().includes("jsdom")
    ) {
      return;
    }
    if (
      typeof document === "undefined" ||
      typeof URL === "undefined" ||
      !("createObjectURL" in URL)
    ) {
      return;
    }
    const href = URL.createObjectURL(blob as Blob);
    const link = document.createElement("a");
    link.href = href;
    link.download = `${output.title || "pipeline-output"}.md`;
    link.click();
    URL.revokeObjectURL(href);
  }

  const canUsePipeline = organizationId !== null && status !== "forbidden";

  return (
    <main aria-labelledby="pipeline-title" className="page-view pipeline-page">
      <header className="page-header">
        <div>
          <h1 id="pipeline-title">Pipeline</h1>
          <p>任务列表、执行详情、审批处理和 Markdown 产物。</p>
        </div>
        <button
          disabled={!canUsePipeline}
          onClick={() => void refreshPipeline()}
          type="button"
        >
          刷新 Pipeline
        </button>
      </header>

      {errorMessage ? (
        <p className="error-message" role="alert">
          {errorMessage}
        </p>
      ) : null}
      {status === "loading" ? <p>正在加载 Pipeline</p> : null}
      {status === "empty" ? <p>暂无 Pipeline 任务</p> : null}

      <section aria-label="AI 创建任务" className="pipeline-task-composer">
        <div className="pipeline-composer-input">
          <label htmlFor="pipeline-task-prompt">任务描述</label>
          <textarea
            disabled={!canUsePipeline || composerPending}
            id="pipeline-task-prompt"
            onChange={(event) => setPrompt(event.target.value)}
            value={prompt}
          />
          <button
            disabled={!canUsePipeline || composerPending || !prompt.trim()}
            onClick={() => void generateDraft()}
            type="button"
          >
            生成任务草稿
          </button>
        </div>
        {draft ? (
          <div aria-label="任务确认" className="pipeline-draft-confirmation">
            <h2>{draft.title || "任务草稿"}</h2>
            <dl>
              <div><dt>时间</dt><dd>{scheduleTime(draft.schedule)}</dd></div>
              <div><dt>时区</dt><dd>{draft.timezone || "-"}</dd></div>
              <div><dt>来源</dt><dd>{draft.input_sources?.join(", ") || "-"}</dd></div>
              <div><dt>格式</dt><dd>{draft.output_format || "-"}</dd></div>
            </dl>
            <div className="pipeline-draft-actions">
              <button
                disabled={composerPending}
                onClick={() => void confirmDraft()}
                type="button"
              >
                确认创建任务
              </button>
              <button disabled={composerPending} onClick={() => setDraft(null)} type="button">
                取消
              </button>
            </div>
          </div>
        ) : null}
      </section>

      <section aria-label="Pipeline 工作台" className="pipeline-shell">
        <aside aria-label="任务列表" className="pipeline-list">
          <h2>任务列表</h2>
          {tasks.length ? (
            <ul>
              {tasks.map((task) => (
                <li key={task.id}>
                  <button
                    aria-pressed={selectedTask?.id === task.id}
                    onClick={() => void selectTask(task)}
                    type="button"
                  >
                    {task.title}
                  </button>
                  <span>{task.status}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p>暂无任务</p>
          )}
        </aside>

        <section aria-label="任务详情" className="pipeline-detail">
          <div className="section-header">
            <h2>任务详情</h2>
            <button
              disabled={!selectedTask || runPending}
              onClick={() => void runSelectedTask()}
              type="button"
            >
              运行任务
            </button>
          </div>
          {selectedTask ? (
            <article>
              <h3>{selectedTask.title}</h3>
              <p>{selectedTask.description || "暂无任务描述"}</p>
              <dl>
                <div>
                  <dt>状态</dt>
                  <dd>{selectedTask.status}</dd>
                </div>
                <div>
                  <dt>产物</dt>
                  <dd>{selectedTask.outputId ?? "未生成"}</dd>
                </div>
              </dl>
              {runNotice ? (
                <p
                  className="pipeline-run-notice"
                  data-testid="pipeline-run-notice"
                  role="status"
                >
                  {runNotice}
                </p>
              ) : null}
            </article>
          ) : (
            <p>请选择任务</p>
          )}
        </section>

        <section aria-label="Markdown 预览" className="pipeline-output">
          <div className="section-header">
            <h2>{output?.title ?? "Markdown 预览"}</h2>
            <button
              disabled={!output}
              onClick={() => void downloadOutput()}
              type="button"
            >
              下载 Markdown
            </button>
          </div>
          {output ? (
            <>
              <div
                className="markdown-preview"
                dangerouslySetInnerHTML={{
                  __html: renderPipelineMarkdown(output),
                }}
              />
              {output.sources.length ? (
                <section aria-label="联网来源" className="pipeline-sources">
                  <h3>联网来源</h3>
                  <ul>
                    {output.sources.map((source) => (
                      <li key={source.url}>
                        <a href={source.url} target="_blank" rel="noreferrer noopener">{source.title}</a>
                        <span>检索：{source.searchedAt}；发布：{source.publishedAt}</span>
                      </li>
                    ))}
                  </ul>
                </section>
              ) : (
                <p className="pipeline-sources-empty">未提供联网来源；该产物不能作为“最新动态”的实时证据。</p>
              )}
            </>
          ) : (
            <p>暂无 Markdown 产物</p>
          )}
        </section>
      </section>

      <section aria-label="审批摘要" className="pipeline-decisions">
        <div className="section-header">
          <h2>审批抽屉</h2>
          <button onClick={() => setApprovalOpen(true)} type="button">
            查看审批
          </button>
        </div>
        <p>待处理 {decisions.filter((item) => item.status === "pending").length}</p>
        {decisions.length ? (
          <ul>
            {decisions.slice(0, 3).map((decision) => (
              <li key={decision.id}>{decision.title}</li>
            ))}
          </ul>
        ) : (
          <p>暂无审批</p>
        )}
      </section>

      {approvalOpen ? (
        <div aria-label="审批抽屉" className="pipeline-drawer" role="dialog">
          <div className="section-header">
            <h2>审批抽屉</h2>
            <button onClick={() => setApprovalOpen(false)} type="button">
              关闭
            </button>
          </div>
          <label>
            修改说明
            <textarea
              onChange={(event) => setChangeReason(event.target.value)}
              value={changeReason}
            />
          </label>
          {decisions.length ? (
            <ul>
              {decisions.map((decision) => (
                <li key={decision.id}>
                  <strong>{decision.title}</strong>
                  <span>{decision.status}</span>
                  {decision.summary ? <p>{decision.summary}</p> : null}
                  <button
                    disabled={actionPending === decision.id}
                    onClick={() => void approveDecision(decision)}
                    type="button"
                  >
                    批准 {decision.title}
                  </button>
                  <button
                    disabled={!changeReason.trim() || actionPending === decision.id}
                    onClick={() => void requestChanges(decision)}
                    type="button"
                  >
                    要求修改 {decision.title}
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p>暂无审批</p>
          )}
        </div>
      ) : null}
    </main>
  );
}
