import { createApp } from 'vue'
import { createPinia } from 'pinia'
import {
  ElAlert,
  ElButton,
  ElConfigProvider,
  ElDatePicker,
  ElDialog,
  ElDivider,
  ElForm,
  ElFormItem,
  ElIcon,
  ElInput,
  ElInputNumber,
  ElOption,
  ElProgress,
  ElRadio,
  ElRadioButton,
  ElRadioGroup,
  ElSelect,
  ElSlider,
  ElSwitch,
  ElTable,
  ElTableColumn,
  ElTag,
  vLoading,
} from 'element-plus'
import {
  ArrowLeft,
  Clock,
  DataAnalysis,
  Delete,
  Hide,
  Refresh,
  Setting,
  View,
} from '@element-plus/icons-vue'
import 'element-plus/dist/index.css'
import './styles/index.css'
import App from './App.vue'
import router from './router'

const app = createApp(App)
const pinia = createPinia()
const elementPlusComponents = [
  ElAlert,
  ElButton,
  ElConfigProvider,
  ElDatePicker,
  ElDialog,
  ElDivider,
  ElForm,
  ElFormItem,
  ElIcon,
  ElInput,
  ElInputNumber,
  ElOption,
  ElProgress,
  ElRadio,
  ElRadioButton,
  ElRadioGroup,
  ElSelect,
  ElSlider,
  ElSwitch,
  ElTable,
  ElTableColumn,
  ElTag,
]

app.use(pinia)
app.use(router)

for (const component of elementPlusComponents) {
  app.use(component)
}

app.directive('loading', vLoading)

app.component('ArrowLeft', ArrowLeft)
app.component('Clock', Clock)
app.component('DataAnalysis', DataAnalysis)
app.component('Delete', Delete)
app.component('Hide', Hide)
app.component('Refresh', Refresh)
app.component('Setting', Setting)
app.component('View', View)

app.mount('#app')
