<script setup lang="ts">
import { computed } from 'vue'

import { useAuthSession } from '@/auth/session'
import type { PositionDetailResponse, PositionItem } from '@/types/positions'

const { authState } = useAuthSession()
const showTradeHistory = computed(() => authState.authenticated)

defineProps<{
  position: PositionItem
  detail: PositionDetailResponse | null
  loading?: boolean
  errorMessage?: string
  formatNumber: (value: number | null, digits?: number) => string
}>()

function pnlClass(value: number | null): string {
  if (value === null || value === 0) return 'table-pnl--neutral'
  return value > 0 ? 'table-pnl--positive' : 'table-pnl--negative'
}

function signedPercentText(value: number | null, formatNumber: (v: number | null, d?: number) => string): string {
  if (value === null) return '--'
  const prefix = value > 0 ? '+' : ''
  return `${prefix}${formatNumber(value, 2)}%`
}

function sortedTrades(detail: PositionDetailResponse | null): PositionDetailResponse['trades'] {
  if (!detail?.trades?.length) return []
  return [...detail.trades].sort((a, b) => {
    const da = a.date_time ?? a.trade_date ?? ''
    const db = b.date_time ?? b.trade_date ?? ''
    return db.localeCompare(da)
  }).slice(0, 10)
}

function sideLabel(buySell: string | null): string {
  if (buySell === 'BUY') return '买入'
  if (buySell === 'SELL') return '卖出'
  return buySell ?? '--'
}

function tradeDate(trade: { date_time?: string | null; trade_date?: string | null }): string {
  const raw = trade.date_time ?? trade.trade_date ?? ''
  if (!raw) return '--'
  return raw.slice(0, 10)
}
</script>

<template>
  <div class="simple-detail">
    <!-- Section 1: 当前仓位 -->
    <section class="simple-detail__section">
      <h4 class="simple-detail__heading">当前仓位</h4>
      <div class="detail-grid">
        <div class="detail-row">
          <span class="detail-label">代码</span>
          <span class="detail-value">{{ position.symbol ?? '--' }}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">名称</span>
          <span class="detail-value">{{ position.description ?? '--' }}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">数量</span>
          <span class="detail-value">{{ formatNumber(position.quantity, 4) }}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">持仓市值</span>
          <span class="detail-value">{{ formatNumber(position.position_value, 2) }}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">账户占比</span>
          <span class="detail-value">{{ position.percent_of_nav === null ? '--' : `${formatNumber(position.percent_of_nav, 2)}%` }}</span>
        </div>
      </div>
    </section>

    <!-- Section 2: 成本 / 现价 / 盈亏 -->
    <section class="simple-detail__section">
      <h4 class="simple-detail__heading">成本 / 现价 / 盈亏</h4>
      <div class="detail-grid">
        <div class="detail-row">
          <span class="detail-label">现价</span>
          <span class="detail-value">{{ formatNumber(position.mark_price, 2) }}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">持仓均价</span>
          <span class="detail-value">{{ formatNumber(position.average_cost_price, 2) }}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">摊薄成本价</span>
          <span class="detail-value">{{ formatNumber(position.diluted_cost_price, 2) }}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">成本金额</span>
          <span class="detail-value">{{ formatNumber(position.cost_basis_money, 2) }}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">未实现盈亏</span>
          <span class="detail-value" :class="pnlClass(position.total_unrealized_pnl)">
            {{ formatNumber(position.total_unrealized_pnl, 2) }}
            <small :class="pnlClass(position.unrealized_pnl_percent)">
              {{ signedPercentText(position.unrealized_pnl_percent, formatNumber) }}
            </small>
          </span>
        </div>
        <div class="detail-row">
          <span class="detail-label">已实现盈亏</span>
          <span class="detail-value" :class="pnlClass(position.total_realized_pnl)">
            {{ formatNumber(position.total_realized_pnl, 2) }}
            <small :class="pnlClass(position.realized_pnl_percent)">
              {{ signedPercentText(position.realized_pnl_percent, formatNumber) }}
            </small>
          </span>
        </div>
        <div class="detail-row">
          <span class="detail-label">前日涨跌</span>
          <span class="detail-value" :class="pnlClass(position.previous_day_change_percent)">
            {{ signedPercentText(position.previous_day_change_percent, formatNumber) }}
          </span>
        </div>
      </div>
    </section>

    <!-- Section 3: 最近交易记录 -->
    <section v-if="showTradeHistory" class="simple-detail__section">
      <h4 class="simple-detail__heading">最近交易记录</h4>
      <div v-if="loading" class="simple-detail__empty">交易记录加载中...</div>
      <div v-else-if="errorMessage" class="simple-detail__error">{{ errorMessage }}</div>
      <div v-else-if="sortedTrades(detail).length === 0" class="simple-detail__empty">暂无交易记录</div>
      <div v-else class="trade-mini-table-wrapper">
        <table class="trade-mini-table">
          <thead>
            <tr>
              <th>日期</th>
              <th>方向</th>
              <th class="trade-mini-table__num">数量</th>
              <th class="trade-mini-table__num">成交价</th>
              <th class="trade-mini-table__num">已实现盈亏</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(trade, idx) in sortedTrades(detail)" :key="idx">
              <td>{{ tradeDate(trade) }}</td>
              <td :class="trade.buy_sell === 'BUY' ? 'side-buy' : 'side-sell'">{{ sideLabel(trade.buy_sell) }}</td>
              <td class="trade-mini-table__num">{{ formatNumber(trade.quantity, 4) }}</td>
              <td class="trade-mini-table__num">{{ formatNumber(trade.trade_price, 2) }}</td>
              <td class="trade-mini-table__num" :class="pnlClass(trade.fifo_pnl_realized)">{{ formatNumber(trade.fifo_pnl_realized, 2) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>

<style scoped>
.simple-detail {
  display: flex;
  flex-direction: column;
  gap: 1.4rem;
  padding: 1rem 0;
}

.simple-detail__error,
.simple-detail__empty {
  padding: 2rem 1rem;
  text-align: center;
  color: var(--color-text-muted);
}

.simple-detail__error {
  color: var(--color-negative);
}

.simple-detail__section {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
  background: #0b1d33;
  border: 1px solid rgba(129, 160, 207, 0.18);
  border-radius: 16px;
  padding: 1rem;
  box-shadow: 0 10px 28px rgba(0, 0, 0, 0.18);
}

.simple-detail__heading {
  margin: 0;
  font-size: 0.92rem;
  font-weight: 700;
  color: var(--color-accent-strong);
  border-bottom: 1px solid var(--color-border);
  padding-bottom: 0.4rem;
}

.detail-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 0.35rem 1.6rem;
}

.detail-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  padding: 0.2rem 0;
}

.detail-label {
  color: #9fb0cc;
  font-size: 0.88rem;
}

.detail-value {
  color: #f2f7ff;
  font-weight: 600;
  font-size: 0.92rem;
  text-align: right;
  display: inline-flex;
  align-items: baseline;
  gap: 0.35rem;
}

.detail-value small {
  font-weight: 500;
  font-size: 0.82rem;
  opacity: 0.82;
}

.side-buy {
  color: #4d95ff;
}

.side-sell {
  color: #ff5c73;
}

.trade-mini-table-wrapper {
  overflow-x: auto;
}

.trade-mini-table {
  width: 100%;
  min-width: 620px;
  border-collapse: collapse;
  font-size: 0.88rem;
}

.trade-mini-table th {
  text-align: left;
  background: rgba(15, 34, 58, 0.95);
  color: #aebfda;
  font-weight: 600;
  font-size: 0.82rem;
  padding: 0.35rem 0.5rem;
  border-bottom: 1px solid var(--color-border);
}

.trade-mini-table td {
  padding: 0.4rem 0.5rem;
  color: #edf5ff;
  border-bottom: 1px solid rgba(129, 160, 207, 0.06);
}

.trade-mini-table__num {
  text-align: right;
}

.table-pnl--positive {
  color: var(--color-positive);
}

.table-pnl--negative {
  color: var(--color-negative);
}

.table-pnl--neutral {
  color: var(--color-text-primary);
}
</style>
