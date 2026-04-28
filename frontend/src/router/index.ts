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
  ],
})

export default router
