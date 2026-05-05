import { readonly, ref } from 'vue'

import { fetchAccountOverview } from '@/api/account'
import type { AccountOverview } from '@/types/account'

const overview = ref<AccountOverview | null>(null)
const loading = ref(false)
const errorMessage = ref('')

let pendingRequest: Promise<AccountOverview | null> | null = null
let refreshTimer: number | null = null
let refreshSubscribers = 0

async function loadOverview(force = false): Promise<AccountOverview | null> {
  if (pendingRequest && !force) {
    return pendingRequest
  }
  if (overview.value && !force) {
    return overview.value
  }

  pendingRequest = (async () => {
    loading.value = true
    errorMessage.value = ''
    try {
      const response = await fetchAccountOverview()
      overview.value = response
      return response
    } catch (error) {
      errorMessage.value = error instanceof Error ? error.message : '加载账户总览失败'
      return overview.value
    } finally {
      loading.value = false
      pendingRequest = null
    }
  })()

  return pendingRequest
}

function startAutoRefresh(): void {
  refreshSubscribers += 1
  if (refreshTimer !== null) {
    return
  }

  refreshTimer = window.setInterval(() => {
    void loadOverview(true)
  }, 30000)
}

function stopAutoRefresh(): void {
  refreshSubscribers = Math.max(0, refreshSubscribers - 1)
  if (refreshSubscribers > 0 || refreshTimer === null) {
    return
  }

  window.clearInterval(refreshTimer)
  refreshTimer = null
}

export function useAccountOverviewData() {
  return {
    overview: readonly(overview),
    loading: readonly(loading),
    errorMessage: readonly(errorMessage),
    ensureLoaded: loadOverview,
    refresh: () => loadOverview(true),
    startAutoRefresh,
    stopAutoRefresh,
  }
}
