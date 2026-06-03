<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import Dialog from 'primevue/dialog'

import { fetchPositionDetail, fetchPositions } from '@/api/positions'
import { useAccountOverviewData } from '@/composables/accountOverview'
import ErrorBlock from '@/components/ErrorBlock.vue'
import LoadingBlock from '@/components/LoadingBlock.vue'
import PieDistributionCard from '@/components/PieDistributionCard.vue'
import PositionSimpleDetail from '@/components/PositionSimpleDetail.vue'
import PositionTable from '@/components/PositionTable.vue'
import PositionTreemap from '@/components/PositionTreemap.vue'
import type { AccountOverview } from '@/types/account'
import type { PositionDetailResponse, PositionItem, PositionListResponse, PositionSummaryResponse } from '@/types/positions'

const { overview: sharedOverview, ensureLoaded: ensureOverviewLoaded } = useAccountOverviewData()
const reportDate = ref('')
const response = ref<PositionListResponse | null>(null)
const summary = ref<PositionSummaryResponse | null>(null)
const overview = ref<AccountOverview | null>(null)
const loading = ref(true)
const errorMessage = ref('')
const detailDialogVisible = ref(false)
const detailLoading = ref(false)
const detailErrorMessage = ref('')
const activePosition = ref<PositionItem | null>(null)
const activeDetail = ref<{
  key: string
  symbol: string
  description: string
  assetClass: string | null
  detail: PositionDetailResponse | null
} | null>(null)

function formatNumber(value: number | null, digits = 2): string {
  if (value === null) {
    return '--'
  }
  return new Intl.NumberFormat('zh-CN', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value)
}

async function loadPositions(): Promise<void> {
  loading.value = true
  errorMessage.value = ''

  try {
    const [listResponse] = await Promise.all([
      fetchPositions({
        report_date: reportDate.value,
        include_summary: true,
        sort_by: 'position_value',
        sort_order: 'desc',
        page: 1,
        page_size: 200,
      }),
      ensureOverviewLoaded(),
    ])
    summary.value = listResponse.summary
    response.value = listResponse
    overview.value = sharedOverview.value
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '加载持仓失败'
  } finally {
    loading.value = false
  }
}

async function initialize(): Promise<void> {
  await loadPositions()
}

function toneByNumber(value: number | null | undefined): 'positive' | 'negative' | 'neutral' {
  if (!value) {
    return 'neutral'
  }
  return value > 0 ? 'positive' : 'negative'
}

function classifyAssetBucket(item: PositionListResponse['items'][number]): '股票' | '固定收益' | '现金' | '其他' {
  const description = `${item.description ?? ''}`.toUpperCase()
  const symbol = `${item.symbol ?? ''}`.toUpperCase()

  if (
    description.includes('TREASURY') ||
    description.includes('BOND') ||
    description.includes('0-3 MONTH') ||
    symbol === 'SGOV'
  ) {
    return '固定收益'
  }

  if (item.asset_class === 'STK') {
    return '股票'
  }

  return '其他'
}

function classifyIndustry(item: PositionListResponse['items'][number]): string {
  const text = `${item.symbol ?? ''} ${item.description ?? ''}`.toUpperCase()

  if (
    text.includes('AMD') ||
    text.includes('ARM') ||
    text.includes('INTEL') ||
    text.includes('QUALCOMM') ||
    text.includes('SEMI')
  ) {
    return '半导体'
  }
  if (
    text.includes('MICROSOFT') ||
    text.includes('META') ||
    text.includes('INTERACTIVE BROKERS') ||
    text.includes('STRATEGY') ||
    text.includes('SOFTWARE')
  ) {
    return '软件平台'
  }
  if (text.includes('AMAZON')) {
    return '电商消费'
  }
  if (text.includes('TESLA')) {
    return '汽车出行'
  }
  if (text.includes('XIAOMI')) {
    return '消费电子'
  }

  return '其他'
}

function uniqueMembers(values: Array<string | null | undefined>): string[] {
  return Array.from(
    new Set(
      values
        .map((value) => `${value ?? ''}`.trim())
        .filter((value) => value.length > 0),
    ),
  )
}

function industryDescription(label: string): string {
  const mapping: Record<string, string> = {
    半导体: '芯片 / 处理器 / 通信',
    软件平台: '平台软件 / 社交 / 券商科技',
    电商消费: '线上零售 / 云服务',
    汽车出行: '新能源车 / 出行',
    消费电子: '手机 / 智能终端',
    其他: '未单独细分的持仓',
  }

  return mapping[label] ?? '行业聚合'
}

const assetPieItems = computed(() => {
  const buckets = new Map<string, { value: number; members: string[] }>([
    ['股票', { value: 0, members: [] }],
    ['固定收益', { value: 0, members: [] }],
    ['现金', { value: Math.max(overview.value?.cash ?? 0, 0), members: ['账户现金'] }],
  ])

  response.value?.items.forEach((item) => {
    const bucket = classifyAssetBucket(item)
    const current = buckets.get(bucket) ?? { value: 0, members: [] }
    current.value += item.position_value ?? 0
    current.members.push(item.symbol ?? item.description ?? '--')
    buckets.set(bucket, current)
  })

  return [
    {
      label: '股票',
      value: buckets.get('股票')?.value ?? 0,
      color: '#56d5ff',
      note: '股票与 ADR 持仓',
      members: uniqueMembers(buckets.get('股票')?.members ?? []),
    },
    {
      label: '固定收益',
      value: buckets.get('固定收益')?.value ?? 0,
      color: '#6ee7b7',
      note: '国债 / 固收 ETF',
      members: uniqueMembers(buckets.get('固定收益')?.members ?? []),
    },
    {
      label: '现金',
      value: buckets.get('现金')?.value ?? 0,
      color: '#8b7cff',
      note: '账户现金余额',
      members: ['USD 现金余额'],
    },
  ].filter((item) => item.value > 0)
})

const industryPieItems = computed(() => {
  const palette = ['#56d5ff', '#6ee7b7', '#8b7cff', '#ffb454', '#ff7b98', '#7dd3fc', '#c084fc']
  const buckets = new Map<string, { value: number; members: string[] }>()

  response.value?.items.forEach((item) => {
    const industry = classifyIndustry(item)
    const current = buckets.get(industry) ?? { value: 0, members: [] }
    current.value += item.position_value ?? 0
    current.members.push(item.symbol ?? item.description ?? '--')
    buckets.set(industry, current)
  })

  return Array.from(buckets.entries())
    .sort((first, second) => second[1].value - first[1].value)
    .map(([label, payload], index) => ({
      label,
      value: payload.value,
      color: palette[index % palette.length],
      note: industryDescription(label),
      members: uniqueMembers(payload.members),
    }))
})

onMounted(() => {
  void initialize()
})

async function openPositionDetail(item: PositionItem): Promise<void> {
  const symbol = `${item.symbol ?? ''}`.trim()
  if (!symbol) {
    return
  }

  const key = `${item.asset_class ?? 'UNKNOWN'}:${symbol}`
  activePosition.value = item
  activeDetail.value = {
    key,
    symbol,
    description: item.description ?? '无名称',
    assetClass: item.asset_class,
    detail: null,
  }
  detailLoading.value = true
  detailErrorMessage.value = ''
  detailDialogVisible.value = true

  try {
    const detail = await fetchPositionDetail({
      symbol,
      asset_class: item.asset_class,
    })
    if (activeDetail.value?.key === key) {
      activeDetail.value = {
        ...activeDetail.value,
        detail,
      }
    }
  } catch (error) {
    detailErrorMessage.value = error instanceof Error ? error.message : '加载股票详情失败'
  } finally {
    if (activeDetail.value?.key === key) {
      detailLoading.value = false
    }
  }
}
</script>

<template>
  <section class="page-section">
    <LoadingBlock v-if="loading" />
    <ErrorBlock v-else-if="errorMessage" :message="errorMessage" />

    <template v-else>
      <PositionTreemap
        v-if="response"
        :items="response.items"
        :format-number="formatNumber"
        @select="openPositionDetail"
      />

      <section class="summary-layout summary-layout--triple">
        <section class="surface-panel">
          <div class="surface-panel__content summary-panel summary-panel--list">
          <h3 class="summary-title">持仓集中度</h3>
          <div v-if="!summary || summary.top_positions.length === 0" class="empty-state empty-state--inline">暂无集中度数据</div>
          <div v-else class="summary-list">
            <div v-for="item in summary.top_positions" :key="`${item.asset_class}-${item.symbol}`" class="summary-list__row">
              <div class="summary-list__meta">
                <strong>{{ item.symbol ?? '--' }}</strong>
                <p>{{ item.description ?? '无名称' }}</p>
              </div>
              <div class="summary-list__value">
                <strong>{{ formatNumber(item.position_value, 2) }}</strong>
                <span>{{ item.percent_of_nav === null ? '--' : `${formatNumber(item.percent_of_nav, 2)}%` }}</span>
              </div>
            </div>
          </div>
          </div>
        </section>

        <PieDistributionCard
          title="资金类别"
          subtitle="股票、固定收益与现金的当前占比"
          :items="assetPieItems"
          :format-number="formatNumber"
        />

        <PieDistributionCard
          title="行业分布"
          subtitle="基于持仓代码和描述的轻量行业归类"
          :items="industryPieItems"
          :format-number="formatNumber"
        />
      </section>

      <section class="surface-panel">
        <div class="surface-panel__content">
          <div class="section-header">
            <div>
              <h2 class="panel-title">持仓明细表</h2>
              <p class="panel-subtitle">点击表头可按日涨跌、已实现盈亏、未实现盈亏、成本、持仓市值和持仓占比排序；点击任意一行可打开股票详情。</p>
            </div>
          </div>
          <PositionTable v-if="response" :items="response.items" :format-number="formatNumber" @select="openPositionDetail" />
        </div>
      </section>

    </template>
  </section>

  <Dialog
    v-model:visible="detailDialogVisible"
    modal
    :draggable="false"
    :style="{ width: 'min(960px, 94vw)' }"
    class="position-detail-dialog"
    :header="activeDetail?.symbol ? `${activeDetail.symbol} 详情` : '详情'"
  >
    <div class="position-detail-dialog__body">
      <PositionSimpleDetail
        v-if="activePosition"
        :position="activePosition"
        :detail="activeDetail?.detail ?? null"
        :loading="detailLoading"
        :error-message="detailErrorMessage"
        :format-number="formatNumber"
      />
      <div v-else class="empty-state">请选择一只股票</div>
    </div>
  </Dialog>
</template>

<style scoped>
.empty-state--inline {
  min-height: auto;
  padding: 2rem 1rem;
}

.summary-panel {
  height: 100%;
}

.summary-panel--list {
  display: grid;
  align-content: start;
}

.position-detail-dialog__body {
  display: grid;
  gap: 0;
}

:global(.p-dialog-mask) {
  background: rgba(2, 6, 14, 0.82) !important;
  backdrop-filter: blur(6px);
  z-index: 9000 !important;
}

:global(.position-detail-dialog.p-dialog) {
  background: #071424 !important;
  border: 1px solid rgba(86, 213, 255, 0.32);
  border-radius: 22px;
  box-shadow:
    0 32px 96px rgba(0, 0, 0, 0.76),
    0 0 0 1px rgba(255, 255, 255, 0.05) inset;
  overflow: hidden;
  z-index: 9001 !important;
}

:global(.position-detail-dialog .p-dialog-header) {
  background: #091a2f !important;
  color: var(--color-text-primary);
  border-bottom: 1px solid rgba(129, 160, 207, 0.24);
  padding: 1rem 1.25rem;
}

:global(.position-detail-dialog .p-dialog-content) {
  background: #071424 !important;
  color: var(--color-text-primary);
  padding: 0 1.25rem 1.25rem;
}

:global(.position-detail-dialog .p-dialog-title) {
  color: var(--color-text-primary);
  font-weight: 800;
}

:global(.position-detail-dialog .p-dialog-header-icon) {
  color: var(--color-text-primary);
}

@media (max-width: 1400px) {
  .summary-layout--triple {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 980px) {
  .summary-layout--triple {
    grid-template-columns: 1fr;
  }
}
</style>
