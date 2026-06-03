<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import Button from 'primevue/button'
import Dialog from 'primevue/dialog'
import InputText from 'primevue/inputtext'
import type { EvalCase } from '@/types/adminHarness'

const props = defineProps<{
  visible: boolean
  initialCase?: Partial<EvalCase> | null
  mode: 'create' | 'edit'
  saving?: boolean
}>()

const emit = defineEmits<{
  'update:visible': [value: boolean]
  save: [payload: Record<string, unknown>]
}>()

const errors = ref<string[]>([])

const SEVERITY_OPTIONS = ['low', 'medium', 'high', 'critical']
const CATEGORY_OPTIONS = ['', 'safety', 'format', 'grounding', 'tool_use', 'investment_risk', 'regression']

const form = reactive({
  title: '',
  agent_name: '',
  description: '',
  enabled: true,
  severity: 'medium',
  category: '',
  tags: '',
  notes: '',
  expected_output_fields: '',
  expected_tools: '',
  expected_data_limitations: '',
  forbidden_behavior: '',
  expected_behavior: '{}',
  scoring_rubric: '{}',
  input: '{}',
  mock_context: '{}',
  mock_tool_outputs: '{}',
  metadata: '{}',
  judge_enabled: false,
  judge_rubric: '{}',
  judge_model_config: '{}',
  eval_scope: 'agent',
  node_name: '',
  source_run_id: '',
  source_llm_call_id: '',
  source_node_trace_id: '',
  prompt_key: '',
  prompt_version: '',
  prompt_hash: '',
  model: '',
})

const collapsedSections = reactive({
  input: true,
  mock: true,
  metadata: true,
  judge: true,
})

watch(() => props.visible, (vis) => {
  if (vis) {
    errors.value = []
    populateForm()
  }
})

function populateForm(): void {
  const c = props.initialCase
  if (!c) return
  form.title = c.title ?? ''
  form.agent_name = c.agent_name ?? ''
  form.description = c.description ?? ''
  form.enabled = c.enabled ?? true
  form.severity = c.severity ?? 'medium'
  form.category = c.category ?? ''
  form.tags = (c.tags ?? []).join(', ')
  form.notes = c.notes ?? ''
  form.expected_output_fields = (c.expected_output_fields ?? []).join('\n')
  form.expected_tools = (c.expected_tools ?? []).join('\n')
  form.expected_data_limitations = (c.expected_data_limitations ?? []).join('\n')
  form.forbidden_behavior = (c.forbidden_behavior ?? []).join('\n')
  form.expected_behavior = safeJson(c.expected_behavior)
  form.scoring_rubric = safeJson(c.scoring_rubric)
  form.input = safeJson(c.input)
  form.mock_context = safeJson(c.mock_context)
  form.mock_tool_outputs = safeJson(c.mock_tool_outputs)
  form.metadata = safeJson(c.metadata)
  form.judge_enabled = c.judge_enabled ?? false
  form.judge_rubric = safeJson(c.judge_rubric)
  form.judge_model_config = safeJson(c.judge_model_config)
  form.eval_scope = c.eval_scope ?? 'agent'
  form.node_name = c.node_name ?? ''
  form.source_run_id = c.source_run_id ?? ''
  form.source_llm_call_id = c.source_llm_call_id ?? ''
  form.source_node_trace_id = c.source_node_trace_id ?? ''
  form.prompt_key = c.prompt_key ?? ''
  form.prompt_version = c.prompt_version ?? ''
  form.prompt_hash = c.prompt_hash ?? ''
  form.model = c.model ?? ''
}

function safeJson(value: unknown): string {
  if (value === undefined || value === null) return '{}'
  try { return JSON.stringify(value, null, 2) } catch { return '{}' }
}

function textToArray(text: string, mode: 'line' | 'commaOrLine' = 'line'): string[] {
  const separator = mode === 'commaOrLine' ? /[\n,]/ : '\n'
  const parts = text.split(separator).map((s) => s.trim()).filter(Boolean)
  return [...new Set(parts)]
}

function parseJsonStrict(text: string, label: string): Record<string, unknown> | null {
  try {
    const parsed = JSON.parse(text)
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
      errors.value.push(`${label} 必须是 JSON 对象`)
      return null
    }
    return parsed
  } catch {
    errors.value.push(`${label} JSON 格式不合法`)
    return null
  }
}

function buildPayload(): Record<string, unknown> | null {
  errors.value = []
  if (!form.title.trim()) errors.value.push('标题不能为空')
  if (!form.agent_name.trim()) errors.value.push('Agent name 不能为空')

  const evalScope = form.eval_scope.trim() || 'agent'
  if (evalScope !== 'agent' && evalScope !== 'node') {
    errors.value.push('eval_scope 只能是 agent 或 node')
  }
  if (evalScope === 'node' && !form.node_name.trim()) {
    errors.value.push('eval_scope=node 时 node_name 必填')
  }

  const expectedBehavior = parseJsonStrict(form.expected_behavior, 'expected_behavior')
  const scoringRubric = parseJsonStrict(form.scoring_rubric, 'scoring_rubric')
  const inputObj = parseJsonStrict(form.input, 'input')
  const mockContext = parseJsonStrict(form.mock_context, 'mock_context')
  const mockToolOutputs = parseJsonStrict(form.mock_tool_outputs, 'mock_tool_outputs')
  const metadata = parseJsonStrict(form.metadata, 'metadata')
  const judgeRubric = form.judge_enabled ? parseJsonStrict(form.judge_rubric, 'judge_rubric') : null
  const judgeModelConfig = form.judge_enabled ? parseJsonStrict(form.judge_model_config, 'judge_model_config') : null

  if (errors.value.length) return null

  const payload: Record<string, unknown> = {
    title: form.title.trim(),
    agent_name: form.agent_name.trim(),
    description: form.description.trim(),
    enabled: form.enabled,
    severity: form.severity,
    category: form.category,
    tags: textToArray(form.tags, 'commaOrLine'),
    notes: form.notes.trim(),
    expected_output_fields: textToArray(form.expected_output_fields),
    expected_tools: textToArray(form.expected_tools),
    expected_data_limitations: textToArray(form.expected_data_limitations),
    forbidden_behavior: textToArray(form.forbidden_behavior),
    expected_behavior: expectedBehavior,
    scoring_rubric: scoringRubric,
    input: inputObj,
    mock_context: mockContext,
    mock_tool_outputs: mockToolOutputs,
    metadata: metadata,
    judge_enabled: form.judge_enabled,
    judge_rubric: judgeRubric || {},
    judge_model_config: judgeModelConfig || {},
    eval_scope: evalScope,
    node_name: form.node_name.trim() || null,
    source_run_id: form.source_run_id.trim() || null,
    source_llm_call_id: form.source_llm_call_id.trim() || null,
    source_node_trace_id: form.source_node_trace_id.trim() || null,
    prompt_key: form.prompt_key.trim() || null,
    prompt_version: form.prompt_version.trim() || null,
    prompt_hash: form.prompt_hash.trim() || null,
    model: form.model.trim() || null,
  }

  if (props.mode === 'create' && props.initialCase) {
    const draft = props.initialCase
    if (draft.case_id) payload.case_id = draft.case_id
    if (draft.source) payload.source = draft.source
    if (draft.source_replay_id) payload.source_replay_id = draft.source_replay_id
    if (draft.created_at) payload.created_at = draft.created_at
    if (draft.updated_at) payload.updated_at = draft.updated_at
    if (draft.version) payload.version = draft.version
    if (draft.metadata && metadata) {
      payload.metadata = { ...draft.metadata, ...metadata }
    }
  }

  return payload
}

function handleSave(): void {
  const payload = buildPayload()
  if (!payload) return
  emit('save', payload)
}

function close(): void {
  emit('update:visible', false)
}

</script>

<template>
  <Dialog
    :visible="visible"
    modal
    :header="mode === 'create' ? '创建 Eval Case' : '编辑 Eval Case'"
    class="harness-detail-dialog eval-case-editor-dialog"
    :style="{ width: 'min(900px, 92vw)', maxHeight: '90vh' }"
    :content-style="{ padding: 0, display: 'flex', flexDirection: 'column', maxHeight: 'calc(90vh - 64px)', overflow: 'hidden' }"
    @update:visible="emit('update:visible', $event)"
  >
    <div class="eval-case-editor__body">
      <p v-if="errors.length" class="eval-case-editor__errors">
        <span v-for="(err, i) in errors" :key="i">{{ err }}</span>
      </p>

      <fieldset class="eval-case-editor__section">
        <legend>基础信息</legend>
        <div class="eval-case-editor__grid">
          <label class="eval-case-editor__field">
            <span>标题 *</span>
            <InputText v-model="form.title" />
          </label>
          <label class="eval-case-editor__field">
            <span>Agent *</span>
            <InputText v-model="form.agent_name" :disabled="mode === 'edit'" />
          </label>
          <label class="eval-case-editor__field eval-case-editor__field--full">
            <span>描述</span>
            <InputText v-model="form.description" />
          </label>
          <label class="eval-case-editor__field">
            <span>启用</span>
            <select v-model="form.enabled">
              <option :value="true">启用</option>
              <option :value="false">禁用</option>
            </select>
          </label>
          <label class="eval-case-editor__field">
            <span>严重等级</span>
            <select v-model="form.severity">
              <option v-for="s in SEVERITY_OPTIONS" :key="s" :value="s">{{ s }}</option>
            </select>
          </label>
          <label class="eval-case-editor__field">
            <span>分类</span>
            <select v-model="form.category">
              <option v-for="c in CATEGORY_OPTIONS" :key="c" :value="c">{{ c || '(无)' }}</option>
            </select>
          </label>
          <label class="eval-case-editor__field eval-case-editor__field--full">
            <span>标签（逗号分隔）</span>
            <InputText v-model="form.tags" placeholder="replay, trade_review" />
          </label>
          <label class="eval-case-editor__field eval-case-editor__field--full">
            <span>人工备注</span>
            <InputText v-model="form.notes" />
          </label>
        </div>
      </fieldset>

      <fieldset class="eval-case-editor__section">
        <legend>评测规则</legend>
        <div class="eval-case-editor__grid">
          <label class="eval-case-editor__field">
            <span>Eval Scope</span>
            <select v-model="form.eval_scope">
              <option value="agent">agent</option>
              <option value="node">node</option>
            </select>
          </label>
          <label class="eval-case-editor__field">
            <span>Node Name{{ form.eval_scope === 'node' ? ' *' : '' }}</span>
            <InputText v-model="form.node_name" :placeholder="form.eval_scope === 'node' ? '必填，如 event_catalyst' : '（仅 node scope 必填）'" />
          </label>
          <label class="eval-case-editor__field">
            <span>Prompt Key</span>
            <InputText v-model="form.prompt_key" />
          </label>
          <label class="eval-case-editor__field">
            <span>Prompt Version</span>
            <InputText v-model="form.prompt_version" />
          </label>
          <label class="eval-case-editor__field">
            <span>Prompt Hash</span>
            <InputText v-model="form.prompt_hash" />
          </label>
          <label class="eval-case-editor__field">
            <span>Model</span>
            <InputText v-model="form.model" />
          </label>
          <label class="eval-case-editor__field">
            <span>Source Run ID</span>
            <InputText v-model="form.source_run_id" />
          </label>
          <label class="eval-case-editor__field">
            <span>Source LLM Call ID</span>
            <InputText v-model="form.source_llm_call_id" />
          </label>
          <label class="eval-case-editor__field eval-case-editor__field--full">
            <span>Source Node Trace ID</span>
            <InputText v-model="form.source_node_trace_id" />
          </label>
          <label class="eval-case-editor__field eval-case-editor__field--full">
            <span>expected_output_fields（一行一个）</span>
            <textarea v-model="form.expected_output_fields" rows="3" />
          </label>
          <label class="eval-case-editor__field eval-case-editor__field--full">
            <span>expected_tools（一行一个）</span>
            <textarea v-model="form.expected_tools" rows="3" />
          </label>
          <label class="eval-case-editor__field eval-case-editor__field--full">
            <span>expected_data_limitations（一行一个）</span>
            <textarea v-model="form.expected_data_limitations" rows="2" />
          </label>
          <label class="eval-case-editor__field eval-case-editor__field--full">
            <span>forbidden_behavior（一行一个）</span>
            <textarea v-model="form.forbidden_behavior" rows="3" />
          </label>
          <label class="eval-case-editor__field eval-case-editor__field--full">
            <span>expected_behavior（JSON）</span>
            <textarea v-model="form.expected_behavior" rows="4" class="eval-case-editor__json" />
          </label>
          <label class="eval-case-editor__field eval-case-editor__field--full">
            <span>scoring_rubric（JSON）</span>
            <textarea v-model="form.scoring_rubric" rows="3" class="eval-case-editor__json" />
          </label>
        </div>
      </fieldset>

      <fieldset class="eval-case-editor__section">
        <legend role="button" tabindex="0" @click="collapsedSections.input = !collapsedSections.input">
          输入 input {{ collapsedSections.input ? '▶' : '▼' }}
        </legend>
        <div v-show="!collapsedSections.input">
          <label class="eval-case-editor__field eval-case-editor__field--full">
            <textarea v-model="form.input" rows="6" class="eval-case-editor__json" />
          </label>
        </div>
      </fieldset>

      <fieldset class="eval-case-editor__section">
        <legend role="button" tabindex="0" @click="collapsedSections.mock = !collapsedSections.mock">
          Mock 数据 {{ collapsedSections.mock ? '▶' : '▼' }}
        </legend>
        <div v-show="!collapsedSections.mock">
          <label class="eval-case-editor__field eval-case-editor__field--full">
            <span>mock_context（JSON）</span>
            <textarea v-model="form.mock_context" rows="4" class="eval-case-editor__json" />
          </label>
          <label class="eval-case-editor__field eval-case-editor__field--full">
            <span>mock_tool_outputs（JSON）</span>
            <textarea v-model="form.mock_tool_outputs" rows="4" class="eval-case-editor__json" />
          </label>
        </div>
      </fieldset>

      <fieldset class="eval-case-editor__section">
        <legend role="button" tabindex="0" @click="collapsedSections.metadata = !collapsedSections.metadata">
          metadata {{ collapsedSections.metadata ? '▶' : '▼' }}
        </legend>
        <div v-show="!collapsedSections.metadata">
          <label class="eval-case-editor__field eval-case-editor__field--full">
            <textarea v-model="form.metadata" rows="4" class="eval-case-editor__json" />
          </label>
        </div>
      </fieldset>

      <fieldset class="eval-case-editor__section">
        <legend role="button" tabindex="0" @click="collapsedSections.judge = !collapsedSections.judge">
          LLM Judge 配置 {{ collapsedSections.judge ? '▶' : '▼' }}
        </legend>
        <div v-show="!collapsedSections.judge">
          <p class="eval-case-editor__hint">LLM Judge 会调用模型对输出质量进行裁判，可能产生额外 token 成本。建议只对关键 case 启用。</p>
          <div class="eval-case-editor__grid">
            <label class="eval-case-editor__field">
              <span>启用 LLM Judge</span>
              <select v-model="form.judge_enabled">
                <option :value="false">禁用</option>
                <option :value="true">启用</option>
              </select>
            </label>
          </div>
          <label v-if="form.judge_enabled" class="eval-case-editor__field eval-case-editor__field--full">
            <span>judge_rubric（JSON，留空使用默认）</span>
            <textarea v-model="form.judge_rubric" rows="4" class="eval-case-editor__json" />
          </label>
          <label v-if="form.judge_enabled" class="eval-case-editor__field eval-case-editor__field--full">
            <span>judge_model_config（JSON，可选）</span>
            <textarea v-model="form.judge_model_config" rows="3" class="eval-case-editor__json" />
          </label>
        </div>
      </fieldset>
    </div>

    <template #footer>
      <div class="eval-case-editor__footer">
        <Button label="取消" severity="secondary" @click="close" />
        <Button label="保存" icon="pi pi-check" class="p-button--accent" :loading="saving" @click="handleSave" />
      </div>
    </template>
  </Dialog>
</template>

<style scoped>
.eval-case-editor__body {
  flex: 1;
  overflow-y: auto;
  padding: 18px 20px;
  display: grid;
  gap: 14px;
  background: #07111f;
}

.eval-case-editor__errors {
  margin: 0;
  padding: 10px 14px;
  border-radius: var(--radius-sm);
  background: rgba(255, 107, 122, 0.12);
  color: var(--color-negative);
  display: grid;
  gap: 2px;
}

.eval-case-editor__section {
  border: 1px solid rgba(129, 160, 207, 0.14);
  border-radius: var(--radius-sm);
  padding: 14px;
  display: grid;
  gap: 10px;
}

.eval-case-editor__section legend {
  color: var(--color-text-primary);
  font-weight: 700;
  font-size: 0.92rem;
  cursor: pointer;
  padding: 0 6px;
}

.eval-case-editor__grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.eval-case-editor__field {
  display: grid;
  gap: 4px;
  font-size: 0.85rem;
  color: var(--color-text-secondary);
}

.eval-case-editor__field--full {
  grid-column: 1 / -1;
}

.eval-case-editor__field input,
.eval-case-editor__field select,
.eval-case-editor__field textarea {
  min-height: 36px;
  border: 1px solid rgba(129, 160, 207, 0.18);
  border-radius: var(--radius-sm);
  background: rgba(10, 18, 32, 0.72);
  color: var(--color-text-primary);
  padding: 6px 10px;
  font-family: inherit;
  font-size: 0.85rem;
  resize: vertical;
}

.eval-case-editor__field textarea {
  min-height: 60px;
}

.eval-case-editor__json {
  font-family: 'Menlo', 'Consolas', monospace;
  font-size: 0.8rem;
}

.eval-case-editor__hint {
  margin: 0;
  font-size: 0.8rem;
  color: var(--color-text-secondary);
  opacity: 0.8;
  padding: 6px 0;
}

.eval-case-editor__footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 12px 20px;
  border-top: 1px solid rgba(129, 160, 207, 0.2);
  background: #081827;
}
</style>
