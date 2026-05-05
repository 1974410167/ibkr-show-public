import { createRouter, createWebHistory } from 'vue-router'

import { ensureAuthSession, useAuthSession } from '@/auth/session'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'dashboard',
      component: () => import('@/views/DashboardView.vue'),
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
  ],
})

router.beforeEach(async (to) => {
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
