<template>
  <section class="page" data-module="power">
    <header class="page-head">
      <div>
        <h2>供电单元详情</h2>
        <p class="page-desc">标记断电前后都可在此核对最近一次放电测试、责任人员与最近一次巡检结论。</p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" @click="goBack">返回列表</button>
      </div>
    </header>

    <div v-if="entry" class="detail-card">
      <dl class="detail-grid">
        <template v-for="field in detailFields" :key="field">
          <dt>{{ field }}</dt>
          <dd>
            <span
              v-if="field === '供电状态'"
              class="status-tag"
              :class="{ 'status-danger': entry.status === '备电不足' || entry.status === '已断电' }"
            >{{ entry[field] ?? '—' }}</span>
            <template v-else>{{ entry[field] ?? '—' }}</template>
          </dd>
        </template>
      </dl>
      <div class="row-actions detail-actions">
        <button
          v-for="action in actions"
          :key="action"
          class="btn"
          type="button"
          @click="runAction(action)"
        >
          {{ action }}
        </button>
      </div>
      <p v-if="actionMessage" class="action-message">{{ actionMessage }}</p>
    </div>

    <div v-if="errorMessage" class="error-bar">
      <span class="error-text">{{ errorMessage }}</span>
      <button class="btn" type="button" @click="load">重试</button>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/power'
const detailFields = ["供电编号", "所属站点", "供电方式", "蓄电池容量", "上次放电测试", "备电时长", "责任人员", "最近巡检结论", "供电状态"]
const actions = ["安排巡检", "确认正常", "标记断电"]

const route = useRoute()
const router = useRouter()

const entry = ref<Row | null>(null)
const errorMessage = ref('')
const actionMessage = ref('')

async function load() {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${route.params.id}`)
    const payload = await response.json()
    if (!response.ok) {
      throw new Error(payload.detail ?? `供电单元读取失败（${response.status}）`)
    }
    entry.value = payload
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '供电单元读取失败'
  }
}

async function runAction(action: string) {
  actionMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${route.params.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message ?? '供电保障动作未生效，请稍后重试')
    }
    actionMessage.value = payload.message ?? ''
    // 动作生效后重新拉取明细：断电后最近一次放电测试、责任人员、巡检结论仍然可查
    await load()
  } catch (error) {
    actionMessage.value = error instanceof Error ? error.message : '供电保障操作失败'
  }
}

function goBack() {
  void router.push('/power')
}

onMounted(load)
</script>
