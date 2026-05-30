<script setup lang="ts">
import { computed } from 'vue'

import type { CopilotMessage, CopilotRun } from '@/types/accountCopilot'
import CopilotApprovalCard from './CopilotApprovalCard.vue'
import CopilotMessageBubble from './CopilotMessageBubble.vue'

const props = defineProps<{
  messages: CopilotMessage[]
  runsById: Record<string, CopilotRun>
  selectedRunId?: string
  loading?: boolean
  approving?: boolean
}>()

const emit = defineEmits<{
  selectRun: [runId: string]
  approve: [run: CopilotRun, approved: boolean]
}>()

type MessageRenderItem = {
  type: 'message'
  key: string
  message: CopilotMessage
}

type ApprovalRenderItem = {
  type: 'approval'
  key: string
  run: CopilotRun
}

type RenderItem = MessageRenderItem | ApprovalRenderItem

function approvalKey(run: CopilotRun): string {
  const approval = run.pending_approval
  return [
    approval?.approval_id,
    approval?.plan_hash,
    approval?.skill_name,
    approval?.created_at,
    run.id,
  ].filter(Boolean).join(':')
}

function shouldRenderApproval(run?: CopilotRun): run is CopilotRun {
  return Boolean(run?.pending_approval && (run.status === 'awaiting_approval' || run.pending_approval.status))
}

const renderItems = computed<RenderItem[]>(() => {
  // Find the first assistant message index for each run
  const firstAssistantIndexByRun = new Map<string, number>()
  props.messages.forEach((message, index) => {
    if (message.run_id && message.role === 'assistant' && !firstAssistantIndexByRun.has(message.run_id)) {
      firstAssistantIndexByRun.set(message.run_id, index)
    }
  })

  // Fallback: if no assistant message, use the first message of the run
  const firstMessageIndexByRun = new Map<string, number>()
  props.messages.forEach((message, index) => {
    if (message.run_id && !firstMessageIndexByRun.has(message.run_id)) {
      firstMessageIndexByRun.set(message.run_id, index)
    }
  })

  const seenApprovalKeys = new Set<string>()
  const items: RenderItem[] = []
  props.messages.forEach((message, index) => {
    items.push({ type: 'message', key: `message:${message.id}`, message })

    const run = message.run_id ? props.runsById[message.run_id] : undefined
    if (!shouldRenderApproval(run)) return

    // Insert approval card after the first assistant message of this run
    const insertAfterIndex = firstAssistantIndexByRun.get(run.id) ?? firstMessageIndexByRun.get(run.id)
    if (insertAfterIndex !== index) return

    const key = approvalKey(run)
    if (seenApprovalKeys.has(key)) return
    seenApprovalKeys.add(key)
    items.push({ type: 'approval', key: `approval:${key}`, run })
  })
  return items
})
</script>

<template>
  <div class="message-list">
    <div v-if="loading" class="message-list__empty">正在加载会话消息...</div>
    <div v-else-if="messages.length === 0" class="message-list__empty">开始一段账户级多轮分析。</div>
    <template v-for="item in renderItems" :key="item.key">
      <CopilotMessageBubble
        v-if="item.type === 'message'"
        :message="item.message"
        :run="item.message.run_id ? runsById[item.message.run_id] : undefined"
        :selected="Boolean(item.message.run_id && selectedRunId === item.message.run_id)"
        @select-run="emit('selectRun', $event)"
      />
      <CopilotApprovalCard
        v-else
        :run="item.run"
        :approving="approving"
        @approve="(run, approved) => emit('approve', run, approved)"
      />
    </template>
  </div>
</template>

<style scoped>
.message-list {
  padding: 24px;
}

.message-list__empty {
  display: grid;
  min-height: 180px;
  place-items: center;
  color: #94a3b8;
  border: 1px dashed rgba(125, 211, 252, 0.2);
  border-radius: 16px;
  background: rgba(15, 23, 42, 0.42);
}
</style>
