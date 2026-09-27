<template>
  <section class="page" data-module="power">
    <header class="page-head">
      <div>
        <h2>供电保障管理</h2>
        <p class="page-desc">
          备电时长低于 {{ backupMin }} 小时的供电单元单独标记；断电前后都可查到最近一次放电测试、责任人员与巡检结论。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记供电单元</button>
        <button class="btn" type="button" @click="exportRows">导出供电保障清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in statCards" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value" :class="{ 'stat-warn': item.warn }">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="applyFilters">
      <label class="filter-item">
        <span>供电编号</span>
        <input v-model="filters.keyword" placeholder="按供电编号检索" />
      </label>
      <label class="filter-item">
        <span>供电状态</span>
        <select v-model="filters.status">
          <option value="">全部状态</option>
          <option v-for="s in statuses" :key="s" :value="s">{{ s }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <div v-if="errorMessage" class="error-banner">
      <span>{{ errorMessage }}</span>
      <button class="btn" type="button" @click="reload">重试</button>
    </div>

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
          :class="{ 'row-low': row.备电不足 }"
          @click="openDetail(row)"
        >
          <td v-for="column in columns" :key="column">
            <template v-if="column === '备电时长'">
              <span v-if="row.有备电数据" class="backup-cell">
                {{ row.备电时长 }}
                <em v-if="row.备电不足" class="tag-low">备电不足</em>
              </span>
              <span v-else class="empty-cell">暂无备电数据，待登记</span>
            </template>
            <template v-else-if="column === '供电状态'">{{ row[column] || row.status || '—' }}</template>
            <template v-else>{{ row[column] ?? '—' }}</template>
          </td>
          <td class="row-actions" @click.stop>
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
        <tr v-if="!rows.length && !loading">
          <td :colspan="columns.length + 1" class="empty-state">
            {{ emptyText }}
          </td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条供电保障记录，其中备电不足 {{ lowCount }} 条</span>
      <span v-if="noticeMessage" class="notice-text">{{ noticeMessage }}</span>
    </footer>

    <div v-if="showCreate" class="modal-mask" @click.self="showCreate = false">
      <form class="modal-card" @submit.prevent="submitCreate">
        <h3>登记供电单元</h3>
        <label v-for="field in createFields" :key="field.name" class="form-item">
          <span>{{ field.label }}<i v-if="field.required" class="required">*</i></span>
          <input v-model="createForm[field.name]" :placeholder="field.placeholder" />
        </label>
        <p v-if="createError" class="error-text">{{ createError }}</p>
        <p class="form-hint">供电编号重复时将自动合并为一条记录。</p>
        <div class="modal-actions">
          <button class="btn ghost" type="button" @click="showCreate = false">取消</button>
          <button class="btn primary" type="submit">保存</button>
        </div>
      </form>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { request } from '@/api/client'

type Row = Record<string, any>

const ENDPOINT = '/api/power'
const columns = ['供电编号', '所属站点', '供电方式', '蓄电池容量', '上次放电测试', '备电时长', '责任人员', '供电状态']
const actions = ['安排巡检', '确认正常', '标记断电']
const statuses = ['待巡检', '供电正常', '备电不足', '已断电']
const createFields = [
  { name: '供电编号', label: '供电编号', required: true, placeholder: '如 POWE-0007' },
  { name: '所属站点', label: '所属站点', required: true, placeholder: '如 龙泉山雷达站' },
  { name: '供电方式', label: '供电方式', required: true, placeholder: '如 市电+蓄电池' },
  { name: '备电时长', label: '备电时长', required: true, placeholder: '如 12小时' },
  { name: '蓄电池容量', label: '蓄电池容量', required: false, placeholder: '如 500Ah' },
  { name: '上次放电测试', label: '上次放电测试', required: false, placeholder: '如 2026-09-01' },
  { name: '责任人员', label: '责任人员', required: false, placeholder: '责任人姓名' },
]

const route = useRoute()
const router = useRouter()

const rows = ref<Row[]>([])
const total = ref(0)
const loading = ref(false)
const errorMessage = ref('')
const noticeMessage = ref('')
const stats = ref<Record<string, number>>({})
const backupMin = ref(8)
const filters = ref({ keyword: '', status: '' })

const showCreate = ref(false)
const createForm = ref<Record<string, string>>({})
const createError = ref('')

const statCards = computed(() => [
  { label: '在册供电单元', value: stats.value['在册供电单元'] ?? 0, warn: false },
  { label: `备电不足（低于${backupMin.value}小时）`, value: stats.value['备电不足'] ?? 0, warn: true },
  { label: '已断电站点', value: stats.value['已断电站点'] ?? 0, warn: true },
])

// 备电不足条数与列表行内标记逐条核对，保证统计与列表对得上
const lowCount = computed(() => rows.value.filter((row) => row.备电不足).length)

const emptyText = computed(() =>
  filters.value.keyword || filters.value.status
    ? '当前查询条件下没有供电保障记录，可调整条件后重试'
    : '暂无备电数据：还没有登记任何供电单元，可点击右上角「登记供电单元」补录',
)

function syncQuery() {
  const query: Record<string, string> = {}
  if (filters.value.keyword) query.keyword = filters.value.keyword
  if (filters.value.status) query.status = filters.value.status
  void router.replace({ path: '/power', query })
}

function buildQueryString() {
  const query = new URLSearchParams()
  if (filters.value.keyword) query.set('keyword', filters.value.keyword)
  if (filters.value.status) query.set('status', filters.value.status)
  return query.toString()
}

function applyFilters() {
  const next = buildQueryString()
  syncQuery()
  // 地址栏条件没变时 watcher 不会触发，需要手动刷新
  if (next === lastLoadedQuery) void reload()
}

function resetFilters() {
  filters.value = { keyword: '', status: '' }
  const next = buildQueryString()
  syncQuery()
  if (next === lastLoadedQuery) void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  createForm.value = {}
  createError.value = ''
  showCreate.value = true
}

async function submitCreate() {
  createError.value = ''
  const missing = createFields
    .filter((field) => field.required && !String(createForm.value[field.name] ?? '').trim())
    .map((field) => field.label)
  if (missing.length) {
    createError.value = `无法保存：${missing.join('、')}为必填项，请补全后再提交`
    return
  }
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: createForm.value }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      createError.value = payload.message ?? payload.detail ?? '保存失败，请稍后重试'
      return
    }
    showCreate.value = false
    noticeMessage.value = payload.message
    await reload()
  } catch (error) {
    createError.value = error instanceof Error ? error.message : '保存失败，请稍后重试'
  }
}

function openDetail(row: Row) {
  void router.push({
    path: `/power/${row.id}`,
    query: {
      ...(filters.value.keyword ? { keyword: filters.value.keyword } : {}),
      ...(filters.value.status ? { status: filters.value.status } : {}),
    },
  })
}

async function runAction(action: string, row: Row) {
  noticeMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message ?? '供电保障动作未生效，请稍后重试')
    }
    noticeMessage.value = payload.message
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '供电保障操作失败'
  }
}

async function reload() {
  // 查询失败时保留原查询条件，重试仍按当前条件发起
  loading.value = true
  errorMessage.value = ''
  const query = new URLSearchParams(buildQueryString())
  query.set('size', '200')
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) {
      throw new Error(`供电单元列表读取失败（${response.status}）`)
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    stats.value = payload.stats ?? {}
    if (rows.value.length && typeof rows.value[0]['备电下限小时'] === 'number') {
      backupMin.value = rows.value[0]['备电下限小时']
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '供电保障列表读取失败'
  } finally {
    loading.value = false
    lastLoadedQuery = buildQueryString()
  }
}

let lastLoadedQuery = ''

function readQuery() {
  filters.value = {
    keyword: String(route.query.keyword ?? ''),
    status: String(route.query.status ?? ''),
  }
}

onMounted(() => {
  readQuery()
  void reload()
})

// 从详情页返回（path 或 query 变化）后按当前条件刷新，保证备电不足条数与统计对得上
watch(
  () => [route.path, route.query.keyword, route.query.status],
  () => {
    if (route.path !== '/power') return
    readQuery()
    void reload()
  },
)
</script>
