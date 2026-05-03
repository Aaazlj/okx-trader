import { createRouter, createWebHistory } from 'vue-router'
import Dashboard from '../views/Dashboard.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'dashboard',
      component: Dashboard,
    },
    {
      path: '/strategy/:id',
      name: 'strategy-detail',
      component: () => import('../views/StrategyDetail.vue'),
    },
    {
      path: '/analysis',
      name: 'perpetual-analysis',
      component: () => import('../views/PerpetualAnalysis.vue'),
    },
    {
      path: '/analysis/history',
      name: 'perpetual-analysis-history',
      component: () => import('../views/PerpetualAnalysisHistory.vue'),
    },
    {
      path: '/analysis/history/:id',
      name: 'perpetual-analysis-history-detail',
      component: () => import('../views/PerpetualAnalysisHistoryDetail.vue'),
    },
    {
      path: '/settings',
      name: 'settings',
      component: () => import('../views/Settings.vue'),
    },
  ],
})

export default router
