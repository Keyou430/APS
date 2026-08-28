import type { PipelineTaskRequest } from "../api/services/pipelineService";
import { readArray, readString } from "../pages/pageUtils";

type PipelineDraftEditorProps = {
  disabled?: boolean;
  draft: PipelineTaskRequest;
  onChange: (patch: PipelineTaskRequest) => void;
};

export function PipelineDraftEditor({ disabled = false, draft, onChange }: PipelineDraftEditorProps) {
  const approvalRequired = draft.approval_required !== false;
  const assigneeType = readString(draft.approval_assignee_type, "creator");
  const numberValue = (value: unknown) => typeof value === "number" ? value : "";

  return <div className="pipeline-draft-fields">
    <label><span>任务标题</span><input disabled={disabled} onChange={(event) => onChange({ title: event.currentTarget.value })} value={readString(draft.title)} /></label>
    <label><span>任务内容</span><textarea disabled={disabled} onChange={(event) => onChange({ prompt: event.currentTarget.value })} value={readString(draft.prompt)} /></label>
    <label><span>执行周期</span><input disabled={disabled} onChange={(event) => onChange({ schedule: event.currentTarget.value || null })} value={readString(draft.schedule)} /></label>
    <label><span>时区</span><input disabled value="Asia/Shanghai" /></label>
    <label><span>输出格式</span><select disabled value={readString(draft.output_format, "markdown")}><option value="markdown">Markdown</option></select></label>
    <label><span>输入来源</span><input disabled value={readArray(draft.input_sources).join(", ")} /></label>
    <label><input checked={approvalRequired} disabled={disabled} onChange={(event) => onChange({ approval_required: event.currentTarget.checked })} type="checkbox" />需要审批</label>
    {approvalRequired ? <div className="pipeline-draft-approval-fields">
      <label><span>审批人</span><select disabled={disabled} onChange={(event) => onChange({ approval_assignee_type: event.currentTarget.value })} value={assigneeType}><option value="creator">创建者</option><option value="member">指定成员</option><option value="role">指定角色</option></select></label>
      {assigneeType === "member" ? <label><span>成员 ID</span><input disabled={disabled} min="1" onChange={(event) => onChange({ approval_assignee_id: event.currentTarget.value ? Number(event.currentTarget.value) : null })} type="number" value={numberValue(draft.approval_assignee_id)} /></label> : null}
      {assigneeType === "role" ? <label><span>审批角色</span><input disabled={disabled} onChange={(event) => onChange({ approval_role_name: event.currentTarget.value || null })} value={readString(draft.approval_role_name)} /></label> : null}
      <label><span>提醒分钟</span><input disabled={disabled} min="1" onChange={(event) => onChange({ approval_reminder_after_minutes: event.currentTarget.value ? Number(event.currentTarget.value) : null })} type="number" value={numberValue(draft.approval_reminder_after_minutes)} /></label>
      <label><span>升级分钟</span><input disabled={disabled} min="1" onChange={(event) => onChange({ approval_escalation_after_minutes: event.currentTarget.value ? Number(event.currentTarget.value) : null })} type="number" value={numberValue(draft.approval_escalation_after_minutes)} /></label>
      <label><span>升级角色</span><input disabled={disabled} onChange={(event) => onChange({ approval_escalation_role_name: event.currentTarget.value || null })} value={readString(draft.approval_escalation_role_name)} /></label>
    </div> : null}
  </div>;
}
