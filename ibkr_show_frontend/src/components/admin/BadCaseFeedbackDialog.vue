<script setup lang="ts">
import { ref, watch } from 'vue'
import Button from 'primevue/button'
import InputText from 'primevue/inputtext'
import HarnessDetailDialog from './HarnessDetailDialog.vue'
import type { BadCaseFeedbackCreatePayload } from '@/types/adminHarness'

const props = defineProps<{
  visible: boolean
  initial?: Partial<BadCaseFeedbackCreatePayload>
  loading?: boolean
}>()

const emit = defineEmits<{
  'update:visible': [visible: boolean]
  save: [payload: BadCaseFeedbackCreatePayload]
}>()

const title = ref('')
const description = ref('')
const issueType = ref('other')
const severity = ref('medium')
const category = ref('')
const tags = ref('')
const notes = ref('')

watch(() => props.visible, (v) => {
  if (v) resetForm()
})

function closeDialog(visible: boolean): void {
  emit('update:visible', visible)
}

function resetForm(): void {
  title.value = props.initial?.title || ''
  description.value = props.initial?.description || ''
  issueType.value = props.initial?.issue_type || 'other'
  severity.value = props.initial?.severity || 'medium'
  category.value = props.initial?.category || ''
  tags.value = (props.initial?.tags || []).join(', ')
  notes.value = props.initial?.notes || ''
}

function handleSave(): void {
  if (!title.value.trim()) return
  const payload: BadCaseFeedbackCreatePayload = {
    source_type: props.initial?.source_type || 'manual',
    source_id: props.initial?.source_id || 'manual',
    title: title.value.trim(),
    agent_name: props.initial?.agent_name || '',
    description: description.value.trim(),
    issue_type: issueType.value,
    severity: severity.value,
    category: category.value.trim(),
    tags: tags.value.split(/[,\n]/).map(t => t.trim()).filter(Boolean),
    notes: notes.value.trim(),
    replay_id: props.initial?.replay_id,
    run_id: props.initial?.run_id,
    eval_run_id: props.initial?.eval_run_id,
    case_id: props.initial?.case_id,
    result_case_id: props.initial?.result_case_id,
    evidence: props.initial?.evidence || {},
    metadata: props.initial?.metadata || {},
  }
  emit('save', payload)
}
</script>

<template>
  <HarnessDetailDialog :visible="visible" header="标记 Bad Case" @update:visible="closeDialog">
    <template #default>
      <div class="feedback-form">
        <div class="feedback-form__field">
          <label>标题 *</label>
          <InputText v-model="title" placeholder="简要描述问题" />
        </div>
        <div class="feedback-form__field">
          <label>问题描述</label>
          <textarea v-model="description" rows="3" placeholder="详细描述发现的问题"></textarea>
        </div>
        <div class="feedback-form__row">
          <div class="feedback-form__field">
            <label>问题类型</label>
            <select v-model="issueType">
              <option value="wrong_answer">wrong_answer</option>
              <option value="missing_risk">missing_risk</option>
              <option value="overconfident">overconfident</option>
              <option value="tool_error">tool_error</option>
              <option value="format_error">format_error</option>
              <option value="hallucination">hallucination</option>
              <option value="bad_reasoning">bad_reasoning</option>
              <option value="unsafe_investment_advice">unsafe_investment_advice</option>
              <option value="other">other</option>
            </select>
          </div>
          <div class="feedback-form__field">
            <label>严重等级</label>
            <select v-model="severity">
              <option value="low">low</option>
              <option value="medium">medium</option>
              <option value="high">high</option>
              <option value="critical">critical</option>
            </select>
          </div>
        </div>
        <div class="feedback-form__row">
          <div class="feedback-form__field">
            <label>分类</label>
            <select v-model="category">
              <option value="">无</option>
              <option value="safety">safety</option>
              <option value="format">format</option>
              <option value="grounding">grounding</option>
              <option value="tool_use">tool_use</option>
              <option value="investment_risk">investment_risk</option>
              <option value="regression">regression</option>
            </select>
          </div>
          <div class="feedback-form__field">
            <label>标签（逗号分隔）</label>
            <InputText v-model="tags" placeholder="bad_case, risk" />
          </div>
        </div>
        <div class="feedback-form__field">
          <label>备注</label>
          <textarea v-model="notes" rows="2" placeholder="其他备注信息"></textarea>
        </div>
        <div class="feedback-form__actions">
          <Button label="提交反馈" icon="pi pi-check" class="p-button--accent" :loading="loading" :disabled="loading || !title.trim()" @click="handleSave" />
          <Button label="取消" severity="secondary" @click="closeDialog(false)" />
        </div>
      </div>
    </template>
  </HarnessDetailDialog>
</template>

<style scoped>
.feedback-form {
  display: grid;
  gap: var(--space-4);
}

.feedback-form__field {
  display: grid;
  gap: 4px;
}

.feedback-form__field label {
  font-size: 0.84rem;
  color: var(--color-text-secondary);
}

.feedback-form__field select,
.feedback-form__field textarea,
.feedback-form__field :deep(input) {
  min-height: 38px;
  border: 1px solid rgba(129, 160, 207, 0.18);
  border-radius: var(--radius-sm);
  background: rgba(10, 18, 32, 0.72);
  color: var(--color-text-primary);
  padding: 8px 10px;
  font-size: 0.84rem;
}

.feedback-form__row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-4);
}

.feedback-form__actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}
</style>
