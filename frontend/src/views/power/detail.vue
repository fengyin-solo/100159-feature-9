<template>
  <section class="page" data-module="power-detail">
    <header class="page-head">
      <div>
        <h2>供电单元详情</h2>
        <p class="page-desc">备电时长、最近一次放电测试与巡检结论汇总，标记断电前后口径一致。</p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" @click="backToList">返回列表</button>
      </div>
    </header>

    <div v-if="errorMessage" class="error-banner">
      <span>{{ errorMessage }}</span>
      <button class="btn" type="button" @click="reload">重试</button>
    </div>

    <div v-if="entry" class="detail-wrap">
      <div class="detail-head">
        <div>
          <h3>{{ entry['供电编号'] }} · {{ entry['所属站点'] }}</h3>
          <p>
            <em class="tag-status" :class="{ 'tag-low': entry['备电不足'], 'tag-off': isCutoff }">
              {{ entry['供电状态'] || entry.status }}
            </em>
            <em v-if="entry['备电不足']" class="tag-low">备电不足</em>
          </p>
        </div>
        <div class="row-actions detail-actions">
          <button
            v-for="action in actions"
            :key="action"
            class="btn"
            :class="{ primary: action === '标记断电' }"
            type="button"
            @click="runAction(action)"
          >
            {{ action }}
          </button>
        </div>
      </div>

      <article class="detail-card">
        <h4>基本信息</h4>
        <dl class="detail-grid">
          <div v-for="field in baseFields" :key="field" class="detail-item">
            <dt>{{ field }}</dt>
            <dd>{{ entry[field] || '—' }}</dd>
          </div>
        </dl>
      </article>

      <article class="detail-card" :class="{ 'card-warn': entry['备电不足'] }">
        <h4>备电与放电测试</h4>
        <dl class="detail-grid">
          <div class="detail-item">
            <dt>备电时长</dt>
            <dd>
              <span v-if="entry['有备电数据']">
                {{ entry['备电时长'] }}
                <em v-if="entry['备电不足']" class="tag-low">
                  低于下限 {{ entry['备电下限小时'] }} 小时
                </em>
              </span>
              <span v-else class="empty-cell">暂无备电数据，待登记</span>
            </dd>
          </div>
          <div class="detail-item">
            <dt>最近一次放电测试</dt>
            <dd>{{ entry['最近放电测试'] || '暂无放电测试记录' }}</dd>
          </div>
          <div class="detail-item">
            <dt>责任人员</dt>
            <dd>{{ entry['责任人员'] || '暂无责任人' }}</dd>
          </div>
          <div v-if="isCutoff" class="detail-item">
            <dt>断电时刻</dt>
            <dd>{{ entry['断电时刻'] }}</dd>
          </div>
        </dl>
      </article>

      <article class="detail-card">
        <h4>最近一次巡检结论</h4>
        <dl v-if="inspection" class="detail-grid">
          <div v-for="field in inspectionFields" :key="field" class="detail-item">
            <dt>{{ field }}</dt>
            <dd>{{ inspection[field] || '—' }}</dd>
          </div>
        </dl>
        <p v-else class="empty-cell">该站点暂无巡检记录，可通过「安排巡检」发起巡检。</p>
      </article>

      <p v-if="noticeMessage" class="notice-text">{{ noticeMessage }}</p>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { request } from '@/api/client'

type Entry = Record<string, any>

const actions = ['安排巡检', '确认正常', '标记断电']
const baseFields = ['供电编号', '所属站点', '供电方式', '蓄电池容量']
const inspectionFields = ['巡检单号', '巡检人员', '巡检日期', '巡检项目', '巡检状态', '巡检结论']

const route = useRoute()
const router = useRouter()

const entry = ref<Entry | null>(null)
const errorMessage = ref('')
const noticeMessage = ref('')

const inspection = computed(() => entry.value?.['最近巡检'] ?? null)
const isCutoff = computed(() => entry.value?.status === '已断电' || entry.value?.['供电状态'] === '已断电')

function backToList() {
  // 返回列表时带回原查询条件，列表据此刷新并保持统计口径
  void router.push({ path: '/power', query: route.query })
}

async function runAction(action: string) {
  if (!entry.value) return
  noticeMessage.value = ''
  try {
    const response = await request(`/api/power/${entry.value.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message ?? '动作未生效，请稍后重试')
    }
    entry.value = payload.entry
    noticeMessage.value = payload.message
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '供电保障操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const id = route.params.id
  try {
    const response = await request(`/api/power/${id}`)
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}))
      throw new Error(payload.detail ?? `供电单元 ${id} 读取失败（${response.status}）`)
    }
    entry.value = await response.json()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '供电单元明细读取失败'
  }
}

onMounted(reload)
</script>
