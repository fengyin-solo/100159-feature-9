<template>
  <section class="page" data-module="power">
    <header class="page-head">
      <div>
        <h2>供电保障管理</h2>
        <p class="page-desc">
          维护供电单元，围绕供电编号、所属站点、供电方式、蓄电池容量做登记、筛选与状态流转；备电时长低于
          {{ backupLimit }} 小时的供电单元会单独标为「备电不足」。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记供电单元</button>
        <button class="btn" type="button" @click="exportRows">导出供电保障清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="row in rows"
          :key="String(row.id)"
          :class="{ 'row-backup-low': row.status === '备电不足' }"
        >
          <td v-for="column in columns" :key="column">
            <span
              v-if="column === '供电状态'"
              class="status-tag"
              :class="{ 'status-danger': row.status === '备电不足' || row.status === '已断电' }"
            >{{ row[column] ?? '—' }}</span>
            <span v-else-if="column === '备电时长'" :class="{ 'error-text': isBackupLow(row) }">
              {{ row[column] ?? '—' }}
            </span>
            <template v-else>{{ row[column] ?? '—' }}</template>
          </td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
            <button class="link" type="button" @click="openDetail(row)">详情</button>
          </td>
        </tr>
        <tr v-if="!rows.length && !errorMessage">
          <td :colspan="columns.length + 1" class="empty-state">{{ emptyText }}</td>
        </tr>
      </tbody>
    </table>

    <div v-if="errorMessage" class="error-bar">
      <span class="error-text">{{ errorMessage }}</span>
      <button class="btn" type="button" @click="retry">重试</button>
    </div>

    <footer class="page-foot">
      <span>共 {{ total }} 条供电保障记录，其中备电不足 {{ shortCount }} 条</span>
      <span v-if="actionMessage">{{ actionMessage }}</span>
    </footer>

    <div v-if="showCreate" class="dialog-mask">
      <form class="dialog" @submit.prevent="saveCreate">
        <h3 class="dialog-title">登记供电单元</h3>
        <label v-for="field in createFields" :key="field" class="dialog-item">
          <span>
            {{ field }}
            <em v-if="requiredCreateFields.includes(field)" class="error-text">*</em>
          </span>
          <input v-model="createForm[field]" :placeholder="`请输入${field}`" />
        </label>
        <p v-if="createError" class="error-text dialog-error">{{ createError }}</p>
        <div class="dialog-actions">
          <button class="btn primary" type="submit">保存</button>
          <button class="btn ghost" type="button" @click="closeCreate">取消</button>
        </div>
      </form>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/power'
const columns = ["供电编号", "所属站点", "供电方式", "蓄电池容量", "上次放电测试", "备电时长", "责任人员", "供电状态"]
const actions = ["安排巡检", "确认正常", "标记断电"]
const filterFields = columns.slice(0, 3)
const createFields = ["供电编号", "所属站点", "供电方式", "蓄电池容量", "上次放电测试", "备电时长", "责任人员", "最近巡检结论"]
const requiredCreateFields = ["供电编号", "所属站点", "供电方式", "备电时长"]

const router = useRouter()

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const actionMessage = ref('')
const filters = ref<Record<string, string>>({})
const lastQuery = ref('')
const backupLimit = ref(4)
const stats = ref([
  { label: '在册供电单元', value: 0 },
  { label: '备电不足', value: 0 },
  { label: '已断电站点', value: 0 },
])

const showCreate = ref(false)
const createForm = ref<Record<string, string>>({})
const createError = ref('')

const shortCount = computed(() => stats.value[1]?.value ?? 0)

const emptyText = computed(() => {
  const station = (filters.value['所属站点'] ?? '').trim()
  if (station) {
    return `站点「${station}」暂无备电数据，可确认站点名称或先登记供电单元`
  }
  const hasFilter = Object.values(filters.value).some((value) => value && value.trim())
  if (hasFilter) {
    return '当前查询条件下暂无供电保障记录，可调整条件后重新查询'
  }
  return '暂无供电保障数据，可先登记供电单元'
})

function isBackupLow(row: Row) {
  const hours = parseFloat(String(row['备电时长'] ?? ''))
  return !Number.isNaN(hours) && hours < backupLimit.value
}

function buildQuery() {
  const params = new URLSearchParams()
  for (const field of filterFields) {
    const value = (filters.value[field] ?? '').trim()
    if (value) {
      params.set(field, value)
    }
  }
  return params.toString()
}

async function fetchList(query: string) {
  errorMessage.value = ''
  try {
    const [listResponse, summaryResponse] = await Promise.all([
      request(`${ENDPOINT}?${query}`),
      request(`${ENDPOINT}/summary`),
    ])
    if (!listResponse.ok) {
      throw new Error(`供电单元列表读取失败（${listResponse.status}）`)
    }
    const payload = await listResponse.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    if (summaryResponse.ok) {
      const summary = await summaryResponse.json()
      backupLimit.value = Number(summary['备电时长下限'] ?? 4)
      stats.value = [
        { label: '在册供电单元', value: summary['在册供电单元'] ?? 0 },
        { label: '备电不足', value: summary['备电不足'] ?? 0 },
        { label: '已断电站点', value: summary['已断电站点'] ?? 0 },
      ]
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '供电保障列表读取失败'
  }
}

function reload() {
  lastQuery.value = buildQuery()
  return fetchList(lastQuery.value)
}

function retry() {
  // 查询失败后重试：沿用上一次的查询条件，不清空用户输入
  return fetchList(lastQuery.value)
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openDetail(row: Row) {
  void router.push(`/power/${row.id}`)
}

function openCreate() {
  createForm.value = {}
  createError.value = ''
  showCreate.value = true
}

function closeCreate() {
  showCreate.value = false
}

async function saveCreate() {
  const missing = requiredCreateFields.filter((field) => !(createForm.value[field] ?? '').trim())
  if (missing.length) {
    createError.value = `不允许保存：${missing.join('、')}未填写，请补充后再保存`
    return
  }
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: { ...createForm.value } }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      createError.value = payload.message ?? payload.detail ?? '保存失败，请稍后重试'
      return
    }
    showCreate.value = false
    actionMessage.value = payload.message ?? ''
    await reload()
  } catch (error) {
    createError.value = error instanceof Error ? error.message : '保存失败，请稍后重试'
  }
}

async function runAction(action: string, row: Row) {
  actionMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message ?? '供电保障动作未生效，请稍后重试')
    }
    actionMessage.value = payload.message ?? ''
    await fetchList(lastQuery.value)
  } catch (error) {
    actionMessage.value = error instanceof Error ? error.message : '供电保障操作失败'
  }
}

onMounted(reload)
</script>
