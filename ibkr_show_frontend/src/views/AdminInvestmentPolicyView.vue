<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import Button from 'primevue/button'
import InputText from 'primevue/inputtext'
import Tag from 'primevue/tag'

import {
  disableSymbolInvestmentPolicy,
  fetchGlobalInvestmentPolicy,
  fetchSymbolInvestmentPolicies,
  seedDefaultInvestmentPolicies,
  updateGlobalInvestmentPolicy,
  updateSymbolInvestmentPolicy,
} from '@/api/investmentPolicy'
import ErrorBlock from '@/components/ErrorBlock.vue'
import LoadingBlock from '@/components/LoadingBlock.vue'
import type {
  AddStyle,
  AssetRole,
  Conviction,
  GlobalInvestmentPolicy,
  GlobalInvestmentPolicyPayload,
  RiskProfile,
  SymbolInvestmentPolicy,
  SymbolInvestmentPolicyPayload,
} from '@/types/investmentPolicy'

type PolicyTab = 'global' | 'symbols'

const router = useRouter()
const activeTab = ref<PolicyTab>('global')
const loading = ref(true)
const saving = ref(false)
const seeding = ref(false)
const disablingSymbol = ref('')
const errorMessage = ref('')
const noticeMessage = ref('')
const globalPolicy = ref<GlobalInvestmentPolicy | null>(null)
const symbolPolicies = ref<SymbolInvestmentPolicy[]>([])
const showSymbolForm = ref(false)
const editingOriginalSymbol = ref('')

const riskProfiles: RiskProfile[] = ['conservative', 'balanced', 'aggressive_growth']
const addStyles: AddStyle[] = ['left_side_add', 'pullback_add', 'right_side_confirm', 'batch_add']
const assetRoles: AssetRole[] = [
  'core_growth',
  'faith_holding',
  'satellite_growth',
  'speculative',
  'btc_proxy',
  'cash_like',
  'index_etf',
  'watchlist',
  'forbidden',
  'unknown',
]
const convictions: Conviction[] = ['high', 'medium', 'low']

const globalForm = reactive({
  risk_profile: 'balanced' as RiskProfile,
  target_annual_return_pct: 20,
  max_drawdown_tolerance_pct: 25,
  allow_concentrated_position: true,
  allow_single_position_over_20_pct: true,
  allow_leverage: false,
  cash_reserve_pct: 5,
  preferred_add_styles: ['pullback_add', 'batch_add'] as AddStyle[],
  preferred_sell_style: '',
  holding_period: '',
  notes: '',
  enabled: true,
})

const symbolForm = reactive({
  symbol: '',
  asset_role: 'unknown' as AssetRole,
  conviction: 'medium' as Conviction,
  user_preferred_min_position_pct: 0,
  user_preferred_target_position_pct: 0,
  user_preferred_max_position_pct: 5,
  add_rules: '',
  no_add_triggers: '',
  sell_triggers: '',
  hard_constraints: '',
  soft_preferences: '',
  notes: '',
  enabled: true,
})

const enabledSymbolCount = computed(() => symbolPolicies.value.filter((item) => item.enabled).length)

function percentToDisplay(value: number | null | undefined): number {
  if (value === null || value === undefined) return 0
  return Number((value * 100).toFixed(4))
}

function displayToPercent(value: number | null | undefined): number | null {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return null
  return Number(value) / 100
}

function linesToList(value: string): string[] {
  return value
    .split('\n')
    .map((item) => item.trim())
    .filter(Boolean)
}

function listToLines(value: string[]): string {
  return value.join('\n')
}

function formatPercent(value: number | null): string {
  if (value === null) return '--'
  return `${(value * 100).toFixed(value * 100 >= 10 ? 1 : 2)}%`
}

function formatDateTime(value: string): string {
  if (!value) return '--'
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

function applyGlobalPolicy(policy: GlobalInvestmentPolicy): void {
  globalPolicy.value = policy
  globalForm.risk_profile = policy.risk_profile
  globalForm.target_annual_return_pct = percentToDisplay(policy.target_annual_return_pct)
  globalForm.max_drawdown_tolerance_pct = percentToDisplay(policy.max_drawdown_tolerance_pct)
  globalForm.allow_concentrated_position = policy.allow_concentrated_position
  globalForm.allow_single_position_over_20_pct = policy.allow_single_position_over_20_pct
  globalForm.allow_leverage = policy.allow_leverage
  globalForm.cash_reserve_pct = percentToDisplay(policy.cash_reserve_pct)
  globalForm.preferred_add_styles = [...policy.preferred_add_styles]
  globalForm.preferred_sell_style = policy.preferred_sell_style
  globalForm.holding_period = policy.holding_period
  globalForm.notes = policy.notes
  globalForm.enabled = policy.enabled
}

async function loadData(): Promise<void> {
  loading.value = true
  errorMessage.value = ''
  try {
    const [global, symbols] = await Promise.all([
      fetchGlobalInvestmentPolicy(),
      fetchSymbolInvestmentPolicies(true),
    ])
    applyGlobalPolicy(global)
    symbolPolicies.value = symbols
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '加载投资策略配置失败'
  } finally {
    loading.value = false
  }
}

function toggleAddStyle(style: AddStyle): void {
  if (globalForm.preferred_add_styles.includes(style)) {
    globalForm.preferred_add_styles = globalForm.preferred_add_styles.filter((item) => item !== style)
  } else {
    globalForm.preferred_add_styles = [...globalForm.preferred_add_styles, style]
  }
}

async function saveGlobalPolicy(): Promise<void> {
  saving.value = true
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const payload: GlobalInvestmentPolicyPayload = {
      risk_profile: globalForm.risk_profile,
      target_annual_return_pct: displayToPercent(globalForm.target_annual_return_pct),
      max_drawdown_tolerance_pct: displayToPercent(globalForm.max_drawdown_tolerance_pct),
      allow_concentrated_position: globalForm.allow_concentrated_position,
      allow_single_position_over_20_pct: globalForm.allow_single_position_over_20_pct,
      allow_leverage: globalForm.allow_leverage,
      cash_reserve_pct: displayToPercent(globalForm.cash_reserve_pct),
      preferred_add_styles: globalForm.preferred_add_styles,
      preferred_sell_style: globalForm.preferred_sell_style.trim(),
      holding_period: globalForm.holding_period.trim(),
      notes: globalForm.notes.trim(),
      enabled: globalForm.enabled,
    }
    applyGlobalPolicy(await updateGlobalInvestmentPolicy(payload))
    noticeMessage.value = '交易风格配置已保存'
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '保存交易风格失败'
  } finally {
    saving.value = false
  }
}

function resetSymbolForm(): void {
  editingOriginalSymbol.value = ''
  symbolForm.symbol = ''
  symbolForm.asset_role = 'unknown'
  symbolForm.conviction = 'medium'
  symbolForm.user_preferred_min_position_pct = 0
  symbolForm.user_preferred_target_position_pct = 0
  symbolForm.user_preferred_max_position_pct = 5
  symbolForm.add_rules = ''
  symbolForm.no_add_triggers = ''
  symbolForm.sell_triggers = ''
  symbolForm.hard_constraints = ''
  symbolForm.soft_preferences = ''
  symbolForm.notes = ''
  symbolForm.enabled = true
}

function openCreateSymbolForm(): void {
  resetSymbolForm()
  showSymbolForm.value = true
}

function openEditSymbolForm(policy: SymbolInvestmentPolicy): void {
  editingOriginalSymbol.value = policy.symbol
  symbolForm.symbol = policy.symbol
  symbolForm.asset_role = policy.asset_role
  symbolForm.conviction = policy.conviction
  symbolForm.user_preferred_min_position_pct = percentToDisplay(policy.user_preferred_min_position_pct)
  symbolForm.user_preferred_target_position_pct = percentToDisplay(policy.user_preferred_target_position_pct)
  symbolForm.user_preferred_max_position_pct = percentToDisplay(policy.user_preferred_max_position_pct)
  symbolForm.add_rules = listToLines(policy.add_rules)
  symbolForm.no_add_triggers = listToLines(policy.no_add_triggers)
  symbolForm.sell_triggers = listToLines(policy.sell_triggers)
  symbolForm.hard_constraints = listToLines(policy.hard_constraints)
  symbolForm.soft_preferences = listToLines(policy.soft_preferences)
  symbolForm.notes = policy.notes
  symbolForm.enabled = policy.enabled
  showSymbolForm.value = true
}

function closeSymbolForm(): void {
  showSymbolForm.value = false
}

async function saveSymbolPolicy(): Promise<void> {
  saving.value = true
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const symbol = (editingOriginalSymbol.value || symbolForm.symbol).trim().toUpperCase()
    const payload: SymbolInvestmentPolicyPayload = {
      symbol: symbolForm.symbol.trim().toUpperCase(),
      asset_role: symbolForm.asset_role,
      conviction: symbolForm.conviction,
      user_preferred_min_position_pct: displayToPercent(symbolForm.user_preferred_min_position_pct) ?? 0,
      user_preferred_target_position_pct: displayToPercent(symbolForm.user_preferred_target_position_pct),
      user_preferred_max_position_pct: displayToPercent(symbolForm.user_preferred_max_position_pct) ?? 0,
      add_rules: linesToList(symbolForm.add_rules),
      no_add_triggers: linesToList(symbolForm.no_add_triggers),
      sell_triggers: linesToList(symbolForm.sell_triggers),
      hard_constraints: linesToList(symbolForm.hard_constraints),
      soft_preferences: linesToList(symbolForm.soft_preferences),
      notes: symbolForm.notes.trim(),
      enabled: symbolForm.enabled,
      ai_review_status: 'unknown',
    }
    const saved = await updateSymbolInvestmentPolicy(symbol, payload)
    const others = symbolPolicies.value.filter((item) => item.symbol !== saved.symbol)
    symbolPolicies.value = [...others, saved].sort((a, b) => a.symbol.localeCompare(b.symbol))
    noticeMessage.value = `${saved.symbol} 配置已保存`
    closeSymbolForm()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '保存股票定位失败'
  } finally {
    saving.value = false
  }
}

async function disablePolicy(policy: SymbolInvestmentPolicy): Promise<void> {
  disablingSymbol.value = policy.symbol
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const disabled = await disableSymbolInvestmentPolicy(policy.symbol)
    symbolPolicies.value = symbolPolicies.value.map((item) => (item.symbol === disabled.symbol ? disabled : item))
    noticeMessage.value = `${disabled.symbol} 已禁用`
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '禁用股票定位失败'
  } finally {
    disablingSymbol.value = ''
  }
}

async function seedDefaults(): Promise<void> {
  seeding.value = true
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const result = await seedDefaultInvestmentPolicies(false)
    symbolPolicies.value = await fetchSymbolInvestmentPolicies(true)
    noticeMessage.value = result.message
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '初始化默认模板失败'
  } finally {
    seeding.value = false
  }
}

onMounted(() => {
  void loadData()
})
</script>

<template>
  <section class="page-section admin-investment-policy-page">
    <section class="surface-panel">
      <div class="surface-panel__content">
        <div class="section-header admin-investment-policy-page__header">
          <div>
            <p class="eyebrow">ADMIN</p>
            <h2 class="panel-title admin-investment-policy-page__title">投资策略配置</h2>
            <p class="panel-subtitle">维护全局交易风格和单股票账户定位偏好，供后续交易决策 Agent 读取并重新评估。</p>
          </div>
          <Tag :value="`${enabledSymbolCount} ENABLED`" class="p-tag--accent" />
        </div>

        <nav class="admin-tabs">
          <Button label="LLM 配置" icon="pi pi-sparkles" class="terminal-nav__button" @click="router.push('/admin/llm')" />
          <Button label="IBKR 数据源" icon="pi pi-database" class="terminal-nav__button" @click="router.push('/admin/ibkr')" />
          <Button label="投资策略" icon="pi pi-sliders-h" class="terminal-nav__button is-active" />
          <Button label="邮件配置" icon="pi pi-envelope" class="terminal-nav__button" @click="router.push('/admin/email')" />
          <Button label="Longbridge MCP" icon="pi pi-link" class="terminal-nav__button" @click="router.push('/admin/longbridge-mcp')" />
          <Button label="宏观数据源" icon="pi pi-calendar-clock" class="terminal-nav__button" @click="router.push('/admin/market-events')" />
          <Button label="系统状态" icon="pi pi-heart" class="terminal-nav__button" @click="router.push('/admin/system')" />
          <Button label="Agent 监控" icon="pi pi-chart-line" class="terminal-nav__button" @click="router.push('/admin/agent-monitoring')" />
          <Button label="Prompt 管理" icon="pi pi-file-edit" class="terminal-nav__button" @click="router.push('/admin/prompts')" />
          <Button label="Harness 控制台" icon="pi pi-sitemap" class="terminal-nav__button" @click="router.push('/admin/harness')" />
        </nav>
      </div>
    </section>

    <LoadingBlock v-if="loading" />
    <ErrorBlock v-else-if="errorMessage" :message="errorMessage" />

    <template v-else>
      <p v-if="noticeMessage" class="admin-notice">{{ noticeMessage }}</p>

      <section class="surface-panel">
        <div class="surface-panel__content">
          <div class="policy-local-tabs">
            <Button label="我的交易风格" icon="pi pi-user-edit" class="terminal-nav__button" :class="{ 'is-active': activeTab === 'global' }" @click="activeTab = 'global'" />
            <Button label="股票定位配置" icon="pi pi-tags" class="terminal-nav__button" :class="{ 'is-active': activeTab === 'symbols' }" @click="activeTab = 'symbols'" />
          </div>
        </div>
      </section>

      <section v-if="activeTab === 'global'" class="admin-layout">
        <section class="surface-panel">
          <div class="surface-panel__content">
            <div class="section-header">
              <div>
                <h3 class="panel-title">我的交易风格</h3>
                <p class="panel-subtitle">百分比字段以 20 表示 20%，后端保存为 0.2。</p>
              </div>
              <Tag :value="globalForm.enabled ? 'ENABLED' : 'DISABLED'" :class="globalForm.enabled ? 'p-tag--positive' : 'p-tag--negative'" />
            </div>

            <form class="policy-form" @submit.prevent="saveGlobalPolicy">
              <label class="field-stack">
                <span class="field-stack__label">风险偏好</span>
                <select v-model="globalForm.risk_profile" class="admin-select">
                  <option v-for="item in riskProfiles" :key="item" :value="item">{{ item }}</option>
                </select>
              </label>
              <label class="field-stack">
                <span class="field-stack__label">目标年化收益 %</span>
                <input v-model.number="globalForm.target_annual_return_pct" class="admin-input" type="number" min="0" step="0.1" />
              </label>
              <label class="field-stack">
                <span class="field-stack__label">最大回撤容忍 %</span>
                <input v-model.number="globalForm.max_drawdown_tolerance_pct" class="admin-input" type="number" min="0" max="100" step="0.1" />
              </label>
              <label class="field-stack">
                <span class="field-stack__label">现金保留 %</span>
                <input v-model.number="globalForm.cash_reserve_pct" class="admin-input" type="number" min="0" max="100" step="0.1" />
              </label>
              <label class="field-stack">
                <span class="field-stack__label">卖出风格</span>
                <InputText v-model="globalForm.preferred_sell_style" />
              </label>
              <label class="field-stack">
                <span class="field-stack__label">持有周期</span>
                <InputText v-model="globalForm.holding_period" />
              </label>

              <div class="field-stack field-stack--wide">
                <span class="field-stack__label">偏好的加仓方式</span>
                <div class="policy-check-grid">
                  <label v-for="style in addStyles" :key="style" class="policy-check">
                    <input type="checkbox" :checked="globalForm.preferred_add_styles.includes(style)" @change="toggleAddStyle(style)" />
                    <span>{{ style }}</span>
                  </label>
                </div>
              </div>

              <div class="field-stack field-stack--wide">
                <span class="field-stack__label">风险开关</span>
                <div class="policy-check-grid">
                  <label class="policy-check"><input v-model="globalForm.allow_concentrated_position" type="checkbox" />允许集中持仓</label>
                  <label class="policy-check"><input v-model="globalForm.allow_single_position_over_20_pct" type="checkbox" />允许单股超过 20%</label>
                  <label class="policy-check"><input v-model="globalForm.allow_leverage" type="checkbox" />允许杠杆</label>
                  <label class="policy-check"><input v-model="globalForm.enabled" type="checkbox" />启用配置</label>
                </div>
              </div>

              <label class="field-stack field-stack--wide">
                <span class="field-stack__label">备注</span>
                <textarea v-model="globalForm.notes" class="admin-textarea" rows="4"></textarea>
              </label>

              <div class="admin-form-actions field-stack--wide">
                <Button label="保存交易风格" icon="pi pi-save" type="submit" class="p-button p-button--accent" :loading="saving" />
              </div>
            </form>
          </div>
        </section>

        <section class="surface-panel">
          <div class="surface-panel__content">
            <h3 class="panel-title">当前摘要</h3>
            <dl class="policy-summary">
              <div><dt>风险偏好</dt><dd>{{ globalPolicy?.risk_profile }}</dd></div>
              <div><dt>目标年化</dt><dd>{{ formatPercent(globalPolicy?.target_annual_return_pct ?? null) }}</dd></div>
              <div><dt>回撤容忍</dt><dd>{{ formatPercent(globalPolicy?.max_drawdown_tolerance_pct ?? null) }}</dd></div>
              <div><dt>现金保留</dt><dd>{{ formatPercent(globalPolicy?.cash_reserve_pct ?? null) }}</dd></div>
              <div><dt>加仓方式</dt><dd>{{ globalPolicy?.preferred_add_styles.join(', ') || '--' }}</dd></div>
              <div><dt>更新时间</dt><dd>{{ formatDateTime(globalPolicy?.updated_at ?? '') }}</dd></div>
            </dl>
          </div>
        </section>
      </section>

      <section v-else class="surface-panel">
        <div class="surface-panel__content">
          <div class="section-header">
            <div>
              <h3 class="panel-title">股票定位配置</h3>
              <p class="panel-subtitle">新增、编辑或禁用单股票投资定位偏好；这是你的主观偏好，不是 AI 最终建议。</p>
            </div>
            <div class="admin-form-actions">
              <Button label="从默认模板初始化" icon="pi pi-download" class="p-button p-button--ghost" :loading="seeding" @click="seedDefaults" />
              <Button label="新增股票" icon="pi pi-plus" class="p-button p-button--accent" @click="openCreateSymbolForm" />
            </div>
          </div>

          <div class="policy-table-wrap">
            <table class="policy-table">
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Asset Role</th>
                  <th>Conviction</th>
                  <th>我偏好的目标</th>
                  <th>我能接受的最大</th>
                  <th>Enabled</th>
                  <th>Updated</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="policy in symbolPolicies" :key="policy.symbol" :class="{ 'is-disabled': !policy.enabled }">
                  <td><strong>{{ policy.symbol }}</strong></td>
                  <td>{{ policy.asset_role }}</td>
                  <td>{{ policy.conviction }}</td>
                  <td>{{ formatPercent(policy.user_preferred_target_position_pct) }}</td>
                  <td>{{ formatPercent(policy.user_preferred_max_position_pct) }}</td>
                  <td>
                    <Tag :value="policy.enabled ? 'YES' : 'NO'" :class="policy.enabled ? 'p-tag--positive' : 'p-tag--negative'" />
                  </td>
                  <td>{{ formatDateTime(policy.updated_at) }}</td>
                  <td class="policy-table__actions">
                    <Button label="编辑" icon="pi pi-pencil" class="p-button p-button--ghost" @click="openEditSymbolForm(policy)" />
                    <Button label="禁用" icon="pi pi-ban" class="p-button p-button--ghost" :disabled="!policy.enabled" :loading="disablingSymbol === policy.symbol" @click="disablePolicy(policy)" />
                  </td>
                </tr>
                <tr v-if="symbolPolicies.length === 0">
                  <td colspan="8" class="empty-state">暂无股票定位配置</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </section>
    </template>

    <div v-if="showSymbolForm" class="policy-dialog-backdrop" @click.self="closeSymbolForm">
      <section class="surface-panel policy-dialog">
        <div class="surface-panel__content">
          <div class="section-header">
            <div>
              <p class="eyebrow">SYMBOL POLICY</p>
              <h3 class="panel-title">{{ editingOriginalSymbol ? `编辑 ${editingOriginalSymbol}` : '新增股票定位' }}</h3>
            </div>
            <Button icon="pi pi-times" class="p-button p-button--ghost" aria-label="关闭" @click="closeSymbolForm" />
          </div>

          <form class="policy-form" @submit.prevent="saveSymbolPolicy">
            <label class="field-stack">
              <span class="field-stack__label">Symbol</span>
              <InputText v-model="symbolForm.symbol" required placeholder="AMD 或 AMD.US" />
            </label>
            <label class="field-stack">
              <span class="field-stack__label">Asset Role</span>
              <select v-model="symbolForm.asset_role" class="admin-select">
                <option v-for="item in assetRoles" :key="item" :value="item">{{ item }}</option>
              </select>
            </label>
            <label class="field-stack">
              <span class="field-stack__label">Conviction</span>
              <select v-model="symbolForm.conviction" class="admin-select">
                <option v-for="item in convictions" :key="item" :value="item">{{ item }}</option>
              </select>
            </label>
            <label class="field-stack">
              <span class="field-stack__label">我希望保留的最低仓位 %</span>
              <input v-model.number="symbolForm.user_preferred_min_position_pct" class="admin-input" type="number" min="0" max="100" step="0.1" />
            </label>
            <label class="field-stack">
              <span class="field-stack__label">我偏好的目标仓位 %</span>
              <input v-model.number="symbolForm.user_preferred_target_position_pct" class="admin-input" type="number" min="0" max="100" step="0.1" />
            </label>
            <label class="field-stack">
              <span class="field-stack__label">我能接受的最大仓位 %</span>
              <input v-model.number="symbolForm.user_preferred_max_position_pct" class="admin-input" type="number" min="0" max="100" step="0.1" />
            </label>
            <p class="policy-disclaimer field-stack--wide">
              这是你的主观偏好，不是 AI 最终建议。交易决策会读取该偏好，但会基于市场数据重新评估，必要时反驳。
            </p>

            <label class="field-stack field-stack--wide">
              <span class="field-stack__label">Add Rules</span>
              <textarea v-model="symbolForm.add_rules" class="admin-textarea" rows="3" placeholder="每行一条"></textarea>
            </label>
            <label class="field-stack field-stack--wide">
              <span class="field-stack__label">No Add Triggers</span>
              <textarea v-model="symbolForm.no_add_triggers" class="admin-textarea" rows="3" placeholder="每行一条"></textarea>
            </label>
            <label class="field-stack field-stack--wide">
              <span class="field-stack__label">Sell Triggers</span>
              <textarea v-model="symbolForm.sell_triggers" class="admin-textarea" rows="3" placeholder="每行一条"></textarea>
            </label>
            <label class="field-stack field-stack--wide">
              <span class="field-stack__label">Hard Constraints</span>
              <textarea v-model="symbolForm.hard_constraints" class="admin-textarea" rows="3" placeholder="每行一条"></textarea>
            </label>
            <label class="field-stack field-stack--wide">
              <span class="field-stack__label">Soft Preferences</span>
              <textarea v-model="symbolForm.soft_preferences" class="admin-textarea" rows="3" placeholder="每行一条"></textarea>
            </label>
            <label class="field-stack field-stack--wide">
              <span class="field-stack__label">Notes</span>
              <textarea v-model="symbolForm.notes" class="admin-textarea" rows="4"></textarea>
            </label>
            <label class="policy-check field-stack--wide">
              <input v-model="symbolForm.enabled" type="checkbox" />
              <span>启用该股票定位</span>
            </label>

            <div class="admin-form-actions field-stack--wide">
              <Button label="保存" icon="pi pi-save" type="submit" class="p-button p-button--accent" :loading="saving" />
              <Button label="取消" type="button" class="p-button p-button--ghost" @click="closeSymbolForm" />
            </div>
          </form>
        </div>
      </section>
    </div>
  </section>
</template>

<style scoped>
.admin-investment-policy-page__header,
.policy-local-tabs,
.admin-form-actions,
.policy-table__actions,
.policy-check-grid {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
}

.admin-investment-policy-page__title {
  margin: 0;
}

.admin-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 18px;
}

.admin-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) minmax(280px, 0.6fr);
  gap: 16px;
}

.policy-form {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.field-stack--wide {
  grid-column: 1 / -1;
}

.admin-input,
.admin-textarea,
.admin-select {
  width: 100%;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  background: var(--color-surface-muted);
  color: var(--color-text-primary);
  padding: 10px 12px;
  font: inherit;
}

.admin-textarea {
  min-height: 92px;
  resize: vertical;
}

.admin-notice {
  border: 1px solid var(--color-border);
  border-radius: 8px;
  padding: 10px 12px;
  color: var(--color-text-primary);
  background: var(--color-surface-muted);
}

.policy-check {
  display: inline-flex;
  gap: 8px;
  align-items: center;
  color: var(--color-text-primary);
}

.policy-disclaimer {
  margin: 0;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  padding: 10px 12px;
  color: var(--color-text-secondary);
  background: var(--color-surface-muted);
}

.policy-summary {
  display: grid;
  gap: 12px;
  margin: 0;
}

.policy-summary div {
  border-bottom: 1px solid var(--color-border);
  padding-bottom: 10px;
}

.policy-summary dt {
  color: var(--color-text-secondary);
  font-size: 0.8rem;
}

.policy-summary dd {
  margin: 4px 0 0;
  color: var(--color-text-primary);
  font-weight: 700;
  overflow-wrap: anywhere;
}

.policy-table-wrap {
  overflow-x: auto;
}

.policy-table {
  width: 100%;
  border-collapse: collapse;
  min-width: 920px;
}

.policy-table th,
.policy-table td {
  border-bottom: 1px solid var(--color-border);
  padding: 10px 8px;
  text-align: left;
  vertical-align: middle;
}

.policy-table th {
  color: var(--color-text-secondary);
  font-size: 0.78rem;
  text-transform: uppercase;
}

.policy-table tr.is-disabled {
  opacity: 0.58;
}

.policy-dialog-backdrop {
  position: fixed;
  inset: 0;
  z-index: 50;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  overflow: auto;
  padding: 40px 16px;
  background: rgb(0 0 0 / 0.45);
}

.policy-dialog {
  width: min(920px, 100%);
}

@media (max-width: 900px) {
  .admin-layout,
  .policy-form {
    grid-template-columns: 1fr;
  }
}
</style>
