<script setup lang="ts">
import { computed, ref } from 'vue'
import Column from 'primevue/column'
import DataTable from 'primevue/datatable'

import type { PositionItem } from '@/types/positions'

const props = defineProps<{
  items: PositionItem[]
  formatNumber: (value: number | null, digits?: number) => string
}>()
const emit = defineEmits<{
  select: [item: PositionItem]
}>()

type SortKey =
  | 'previous_day_change_percent'
  | 'total_realized_pnl'
  | 'total_unrealized_pnl'
  | 'diluted_cost_price'
  | 'cost_basis_money'
  | 'position_value'
  | 'percent_of_nav'

const sortKey = ref<SortKey>('position_value')
const sortOrder = ref<'asc' | 'desc'>('desc')

const sortableLabels: Record<SortKey, string> = {
  previous_day_change_percent: '日涨跌',
  total_realized_pnl: '已实现盈亏',
  total_unrealized_pnl: '未实现盈亏',
  diluted_cost_price: '摊薄成本价',
  cost_basis_money: '成本',
  position_value: '持仓市值',
  percent_of_nav: '持仓占比',
}

const sortedItems = computed(() => {
  const values = [...props.items]
  values.sort((left, right) => compareValues(left, right, sortKey.value, sortOrder.value))
  return values
})

function pnlClass(value: number | null): string {
  if (value === null || value === 0) {
    return 'table-pnl--neutral'
  }
  return value > 0 ? 'table-pnl--positive' : 'table-pnl--negative'
}

function percentText(value: number | null): string {
  if (value === null) {
    return '--'
  }
  return `${props.formatNumber(value, 2)}%`
}

function signedPercentText(value: number | null): string {
  if (value === null) {
    return '--'
  }
  const prefix = value > 0 ? '+' : ''
  return `${prefix}${props.formatNumber(value, 2)}%`
}

function dilutedCostTitle(item: PositionItem): string {
  if (item.diluted_cost_status === 'OK') {
    return `摊薄成本金额 ${props.formatNumber(item.diluted_cost_amount, 2)}`
  }
  if (item.diluted_cost_status === 'NO_TRADE_HISTORY') {
    return '无交易记录，可能为赠股、转仓或公司行动'
  }
  if (item.diluted_cost_status === 'QUANTITY_MISMATCH') {
    return '交易净数量与当前持仓不一致'
  }
  if (item.diluted_cost_status === 'INVALID_QUANTITY') {
    return '当前持仓数量不可用'
  }
  return '摊薄成本价不可用'
}

function setSort(nextKey: SortKey): void {
  if (sortKey.value === nextKey) {
    sortOrder.value = sortOrder.value === 'desc' ? 'asc' : 'desc'
    return
  }
  sortKey.value = nextKey
  sortOrder.value = 'desc'
}

function compareValues(
  left: PositionItem,
  right: PositionItem,
  currentSortKey: SortKey,
  currentSortOrder: 'asc' | 'desc',
): number {
  const leftValue = left[currentSortKey]
  const rightValue = right[currentSortKey]
  const leftNumber = typeof leftValue === 'number' ? leftValue : Number.NEGATIVE_INFINITY
  const rightNumber = typeof rightValue === 'number' ? rightValue : Number.NEGATIVE_INFINITY
  const result = leftNumber - rightNumber
  return currentSortOrder === 'asc' ? result : -result
}

function sortLabel(key: SortKey): string {
  return sortableLabels[key]
}

function sortIndicator(key: SortKey): string {
  if (sortKey.value !== key) {
    return '↕'
  }
  return sortOrder.value === 'desc' ? '↓' : '↑'
}

function onRowClick(event: { data: PositionItem }): void {
  emit('select', event.data)
}
</script>

<template>
  <div class="table-shell table-shell--desktop">
    <DataTable
      :value="sortedItems"
      class="terminal-datatable position-datatable"
      tableStyle="table-layout: fixed"
      @row-click="onRowClick"
    >
      <template #empty>
        <div class="empty-state">当前筛选条件下没有持仓数据</div>
      </template>

      <Column header="代码" headerClass="table-head--left table-col--symbol" bodyClass="table-col--symbol">
        <template #body="{ data }">
          <div class="table-symbol">
            <span class="table-symbol__code">{{ data.symbol ?? '--' }}</span>
            <span class="table-symbol__desc">{{ data.description ?? '无名称' }}</span>
          </div>
        </template>
      </Column>

      <Column header="数量" headerClass="table-head--number table-col--qty" bodyClass="table-number table-col--qty">
        <template #body="{ data }">
          <span class="cell-number">{{ formatNumber(data.quantity, 4) }}</span>
        </template>
      </Column>

      <Column header="持仓均价" headerClass="table-head--number table-col--price" bodyClass="table-number table-col--price">
        <template #body="{ data }">
          <span class="cell-number">{{ formatNumber(data.average_cost_price, 2) }}</span>
        </template>
      </Column>

      <Column headerClass="table-head--number table-col--price" bodyClass="table-number table-col--price">
        <template #header>
          <button type="button" class="sort-button" @click="setSort('diluted_cost_price')">
            <span>{{ sortLabel('diluted_cost_price') }}</span>
            <span class="sort-button__indicator">{{ sortIndicator('diluted_cost_price') }}</span>
          </button>
        </template>
        <template #body="{ data }">
          <span class="cell-number" :title="dilutedCostTitle(data)">
            {{ formatNumber(data.diluted_cost_price, 2) }}
          </span>
        </template>
      </Column>

      <Column headerClass="table-head--number table-col--day" bodyClass="table-number table-col--day">
        <template #header>
          <button type="button" class="sort-button" @click="setSort('previous_day_change_percent')">
            <span>{{ sortLabel('previous_day_change_percent') }}</span>
            <span class="sort-button__indicator">{{ sortIndicator('previous_day_change_percent') }}</span>
          </button>
        </template>
        <template #body="{ data }">
          <span class="cell-number" :class="pnlClass(data.previous_day_change_percent)">
            {{ signedPercentText(data.previous_day_change_percent) }}
          </span>
        </template>
      </Column>

      <Column headerClass="table-head--number table-col--pnl" bodyClass="table-number table-col--pnl">
        <template #header>
          <button type="button" class="sort-button" @click="setSort('total_unrealized_pnl')">
            <span>{{ sortLabel('total_unrealized_pnl') }}</span>
            <span class="sort-button__indicator">{{ sortIndicator('total_unrealized_pnl') }}</span>
          </button>
        </template>
        <template #body="{ data }">
          <div class="cell-metric">
            <span class="cell-number" :class="pnlClass(data.total_unrealized_pnl)">
              {{ formatNumber(data.total_unrealized_pnl, 2) }}
            </span>
            <span class="cell-metric__sub" :class="pnlClass(data.unrealized_pnl_percent)">
              {{ signedPercentText(data.unrealized_pnl_percent) }}
            </span>
          </div>
        </template>
      </Column>

      <Column headerClass="table-head--number table-col--pnl" bodyClass="table-number table-col--pnl">
        <template #header>
          <button type="button" class="sort-button" @click="setSort('total_realized_pnl')">
            <span>{{ sortLabel('total_realized_pnl') }}</span>
            <span class="sort-button__indicator">{{ sortIndicator('total_realized_pnl') }}</span>
          </button>
        </template>
        <template #body="{ data }">
          <div class="cell-metric">
            <span class="cell-number" :class="pnlClass(data.total_realized_pnl)">
              {{ formatNumber(data.total_realized_pnl, 2) }}
            </span>
            <span class="cell-metric__sub" :class="pnlClass(data.realized_pnl_percent)">
              {{ signedPercentText(data.realized_pnl_percent) }}
            </span>
          </div>
        </template>
      </Column>

      <Column headerClass="table-head--number table-col--cost" bodyClass="table-number table-col--cost">
        <template #header>
          <button type="button" class="sort-button" @click="setSort('cost_basis_money')">
            <span>{{ sortLabel('cost_basis_money') }}</span>
            <span class="sort-button__indicator">{{ sortIndicator('cost_basis_money') }}</span>
          </button>
        </template>
        <template #body="{ data }">
          <span class="cell-number">{{ formatNumber(data.cost_basis_money, 2) }}</span>
        </template>
      </Column>

      <Column header="市价" headerClass="table-head--number table-col--price" bodyClass="table-number table-col--price">
        <template #body="{ data }">
          <span class="cell-number">{{ formatNumber(data.mark_price, 2) }}</span>
        </template>
      </Column>

      <Column headerClass="table-head--number table-col--value" bodyClass="table-number table-col--value">
        <template #header>
          <button type="button" class="sort-button" @click="setSort('position_value')">
            <span>{{ sortLabel('position_value') }}</span>
            <span class="sort-button__indicator">{{ sortIndicator('position_value') }}</span>
          </button>
        </template>
        <template #body="{ data }">
          <span class="cell-number">{{ formatNumber(data.position_value, 2) }}</span>
        </template>
      </Column>

      <Column headerClass="table-head--number table-col--nav" bodyClass="table-number table-col--nav">
        <template #header>
          <button type="button" class="sort-button" @click="setSort('percent_of_nav')">
            <span>{{ sortLabel('percent_of_nav') }}</span>
            <span class="sort-button__indicator">{{ sortIndicator('percent_of_nav') }}</span>
          </button>
        </template>
        <template #body="{ data }">
          <span class="cell-number">{{ percentText(data.percent_of_nav) }}</span>
        </template>
      </Column>
    </DataTable>
  </div>

  <div class="mobile-data-list">
    <button
      v-for="item in sortedItems"
      :key="`${item.account_id}-${item.symbol}-${item.asset_class}`"
      type="button"
      class="mobile-data-card position-mobile-card"
      @click="emit('select', item)"
    >
      <div class="mobile-data-card__header">
        <div class="mobile-data-card__title">
          <strong>{{ item.symbol ?? '--' }}</strong>
          <small>{{ item.description ?? '无名称' }}</small>
        </div>
        <strong>{{ percentText(item.percent_of_nav) }}</strong>
      </div>

      <div class="mobile-data-grid">
        <div class="mobile-data-row">
          <span>持仓市值</span>
          <strong>{{ formatNumber(item.position_value, 2) }}</strong>
        </div>
        <div class="mobile-data-row">
          <span>数量</span>
          <strong>{{ formatNumber(item.quantity, 4) }}</strong>
        </div>
        <div class="mobile-data-row">
          <span>摊薄成本价</span>
          <strong :title="dilutedCostTitle(item)">{{ formatNumber(item.diluted_cost_price, 2) }}</strong>
        </div>
        <div class="mobile-data-row">
          <span>日涨跌</span>
          <strong :class="pnlClass(item.previous_day_change_percent)">{{ signedPercentText(item.previous_day_change_percent) }}</strong>
        </div>
        <div class="mobile-data-row">
          <span>未实现盈亏</span>
          <strong :class="pnlClass(item.total_unrealized_pnl)">{{ formatNumber(item.total_unrealized_pnl, 2) }}</strong>
        </div>
        <div class="mobile-data-row">
          <span>已实现盈亏</span>
          <strong :class="pnlClass(item.total_realized_pnl)">{{ formatNumber(item.total_realized_pnl, 2) }}</strong>
        </div>
        <div class="mobile-data-row">
          <span>成本</span>
          <strong>{{ formatNumber(item.cost_basis_money, 2) }}</strong>
        </div>
      </div>
    </button>
  </div>
</template>

<style scoped>
.cell-metric {
  display: grid;
  justify-items: end;
  gap: 2px;
}

.cell-metric__sub {
  font-size: 0.82rem;
  opacity: 0.82;
}

.sort-button {
  width: 100%;
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 0.38rem;
  border: 0;
  background: transparent;
  color: inherit;
  font: inherit;
  font-weight: 700;
  cursor: pointer;
  padding: 0;
}

.sort-button__indicator {
  color: var(--color-accent-strong);
  font-size: 0.88rem;
}

.position-datatable :deep(.table-col--symbol) {
  width: 19%;
}

.position-datatable :deep(.table-col--qty) {
  width: 7%;
}

.position-datatable :deep(.table-col--price) {
  width: 7.8%;
}

.position-datatable :deep(.table-col--day) {
  width: 7%;
}

.position-datatable :deep(.table-col--pnl) {
  width: 9.5%;
}

.position-datatable :deep(.table-col--cost) {
  width: 8.5%;
}

.position-datatable :deep(.table-col--value) {
  width: 10%;
}

.position-datatable :deep(.table-col--nav) {
  width: 8%;
}

.position-datatable :deep(.table-symbol__desc) {
  white-space: nowrap;
}

.position-datatable :deep(.p-datatable-tbody > tr) {
  cursor: pointer;
  transition: background-color 0.18s ease;
}

.position-datatable :deep(.p-datatable-tbody > tr:hover > td) {
  background: rgba(86, 213, 255, 0.04);
}

.position-mobile-card {
  width: 100%;
  color: var(--color-text-primary);
  cursor: pointer;
  text-align: left;
}

.position-mobile-card:hover {
  border-color: rgba(86, 213, 255, 0.34);
  background: rgba(19, 42, 70, 0.82);
}
</style>
