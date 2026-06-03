<script setup lang="ts">
import { ref } from 'vue'
import Button from 'primevue/button'
import InputText from 'primevue/inputtext'
import HarnessDetailDialog from './HarnessDetailDialog.vue'

const props = defineProps<{
  visible: boolean
  caseCount: number
  loading?: boolean
}>()

const emit = defineEmits<{
  'update:visible': [visible: boolean]
  save: [payload: Record<string, unknown>]
}>()

const severity = ref('')
const category = ref('')
const tagsAdd = ref('')
const tagsRemove = ref('')
const notesAppend = ref('')

function closeDialog(visible: boolean): void {
  emit('update:visible', visible)
}

function resetForm(): void {
  severity.value = ''
  category.value = ''
  tagsAdd.value = ''
  tagsRemove.value = ''
  notesAppend.value = ''
}

function handleSave(): void {
  const updates: Record<string, unknown> = {}
  if (severity.value) updates.severity = severity.value
  if (category.value) updates.category = category.value
  if (tagsAdd.value.trim()) updates.tags_add = tagsAdd.value.split(/[,\n]/).map(t => t.trim()).filter(Boolean)
  if (tagsRemove.value.trim()) updates.tags_remove = tagsRemove.value.split(/[,\n]/).map(t => t.trim()).filter(Boolean)
  if (notesAppend.value.trim()) updates.notes_append = notesAppend.value.trim()
  if (Object.keys(updates).length === 0) return
  if (!window.confirm(`确认批量更新 ${props.caseCount} 个 Eval Case 吗？`)) return
  emit('save', updates)
  resetForm()
}
</script>

<template>
  <HarnessDetailDialog :visible="visible" header="批量编辑 Eval Case" @update:visible="closeDialog">
    <template #default>
      <div class="bulk-edit-form">
        <div class="bulk-edit-form__field">
          <label>severity（留空不修改）</label>
          <select v-model="severity">
            <option value="">不修改</option>
            <option value="low">low</option>
            <option value="medium">medium</option>
            <option value="high">high</option>
            <option value="critical">critical</option>
          </select>
        </div>
        <div class="bulk-edit-form__field">
          <label>category（留空不修改）</label>
          <InputText v-model="category" placeholder="不修改" />
        </div>
        <div class="bulk-edit-form__field">
          <label>tags_add（逗号或换行分隔）</label>
          <textarea v-model="tagsAdd" rows="2" placeholder="regression, smoke"></textarea>
        </div>
        <div class="bulk-edit-form__field">
          <label>tags_remove（逗号或换行分隔）</label>
          <textarea v-model="tagsRemove" rows="2" placeholder="draft"></textarea>
        </div>
        <div class="bulk-edit-form__field">
          <label>notes_append</label>
          <textarea v-model="notesAppend" rows="3" placeholder="追加到 notes 末尾"></textarea>
        </div>
        <div class="bulk-edit-form__actions">
          <Button label="保存" icon="pi pi-check" class="p-button--accent" :loading="loading" :disabled="loading" @click="handleSave" />
          <Button label="取消" severity="secondary" @click="closeDialog(false)" />
        </div>
      </div>
    </template>
  </HarnessDetailDialog>
</template>

<style scoped>
.bulk-edit-form {
  display: grid;
  gap: var(--space-4);
}

.bulk-edit-form__field {
  display: grid;
  gap: 4px;
}

.bulk-edit-form__field label {
  font-size: 0.84rem;
  color: var(--color-text-secondary);
}

.bulk-edit-form__field select,
.bulk-edit-form__field textarea,
.bulk-edit-form__field :deep(input) {
  min-height: 38px;
  border: 1px solid rgba(129, 160, 207, 0.18);
  border-radius: var(--radius-sm);
  background: rgba(10, 18, 32, 0.72);
  color: var(--color-text-primary);
  padding: 8px 10px;
  font-size: 0.84rem;
}

.bulk-edit-form__actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}
</style>
