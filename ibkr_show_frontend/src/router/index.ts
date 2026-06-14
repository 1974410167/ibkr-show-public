import { createRouter, createWebHistory } from 'vue-router'

import { fetchBootstrapStatus } from '@/api/bootstrap'
import { ensureAuthSession, useAuthSession } from '@/auth/session'

let bootstrapChecked = false
let systemInitialized = true

export function resetBootstrapStatusCache(): void {
  bootstrapChecked = false
  systemInitialized = true
}

async function ensureBootstrapStatus(): Promise<boolean> {
  if (bootstrapChecked) {
    return systemInitialized
  }
  try {
    const status = await fetchBootstrapStatus()
    systemInitialized = status.initialized
    bootstrapChecked = true
  } catch {
    // If the check fails (backend not ready), assume initialized to avoid
    // trapping the user on the bootstrap page with a broken backend.
    systemInitialized = true
  }
  return systemInitialized
}

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'dashboard',
      component: () => import('@/views/DashboardView.vue'),
    },
    {
      path: '/bootstrap',
      name: 'bootstrap',
      component: () => import('@/views/BootstrapView.vue'),
    },
    {
      path: '/positions',
      name: 'positions',
      component: () => import('@/views/PositionsView.vue'),
    },
    {
      path: '/trades',
      name: 'trades',
      component: () => import('@/views/TradesView.vue'),
      meta: {
        requiresAuth: true,
      },
    },
    {
      path: '/cash-flows',
      name: 'cash-flows',
      component: () => import('@/views/CashFlowsView.vue'),
      meta: {
        requiresAuth: true,
      },
    },
    {
      path: '/dividends',
      name: 'dividends',
      component: () => import('@/views/DividendsView.vue'),
      meta: {
        requiresAuth: true,
      },
    },
    {
      path: '/admin',
      redirect: '/admin/ibkr',
      meta: {
        requiresAuth: true,
      },
    },
    {
      path: '/agent/trade-decision',
      name: 'trade-decision-agent',
      component: () => import('@/views/TradeDecisionAgentView.vue'),
      meta: {
        requiresAuth: true,
      },
    },
    {
      path: '/agent/trade-review',
      name: 'trade-review-agent',
      component: () => import('@/views/TradeReviewAgentView.vue'),
      meta: {
        requiresAuth: true,
      },
    },
    {
      path: '/agent/account-copilot',
      name: 'account-copilot',
      component: () => import('@/views/AccountCopilotView.vue'),
      meta: {
        requiresAuth: true,
      },
    },
    {
      path: '/admin/llm',
      name: 'admin-llm',
      component: () => import('@/views/AdminLlmView.vue'),
      meta: {
        requiresAuth: true,
      },
    },
    {
      path: '/admin/ibkr',
      name: 'admin-ibkr',
      component: () => import('@/views/AdminIbkrView.vue'),
      meta: {
        requiresAuth: true,
      },
    },
    {
      path: '/admin/investment-policy',
      name: 'admin-investment-policy',
      component: () => import('@/views/AdminInvestmentPolicyView.vue'),
      meta: {
        requiresAuth: true,
      },
    },
    {
      path: '/admin/email',
      name: 'admin-email',
      component: () => import('@/views/AdminEmailView.vue'),
      meta: {
        requiresAuth: true,
      },
    },
    {
      path: '/admin/longbridge-mcp',
      name: 'admin-longbridge-mcp',
      component: () => import('@/views/AdminLongbridgeMcpView.vue'),
      meta: {
        requiresAuth: true,
      },
    },
    {
      path: '/admin/agent-monitoring',
      name: 'admin-agent-monitoring',
      component: () => import('@/views/AdminAgentMonitoringView.vue'),
      meta: {
        requiresAuth: true,
      },
    },
    {
      path: '/admin/prompts',
      name: 'admin-prompts',
      component: () => import('@/views/AdminPromptsView.vue'),
      meta: {
        requiresAuth: true,
      },
    },
    {
      path: '/admin/system',
      name: 'admin-system',
      component: () => import('@/views/AdminSystemView.vue'),
      meta: {
        requiresAuth: true,
      },
    },
    {
      path: '/admin/harness',
      name: 'admin-harness',
      component: () => import('@/views/AdminHarnessView.vue'),
      meta: {
        requiresAuth: true,
      },
    },
    {
      path: '/market-events',
      name: 'market-events',
      component: () => import('@/views/MarketEventsView.vue'),
    },
    {
      path: '/admin/market-events',
      name: 'admin-market-events',
      component: () => import('@/views/AdminMarketEventsView.vue'),
      meta: {
        requiresAuth: true,
      },
    },
  ],
})

router.beforeEach(async (to) => {
  // Bootstrap route: redirect to / if already initialized
  if (to.path === '/bootstrap') {
    const initialized = await ensureBootstrapStatus()
    if (initialized) {
      return { path: '/' }
    }
    return true
  }

  // Check bootstrap status; redirect to /bootstrap if not initialized
  const initialized = await ensureBootstrapStatus()
  if (!initialized) {
    return { path: '/bootstrap' }
  }

  // Normal auth check for protected routes
  if (!to.meta.requiresAuth) {
    return true
  }

  await ensureAuthSession()
  const { authState } = useAuthSession()
  if (authState.authenticated) {
    return true
  }

  return { path: '/' }
})

export default router
