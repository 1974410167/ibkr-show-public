<template>
  <div class="market-events-page">
    <header class="events-hero">
      <div class="events-hero__copy">
        <p class="eyebrow">Market Calendar</p>
        <h1>重点事件</h1>
        <p class="hero-subtitle">跟踪宏观、央行、公司行动和市场休市事件。</p>
      </div>
      <div class="risk-summary" aria-label="事件风险概览">
        <div class="risk-card" :class="riskLevelClass(riskSummary?.today?.risk_level)">
          <span>今日</span>
          <strong>{{ riskLevelLabel(riskSummary?.today?.risk_level) }}</strong>
          <small>{{ riskCountsText(riskSummary?.today) }}</small>
        </div>
        <div class="risk-card" :class="riskLevelClass(riskSummary?.next_7_days?.risk_level)">
          <span>未来 7 天</span>
          <strong>{{ riskLevelLabel(riskSummary?.next_7_days?.risk_level) }}</strong>
          <small>{{ riskCountsText(riskSummary?.next_7_days) }}</small>
        </div>
        <div class="risk-card" :class="riskLevelClass(riskSummary?.next_30_days?.risk_level)">
          <span>未来 30 天</span>
          <strong>{{ riskLevelLabel(riskSummary?.next_30_days?.risk_level) }}</strong>
          <small>{{ riskCountsText(riskSummary?.next_30_days) }}</small>
        </div>
      </div>
    </header>

    <section class="events-layout">
      <main class="events-main">
        <div class="events-toolbar">
          <div>
            <h2>事件日历</h2>
            <p>{{ total }} 个事件 · 按发布时间排序</p>
          </div>
          <div class="filters">
            <select v-model="filters.importance" @change="resetAndLoad">
              <option value="">全部等级</option>
              <option value="CRITICAL">极高</option>
              <option value="HIGH">高</option>
              <option value="MEDIUM">中</option>
              <option value="LOW">低</option>
            </select>
            <select v-model="filters.category" @change="resetAndLoad">
              <option value="">全部分类</option>
              <option value="MACRO">宏观</option>
              <option value="FED">美联储</option>
              <option value="COMPANY">公司</option>
              <option value="MARKET">市场</option>
              <option value="NEWS">新闻</option>
            </select>
            <select v-model="filters.source_code" @change="resetAndLoad">
              <option value="">全部数据源</option>
              <option value="BLS">BLS</option>
              <option value="BEA">BEA</option>
              <option value="FRED">FRED</option>
              <option value="FED">FED</option>
              <option value="LONGBRIDGE">Longbridge</option>
            </select>
            <input v-model="filters.keyword" placeholder="搜索事件" @input="debounceLoad" />
          </div>
        </div>

        <div v-if="loading" class="loading">正在加载重点事件...</div>
        <div v-else-if="events.length === 0" class="empty">当前筛选条件下暂无事件</div>
        <div v-else class="event-list">
          <article
            v-for="event in events"
            :key="event.id"
            class="event-row"
            :class="`is-${event.importance.toLowerCase()}`"
            @click="openDetail(event.id)"
          >
            <div class="event-time">
              <strong>{{ formatDate(event.scheduled_at) }}</strong>
              <span>{{ formatTime(event.scheduled_at) }}</span>
            </div>
            <div class="event-info">
              <div class="event-title-line">
                <div class="event-title-copy">
                  <h3>{{ event.title }}</h3>
                  <p>{{ eventTypeLabel(event.event_type) }}</p>
                </div>
                <span class="importance-pill" :class="event.importance.toLowerCase()">
                  {{ importanceLabel(event.importance) }}
                </span>
              </div>
              <div class="event-meta">
                <span>{{ categoryLabel(event.category) }}</span>
                <span>{{ sourceLabel(event.source_code) }}</span>
                <span v-if="event.market">{{ event.market }}</span>
                <span v-if="event.period">{{ event.period }}</span>
              </div>
              <div v-if="event.values?.length" class="event-values">
                <span v-for="v in event.values.slice(0, 2)" :key="v.value_type">
                  {{ v.label || valueTypeLabel(v.value_type) }} {{ v.value_text || v.value_numeric || '-' }}
                </span>
              </div>
            </div>
          </article>
        </div>

        <div v-if="total > limit" class="pagination">
          <button :disabled="offset === 0" @click="prevPage">上一页</button>
          <span>{{ offset + 1 }}-{{ Math.min(offset + limit, total) }} / {{ total }}</span>
          <button :disabled="offset + limit >= total" @click="nextPage">下一页</button>
        </div>
      </main>

      <aside class="events-aside">
        <section class="side-panel next-panel">
          <div class="panel-heading">
            <h2>下一场</h2>
            <span v-if="nextEvent">{{ importanceLabel(nextEvent.importance) }}</span>
          </div>
          <template v-if="nextEvent">
            <h3>{{ nextEvent.title }}</h3>
            <p class="event-cn-name">{{ eventTypeLabel(nextEvent.event_type) }}</p>
            <p>{{ formatFullDate(nextEvent.scheduled_at) }}</p>
            <div class="side-meta">
              <span>{{ categoryLabel(nextEvent.category) }}</span>
              <span>{{ sourceLabel(nextEvent.source_code) }}</span>
            </div>
          </template>
          <p v-else class="empty-text">暂无即将到来的事件</p>
        </section>

        <section class="side-panel sources-section">
          <div class="panel-heading">
            <h2>数据源</h2>
            <span>{{ enabledSourceCount }} 个已接入</span>
          </div>
          <div class="sources-list">
            <div v-for="src in sources" :key="src.source_code" class="source-item">
              <div>
                <span class="source-code">{{ src.source_code }}</span>
                <strong>{{ sourceDisplayName(src.source_code) }}</strong>
              </div>
              <span class="source-pill" :class="sourceHealthClass(src)">
                {{ sourceHealthLabel(src) }}
              </span>
            </div>
          </div>
        </section>
      </aside>
    </section>

    <div v-if="detailEvent" class="detail-overlay" @click.self="closeDetail">
      <div class="detail-panel" role="dialog" aria-modal="true">
        <button class="close-btn" @click="closeDetail" aria-label="关闭">×</button>
        <h2>{{ detailEvent.title }}</h2>
        <p class="detail-subtitle">{{ eventTypeLabel(detailEvent.event_type) }}</p>
        <div class="detail-meta">
          <span class="tag">{{ categoryLabel(detailEvent.category) }}</span>
          <span class="tag importance" :class="detailEvent.importance.toLowerCase()">{{ importanceLabel(detailEvent.importance) }}</span>
          <span class="tag">{{ statusLabel(detailEvent.status) }}</span>
        </div>
        <p v-if="detailEvent.summary">{{ detailEvent.summary }}</p>

        <h3>说明</h3>
        <p class="detail-explanation">{{ eventTypeExplanation(detailEvent.event_type) }}</p>

        <h3>数值</h3>
        <div v-if="detailEvent.values?.length" class="values-grid">
          <div v-for="v in detailEvent.values" :key="v.value_type" class="value-item">
            <div class="value-label">{{ v.label || valueTypeLabel(v.value_type) }}</div>
            <div class="value-data">{{ v.value_text || v.value_numeric || '-' }}</div>
          </div>
        </div>
        <p v-else class="empty-text">暂无数值</p>

        <h3>影响</h3>
        <div v-if="detailEvent.impacts?.length">
          <div v-for="(imp, index) in detailEvent.impacts" :key="imp.symbol || `${imp.asset_class || 'impact'}-${index}`" class="impact-item">
            <span class="symbol">{{ imp.symbol || imp.asset_class || '-' }}</span>
            <span class="direction" :class="imp.impact_direction.toLowerCase()">{{ directionLabel(imp.impact_direction) }}</span>
            <span class="level">{{ imp.impact_level }}</span>
            <span v-if="imp.reason" class="reason">{{ imp.reason }}</span>
          </div>
        </div>
        <p v-else class="empty-text">暂无影响分析</p>

        <h3 v-if="detailEvent.news_links?.length">相关新闻</h3>
        <div v-for="(nl, index) in detailEvent.news_links" :key="nl.url || `${nl.title}-${index}`" class="news-item">
          <a :href="nl.url" target="_blank" rel="noopener">{{ nl.title }}</a>
          <span class="publisher">{{ nl.publisher }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import {
  getMarketEventDetail,
  getMarketEventRiskSummary,
  getMarketEventSources,
  getMarketEvents,
} from '@/api/marketEvents'
import type {
  MarketEventCategory,
  MarketEventDetail,
  MarketEventImportance,
  MarketEventListItem,
  MarketEventRiskSummary,
  MarketEventRiskSummaryResponse,
  MarketEventSourceCode,
  MarketEventSourceStatus,
  MarketEventStatus,
  MarketEventValueType,
} from '@/types/marketEvent'

const loading = ref(false)
const events = ref<MarketEventListItem[]>([])
const total = ref(0)
const limit = ref(50)
const offset = ref(0)
const riskSummary = ref<MarketEventRiskSummaryResponse | null>(null)
const sources = ref<MarketEventSourceStatus[]>([])
const detailEvent = ref<MarketEventDetail | null>(null)

const filters = reactive({
  importance: '',
  category: '',
  source_code: '',
  keyword: '',
})

const nextEvent = computed(() => events.value[0] ?? null)
const enabledSourceCount = computed(() => sources.value.filter((src) => src.enabled).length)

let debounceTimer: ReturnType<typeof setTimeout> | null = null

function debounceLoad() {
  if (debounceTimer) clearTimeout(debounceTimer)
  debounceTimer = setTimeout(() => resetAndLoad(), 300)
}

function resetAndLoad() {
  offset.value = 0
  loadEvents()
}

async function loadEvents() {
  loading.value = true
  try {
    const params: Record<string, unknown> = {
      limit: limit.value,
      offset: offset.value,
      sort_by: 'scheduled_at',
      sort_order: 'asc',
    }
    if (filters.importance) params.importance = filters.importance
    if (filters.category) params.category = filters.category
    if (filters.source_code) params.source_code = filters.source_code
    if (filters.keyword) params.keyword = filters.keyword

    const result = await getMarketEvents(params)
    events.value = result.items
    total.value = result.total
  } catch {
    events.value = []
  } finally {
    loading.value = false
  }
}

async function loadRiskSummary() {
  try {
    riskSummary.value = await getMarketEventRiskSummary()
  } catch {
    riskSummary.value = null
  }
}

async function loadSources() {
  try {
    sources.value = await getMarketEventSources()
  } catch {
    sources.value = []
  }
}

async function openDetail(id: string) {
  try {
    detailEvent.value = await getMarketEventDetail(id)
  } catch {
    detailEvent.value = null
  }
}

function closeDetail() {
  detailEvent.value = null
}

function prevPage() {
  offset.value = Math.max(0, offset.value - limit.value)
  loadEvents()
}

function nextPage() {
  offset.value += limit.value
  loadEvents()
}

function riskLevelClass(level?: string) {
  return (level || 'LOW').toLowerCase()
}

function riskLevelLabel(level?: string) {
  const map: Record<string, string> = { LOW: '低', MEDIUM: '中', HIGH: '高', CRITICAL: '极高' }
  return map[level || ''] || '低'
}

function riskCountsText(summary?: MarketEventRiskSummary) {
  if (!summary) return '暂无事件'
  const parts = [
    summary.critical_count ? `极高 ${summary.critical_count}` : '',
    summary.high_count ? `高 ${summary.high_count}` : '',
    summary.medium_count ? `中 ${summary.medium_count}` : '',
  ].filter(Boolean)
  return parts.length ? parts.join(' · ') : '暂无高风险'
}

function importanceLabel(imp: MarketEventImportance) {
  const map: Record<string, string> = { LOW: '低', MEDIUM: '中', HIGH: '高', CRITICAL: '极高' }
  return map[imp] || imp
}

function categoryLabel(cat: MarketEventCategory) {
  const map: Record<string, string> = {
    MACRO: '宏观',
    FED: '美联储',
    COMPANY: '公司',
    MARKET: '市场',
    NEWS: '新闻',
    CRYPTO: '加密',
    POLICY: '政策',
    MANUAL: '手动',
  }
  return map[cat] || cat
}

function eventTypeLabel(type: string) {
  const map: Record<string, string> = {
    CPI: '消费者价格指数',
    PPI: '生产者价格指数',
    NONFARM_PAYROLLS: '非农就业',
    UNEMPLOYMENT_RATE: '失业率',
    JOLTS: '职位空缺与劳动力流动调查',
    PCE: '个人消费支出物价指数',
    GDP: '国内生产总值',
    ISM_MANUFACTURING_PMI: 'ISM 制造业 PMI',
    ISM_SERVICES_PMI: 'ISM 服务业 PMI',
    FOMC_RATE_DECISION: 'FOMC 利率决议',
    FOMC_MINUTES: 'FOMC 会议纪要',
    FOMC_SEP: '美联储经济预测摘要',
    FED_SPEECH: '美联储官员讲话',
    EARNINGS: '财报发布',
    DIVIDEND: '股息事件',
    SPLIT: '拆股事件',
    IPO: '新股上市',
    INVESTOR_DAY: '投资者日',
    SHAREHOLDER_MEETING: '股东大会',
    MARKET_CLOSED: '市场休市',
    HALF_TRADING_DAY: '半日交易',
    TRADING_SESSION_CHANGE: '交易时段调整',
    NEWS: '新闻事件',
    POLICY: '政策事件',
    TARIFF: '关税事件',
    EXPORT_CONTROL: '出口管制',
    CRYPTO_EVENT: '加密市场事件',
    BTC_EVENT: '比特币事件',
    MSTR_BTC_EVENT: 'MSTR 比特币相关事件',
    MANUAL_EVENT: '手动维护事件',
    UNKNOWN: '其他事件',
  }
  return map[type] || type.replace(/_/g, ' ')
}

function eventTypeExplanation(type: string) {
  const map: Record<string, string> = {
    CPI: '消费者价格指数衡量居民购买一篮子商品和服务的价格变化，是观察通胀压力、利率预期和消费成本变化的核心指标。',
    PPI: '生产者价格指数衡量企业出厂价格和生产环节成本变化，常用于判断通胀是否会从上游传导到消费者端。',
    NONFARM_PAYROLLS: '非农就业反映美国非农业部门新增就业人数，是判断劳动力市场强弱、薪资压力和美联储政策路径的重要数据。',
    UNEMPLOYMENT_RATE: '失业率衡量劳动力中没有工作但正在寻找工作的人口比例，用于观察就业市场是否降温或过热。',
    JOLTS: '职位空缺与劳动力流动调查反映岗位空缺、招聘和离职情况，用来观察劳动力需求和工资谈判压力。',
    PCE: '个人消费支出物价指数衡量居民消费价格变化，是美联储更偏好的通胀指标，核心 PCE 尤其影响利率预期。',
    GDP: '国内生产总值衡量一个经济体在一定时期内生产的最终商品和服务总量，是观察经济增长速度和周期位置的核心数据。',
    ISM_MANUFACTURING_PMI: 'ISM 制造业 PMI 反映制造业订单、生产、就业和库存景气度，通常高于 50 表示扩张，低于 50 表示收缩。',
    ISM_SERVICES_PMI: 'ISM 服务业 PMI 反映服务业商业活动、订单和就业景气度，对美国经济判断很重要，因为服务业占比较高。',
    FOMC_RATE_DECISION: 'FOMC 利率决议公布美联储政策利率决定和政策声明，直接影响美元、美债收益率、股票估值和风险偏好。',
    FOMC_MINUTES: 'FOMC 会议纪要披露美联储委员讨论细节，有助于判断政策分歧、通胀担忧和后续加息或降息倾向。',
    FOMC_SEP: '美联储经济预测摘要包含委员对利率、通胀、失业率和经济增长的预测，点阵图常用于观察未来政策路径。',
    FED_SPEECH: '美联储官员讲话可能透露对通胀、就业和利率路径的态度，市场会据此调整政策预期。',
    EARNINGS: '财报发布披露公司收入、利润、利润率和指引变化，是判断个股基本面和估值合理性的关键事件。',
    DIVIDEND: '股息事件记录公司分红相关日期和金额，影响现金流、除息价格调整和收益型投资者判断。',
    SPLIT: '拆股事件表示公司按比例增加股票数量并降低单股价格，本身不改变公司价值，但可能影响流动性和交易情绪。',
    IPO: '新股上市是公司首次公开发行并开始交易，可能带来行业估值参照和市场风险偏好信号。',
    INVESTOR_DAY: '投资者日通常包含公司战略、长期目标和业务更新，可能改变市场对成长空间和利润率的预期。',
    SHAREHOLDER_MEETING: '股东大会涉及董事会、治理、投票和重大议案，可能影响公司治理和资本配置预期。',
    MARKET_CLOSED: '市场休市表示对应市场全天不交易，会影响订单执行、流动性安排和跨市场风险管理。',
    HALF_TRADING_DAY: '半日交易表示市场提前收盘，流动性和成交量通常下降，需要注意交易时间缩短。',
    TRADING_SESSION_CHANGE: '交易时段调整表示开收盘或盘前盘后安排变化，可能影响订单时间和行情连续性。',
    NEWS: '新闻事件是来自公开信息源的市场相关消息，需要结合来源、时间和影响资产判断实际重要性。',
    POLICY: '政策事件涉及监管、财政、产业或货币政策变化，可能影响行业盈利、估值和风险偏好。',
    TARIFF: '关税事件涉及进口税率或贸易限制变化，可能影响供应链成本、企业利润率和相关行业估值。',
    EXPORT_CONTROL: '出口管制涉及技术、设备或产品出口限制，常影响半导体、AI、国防和跨国供应链公司。',
    CRYPTO_EVENT: '加密市场事件反映数字资产相关政策、价格或行业变化，可能影响加密资产和相关上市公司。',
    BTC_EVENT: '比特币事件聚焦比特币价格、监管、ETF 或链上生态变化，可能影响加密市场风险偏好。',
    MSTR_BTC_EVENT: 'MSTR 比特币相关事件关注 MicroStrategy 与比特币持仓、融资和价格波动之间的关系。',
    MANUAL_EVENT: '手动维护事件是管理员补充的重要事项，用于覆盖自动数据源尚未收录但需要关注的事件。',
    UNKNOWN: '该事件暂无明确分类，需要结合标题、来源和发布时间判断其含义和影响。',
  }
  return map[type] || `${eventTypeLabel(type)}：暂无固定说明，请结合事件标题、来源和发布时间判断。`
}

function statusLabel(status: MarketEventStatus) {
  const map: Record<string, string> = {
    SCHEDULED: '已排期',
    WATCHING: '关注中',
    RELEASED: '已发布',
    VALUE_UPDATED: '数值已更新',
    INTERPRETED: '已解读',
    REVIEWED: '已复盘',
    REVISED: '已修订',
    CANCELLED: '已取消',
    FAILED: '失败',
  }
  return map[status] || status
}

function valueTypeLabel(type: MarketEventValueType) {
  const map: Record<string, string> = {
    PREVIOUS: '前值',
    FORECAST: '预期',
    ACTUAL: '实际',
    REVISED: '修正',
    CONSENSUS: '共识',
    LOW_ESTIMATE: '低估',
    HIGH_ESTIMATE: '高估',
  }
  return map[type] || type
}

function sourceDisplayName(code: MarketEventSourceCode) {
  const map: Record<MarketEventSourceCode, string> = {
    BLS: '劳工统计局',
    BEA: '经济分析局',
    FRED: '圣路易斯联储',
    FED: '美联储',
    ISM: '供应管理协会',
    LONGBRIDGE: 'Longbridge',
    MANUAL: '手动维护',
    SYSTEM: '系统',
  }
  return map[code] || code
}

function sourceLabel(code: MarketEventSourceCode) {
  return code === 'LONGBRIDGE' ? 'Longbridge' : code
}

function sourceHealthLabel(src: MarketEventSourceStatus) {
  if (!src.enabled) return '停用'
  if (src.last_check_status === 'SUCCESS') return '可用'
  if (src.last_check_status === 'FAILED') return '需检查'
  return '已接入'
}

function sourceHealthClass(src: MarketEventSourceStatus) {
  if (!src.enabled) return 'disabled'
  if (src.last_check_status === 'SUCCESS') return 'success'
  if (src.last_check_status === 'FAILED') return 'failed'
  return 'connected'
}

function directionLabel(dir: string) {
  const map: Record<string, string> = { POSITIVE: '利好', NEGATIVE: '利空', NEUTRAL: '中性', UNCERTAIN: '不确定', MIXED: '多空混合' }
  return map[dir] || dir
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })
}

function formatTime(iso: string) {
  return new Date(iso).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

function formatFullDate(iso: string) {
  return new Date(iso).toLocaleString('zh-CN', {
    month: 'long',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

onMounted(() => {
  loadEvents()
  loadRiskSummary()
  loadSources()
})
</script>

<style scoped>
.market-events-page {
  box-sizing: border-box;
  width: 100%;
  max-width: 1540px;
  margin: 0 auto;
  padding: 32px 24px 48px;
  overflow-x: hidden;
}

.events-hero {
  display: grid;
  grid-template-columns: minmax(320px, 0.85fr) minmax(0, 1.15fr);
  gap: 24px;
  align-items: stretch;
  margin-bottom: 24px;
}

.events-hero__copy,
.risk-card,
.events-main,
.side-panel {
  border: 1px solid rgba(147, 197, 253, 0.18);
  background: rgba(8, 22, 40, 0.34);
  box-shadow: 0 18px 50px rgba(0, 0, 0, 0.14);
  backdrop-filter: blur(10px);
}

.events-hero__copy {
  border-radius: 8px;
  padding: 28px 30px;
}

.eyebrow {
  margin: 0 0 10px;
  color: #67e8f9;
  font-size: 0.78rem;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

h1,
h2,
h3,
p {
  margin-top: 0;
}

h1 {
  margin-bottom: 10px;
  font-size: clamp(2rem, 3vw, 3.1rem);
  line-height: 1.05;
}

.hero-subtitle {
  max-width: 520px;
  margin-bottom: 0;
  color: rgba(226, 239, 255, 0.78);
  font-size: 1rem;
}

.risk-summary {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
  min-width: 0;
}

.risk-card {
  border-radius: 8px;
  padding: 22px;
  min-width: 0;
}

.risk-card span,
.risk-card small {
  display: block;
  color: rgba(226, 239, 255, 0.72);
}

.risk-card span {
  font-size: 0.86rem;
  font-weight: 700;
}

.risk-card strong {
  display: block;
  margin: 12px 0 10px;
  font-size: 1.9rem;
  line-height: 1;
}

.risk-card small {
  overflow-wrap: anywhere;
}

.risk-card.low strong { color: #6ee7b7; }
.risk-card.medium strong { color: #fde68a; }
.risk-card.high strong { color: #fdba74; }
.risk-card.critical strong { color: #fca5a5; }

.events-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(280px, 320px);
  gap: 24px;
  align-items: start;
}

.events-main,
.side-panel {
  border-radius: 8px;
}

.events-main {
  padding: 22px;
}

.events-toolbar {
  display: flex;
  gap: 18px;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 18px;
}

.events-toolbar h2,
.panel-heading h2 {
  margin-bottom: 4px;
  font-size: 1.1rem;
}

.events-toolbar p {
  margin-bottom: 0;
  color: rgba(226, 239, 255, 0.62);
  font-size: 0.86rem;
}

.filters {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
}

.filters select,
.filters input {
  min-height: 36px;
  border: 1px solid rgba(147, 197, 253, 0.18);
  border-radius: 6px;
  background: rgba(10, 26, 47, 0.72);
  color: #eef6ff;
  font-size: 0.86rem;
}

.filters select {
  padding: 0 30px 0 10px;
}

.filters input {
  width: 180px;
  padding: 0 12px;
}

.loading,
.empty {
  min-height: 260px;
  display: grid;
  place-items: center;
  color: rgba(226, 239, 255, 0.68);
}

.event-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.event-row {
  display: grid;
  grid-template-columns: 82px minmax(0, 1fr);
  gap: 16px;
  align-items: start;
  padding: 16px;
  border: 1px solid rgba(147, 197, 253, 0.14);
  border-left-width: 4px;
  border-radius: 8px;
  background: rgba(6, 18, 33, 0.42);
  cursor: pointer;
  transition: border-color 0.15s ease, background 0.15s ease, transform 0.15s ease;
}

.event-row:hover {
  border-color: rgba(103, 232, 249, 0.58);
  background: rgba(10, 31, 55, 0.72);
  transform: translateY(-1px);
}

.event-row.is-critical { border-left-color: #f87171; }
.event-row.is-high { border-left-color: #fb923c; }
.event-row.is-medium { border-left-color: #facc15; }
.event-row.is-low { border-left-color: #34d399; }

.event-time {
  text-align: right;
}

.event-time strong,
.event-time span {
  display: block;
}

.event-time strong {
  font-size: 1rem;
}

.event-time span {
  margin-top: 4px;
  color: rgba(226, 239, 255, 0.7);
  font-size: 0.82rem;
}

.event-info {
  min-width: 0;
}

.event-title-line {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  justify-content: space-between;
}

.event-title-copy {
  min-width: 0;
}

.event-title-copy h3 {
  margin-bottom: 7px;
  font-size: 1rem;
  line-height: 1.35;
  overflow-wrap: anywhere;
}

.event-title-copy p,
.event-cn-name,
.detail-subtitle {
  margin-bottom: 0;
  color: rgba(226, 239, 255, 0.58);
  font-size: 0.82rem;
  line-height: 1.45;
}

.importance-pill,
.source-pill,
.tag {
  display: inline-flex;
  align-items: center;
  min-height: 22px;
  border-radius: 999px;
  padding: 0 9px;
  font-size: 0.72rem;
  font-weight: 800;
  white-space: nowrap;
}

.importance-pill.critical,
.tag.importance.critical { color: #fecaca; background: rgba(127, 29, 29, 0.42); }
.importance-pill.high,
.tag.importance.high { color: #fed7aa; background: rgba(154, 52, 18, 0.4); }
.importance-pill.medium,
.tag.importance.medium { color: #fef3c7; background: rgba(133, 77, 14, 0.36); }
.importance-pill.low,
.tag.importance.low { color: #bbf7d0; background: rgba(20, 83, 45, 0.36); }

.event-meta,
.event-values,
.side-meta,
.detail-meta {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.event-meta span,
.event-values span,
.side-meta span {
  color: rgba(226, 239, 255, 0.72);
  font-size: 0.78rem;
}

.event-meta span:not(:last-child)::after,
.side-meta span:not(:last-child)::after {
  content: "·";
  margin-left: 8px;
  color: rgba(226, 239, 255, 0.35);
}

.event-values {
  margin-top: 8px;
}

.event-values span {
  border: 1px solid rgba(147, 197, 253, 0.14);
  border-radius: 6px;
  padding: 4px 7px;
  background: rgba(15, 23, 42, 0.35);
}

.pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding-top: 20px;
}

.pagination button {
  min-height: 34px;
  border: 1px solid rgba(147, 197, 253, 0.2);
  border-radius: 6px;
  background: rgba(10, 26, 47, 0.72);
  color: #eef6ff;
  cursor: pointer;
}

.pagination button:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.events-aside {
  display: flex;
  flex-direction: column;
  gap: 16px;
  position: sticky;
  top: 24px;
  min-width: 0;
}

.side-panel {
  padding: 18px;
  min-width: 0;
}

.panel-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}

.panel-heading span {
  color: rgba(226, 239, 255, 0.66);
  font-size: 0.8rem;
  font-weight: 700;
}

.next-panel h3 {
  margin-bottom: 10px;
  font-size: 1rem;
  line-height: 1.35;
  overflow-wrap: anywhere;
}

.next-panel p:not(.event-cn-name) {
  margin-bottom: 10px;
  color: rgba(226, 239, 255, 0.75);
}

.event-cn-name {
  margin-top: -4px;
  margin-bottom: 10px;
}

.sources-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.source-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px;
  border: 1px solid rgba(147, 197, 253, 0.12);
  border-radius: 8px;
  background: rgba(6, 18, 33, 0.36);
}

.source-item > div {
  min-width: 0;
}

.source-code {
  display: block;
  margin-bottom: 3px;
  color: #67e8f9;
  font-size: 0.7rem;
  font-weight: 800;
}

.source-item strong {
  display: block;
  font-size: 0.9rem;
  overflow-wrap: anywhere;
}

.source-pill.success { color: #bbf7d0; background: rgba(20, 83, 45, 0.38); }
.source-pill.failed { color: #fecaca; background: rgba(127, 29, 29, 0.42); }
.source-pill.connected { color: #bae6fd; background: rgba(12, 74, 110, 0.42); }
.source-pill.disabled { color: rgba(226, 239, 255, 0.54); background: rgba(71, 85, 105, 0.32); }

.detail-overlay {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.48);
  padding: 24px;
}

.detail-panel {
  position: relative;
  box-sizing: border-box;
  width: min(720px, calc(100vw - 48px));
  max-height: calc(100vh - 72px);
  overflow-y: auto;
  border: 1px solid rgba(147, 197, 253, 0.2);
  border-radius: 8px;
  background: #071827;
  box-shadow: 0 30px 90px rgba(0, 0, 0, 0.42);
  padding: 30px;
}

.close-btn {
  position: absolute;
  top: 16px;
  right: 16px;
  width: 34px;
  height: 34px;
  border: 1px solid rgba(147, 197, 253, 0.18);
  border-radius: 50%;
  background: rgba(10, 26, 47, 0.8);
  color: #eef6ff;
  cursor: pointer;
}

.detail-panel h2 {
  max-width: calc(100% - 54px);
  margin-bottom: 8px;
  font-size: 1.25rem;
  line-height: 1.3;
  overflow-wrap: anywhere;
}

.detail-subtitle {
  margin-bottom: 14px;
}

.detail-explanation {
  margin-bottom: 0;
  color: rgba(226, 239, 255, 0.78);
  font-size: 0.9rem;
  line-height: 1.7;
}

.detail-panel h3 {
  margin: 24px 0 10px;
  color: rgba(226, 239, 255, 0.72);
  font-size: 0.9rem;
}

.tag {
  background: rgba(148, 163, 184, 0.18);
  color: rgba(226, 239, 255, 0.82);
}

.values-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.value-item {
  border: 1px solid rgba(147, 197, 253, 0.14);
  border-radius: 8px;
  padding: 12px;
  background: rgba(6, 18, 33, 0.42);
}

.value-label {
  color: rgba(226, 239, 255, 0.64);
  font-size: 0.76rem;
}

.value-data {
  margin-top: 6px;
  font-size: 1rem;
  font-weight: 800;
}

.impact-item {
  display: flex;
  gap: 9px;
  align-items: center;
  padding: 9px 0;
  border-bottom: 1px solid rgba(147, 197, 253, 0.12);
  font-size: 0.86rem;
}

.impact-item .symbol {
  min-width: 64px;
  font-weight: 800;
}

.impact-item .direction.positive { color: #6ee7b7; }
.impact-item .direction.negative { color: #fca5a5; }
.impact-item .direction.neutral { color: rgba(226, 239, 255, 0.7); }

.news-item {
  padding: 8px 0;
}

.news-item a {
  color: #67e8f9;
  text-decoration: none;
}

.news-item a:hover {
  text-decoration: underline;
}

.news-item .publisher {
  margin-left: 8px;
  color: rgba(226, 239, 255, 0.6);
  font-size: 0.76rem;
}

.empty-text {
  color: rgba(226, 239, 255, 0.62);
}

@media (max-width: 1180px) {
  .market-events-page {
    max-width: 980px;
    padding-right: 16px;
    padding-left: 16px;
  }

  .events-hero,
  .events-layout {
    grid-template-columns: 1fr;
  }

  .events-aside {
    position: static;
  }
}

@media (max-width: 760px) {
  .market-events-page {
    width: min(100% - 20px, 720px);
    padding-top: 18px;
  }

  .risk-summary {
    grid-template-columns: 1fr;
  }

  .events-toolbar,
  .event-title-line {
    flex-direction: column;
    align-items: stretch;
  }

  .detail-overlay {
    padding: 12px;
  }

  .detail-panel {
    width: min(100%, 680px);
    max-height: calc(100vh - 24px);
    padding: 22px;
  }

  .filters {
    justify-content: stretch;
  }

  .filters select,
  .filters input {
    width: 100%;
  }

  .event-row {
    grid-template-columns: 1fr;
  }

  .event-time {
    display: flex;
    gap: 8px;
    text-align: left;
  }

  .values-grid {
    grid-template-columns: 1fr;
  }
}
</style>
