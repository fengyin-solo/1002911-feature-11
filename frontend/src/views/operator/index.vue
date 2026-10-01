<template>
  <section class="page" data-module="operator">
    <header class="page-head">
      <div>
        <h2>作业人员管理</h2>
        <p class="page-desc">
          证书复审与注销按单位归属办理：仅本单位证书管理员可登记复审、注销；跨单位代办须持委托单位专项授权；只读岗仅可查看。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" :disabled="store.isViewer" @click="openCreate">登记作业人员</button>
        <button class="btn" type="button" @click="exportRows">导出作业人员清单</button>
      </div>
    </header>

    <div v-if="store.isViewer" class="notice-bar viewer-only">
      当前身份为只读岗（{{ store.operator }}·{{ store.unit }}），只能查看人员台账与复审名单，所有改动按钮已禁用。
    </div>
    <div v-else class="notice-bar">
      当前以证书管理员 {{ store.operator }}（{{ store.unit }}）经办；对非本单位证件的操作将被驳回，驳回信息会列明缺少的委托单位、受托单位与授权事项。
    </div>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <div class="tabs">
      <button class="tab" :class="{ active: tab === 'ledger' }" type="button" @click="tab = 'ledger'">人员台账</button>
      <button class="tab" :class="{ active: tab === 'roster' }" type="button" @click="switchToRoster">
        复审名单（{{ rosterPeriod }}）
      </button>
    </div>

    <template v-if="tab === 'ledger'">
      <form class="filter-bar" @submit.prevent="reload">
        <label class="filter-item">
          <span>人员编号/姓名</span>
          <input v-model="filters.keyword" placeholder="按编号或姓名检索" />
        </label>
        <label class="filter-item">
          <span>证书状态</span>
          <select v-model="filters.status">
            <option value="">全部</option>
            <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
          </select>
        </label>
        <label class="filter-item">
          <span>所属单位</span>
          <select v-model="filters.unit">
            <option value="">全部单位</option>
            <option v-for="unit in units" :key="unit" :value="unit">{{ unit }}</option>
          </select>
        </label>
        <button class="btn" type="submit">查询</button>
        <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
      </form>

      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in columns" :key="column">{{ column }}</th>
            <th>最近经办</th>
            <th>可执行动作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="String(row.id)">
            <td>{{ row['人员编号'] ?? '—' }}</td>
            <td>{{ row['姓名'] ?? '—' }}</td>
            <td>{{ row['证书类别'] ?? '—' }}</td>
            <td>{{ row['证书编号'] ?? '—' }}</td>
            <td>{{ row['发证日期'] ?? '—' }}</td>
            <td>{{ row['复审日期'] ?? '—' }}</td>
            <td>
              {{ row['所属单位'] }}
              <span v-if="!store.isViewer && row['所属单位'] !== store.unit" class="subtle">（外单位）</span>
            </td>
            <td><span class="status-tag" :class="`status-${row['证书状态']}`">{{ row['证书状态'] }}</span></td>
            <td class="subtle">
              <template v-if="row['最近动作']">
                {{ row['最近动作'] }} · {{ row['最近经办人'] }}<br />{{ row['最近经办单位'] }} · {{ row['最近经办时间'] }}
              </template>
              <template v-else>—</template>
            </td>
            <td class="row-actions">
              <button
                v-for="action in availableActions(row)"
                :key="action.name"
                class="link"
                :class="{ danger: action.tone === 'danger' }"
                type="button"
                :disabled="action.disabled"
                :title="action.reason"
                @click="openAction(action.name, row)"
              >
                {{ action.name }}
              </button>
              <button class="link" type="button" @click="openHistory(row)">经办记录</button>
            </td>
          </tr>
          <tr v-if="!rows.length">
            <td :colspan="columns.length + 2" class="empty-state">暂无符合条件的作业人员</td>
          </tr>
        </tbody>
      </table>

      <footer class="page-foot">
        <span>共 {{ total }} 条作业人员记录</span>
        <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
      </footer>
    </template>

    <template v-else>
      <form class="filter-bar" @submit.prevent="reloadRoster">
        <label class="filter-item">
          <span>复审期</span>
          <input v-model="rosterInput" placeholder="如 2026Q4" />
        </label>
        <label class="filter-item">
          <span>所属单位</span>
          <select v-model="rosterUnit">
            <option value="">全部单位</option>
            <option v-for="unit in units" :key="unit" :value="unit">{{ unit }}</option>
          </select>
        </label>
        <button class="btn" type="submit">生成名单</button>
      </form>
      <p class="subtle">
        入期口径：已安排本期、复审日期落在本期、逾期未复审须并入本期补办；状态为「已过期」「已注销」的证件不进名单。
      </p>
      <table class="data-table">
        <thead>
          <tr>
            <th>人员编号</th><th>姓名</th><th>证书类别</th><th>所属单位</th>
            <th>复审日期</th><th>证书状态</th><th>入期原因</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rosterRows" :key="String(row.id)">
            <td>{{ row['人员编号'] }}</td>
            <td>{{ row['姓名'] }}</td>
            <td>{{ row['证书类别'] }}</td>
            <td>{{ row['所属单位'] }}</td>
            <td>{{ row['复审日期'] }}</td>
            <td><span class="status-tag" :class="`status-${row['证书状态']}`">{{ row['证书状态'] }}</span></td>
            <td>{{ row['入期原因'] }}</td>
            <td class="row-actions">
              <button class="link" type="button" :disabled="store.isViewer || row['证书状态'] === '已过期' || row['证书状态'] === '已注销'"
                      @click="openAction('登记复审结果', row)">登记复审结果</button>
              <button class="link" type="button" @click="openHistory(row)">经办记录</button>
            </td>
          </tr>
          <tr v-if="!rosterRows.length">
            <td colspan="8" class="empty-state">{{ rosterPeriod }} 没有待复审证件（终态证件不列入）</td>
          </tr>
        </tbody>
      </table>
      <footer class="page-foot">
        <span>共 {{ rosterRows.length }} 条复审安排</span>
        <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
      </footer>
    </template>

    <!-- 动作表单：安排复审 / 登记复审结果 / 登记过期 / 注销 / 调动 -->
    <div v-if="actionDialog.open" class="modal-mask" @click.self="closeDialog">
      <div class="modal">
        <h3>{{ actionDialog.action }} · {{ actionDialog.row?.['姓名'] }}（{{ actionDialog.row?.['人员编号'] }}）</h3>
        <p class="modal-sub">
          所属单位：{{ actionDialog.row?.['所属单位'] }} ｜ 当前状态：{{ actionDialog.row?.['证书状态'] }}
        </p>
        <div v-if="actionDialog.action === '安排复审'" class="form-item">
          <label>复审期（如 2026Q4）</label>
          <input v-model="actionForm['复审期']" placeholder="2026Q4" />
        </div>
        <template v-if="actionDialog.action === '登记复审结果'">
          <div class="form-item">
            <label>本次复审日期</label>
            <input v-model="actionForm['复审日期']" type="date" />
          </div>
          <div class="form-item">
            <label>复审结果</label>
            <select v-model="actionForm['复审结果']">
              <option value="合格">合格——换新复审日期，证件继续有效</option>
              <option value="不合格">不合格——状态落定为已过期，不再排入下一期</option>
            </select>
          </div>
          <div v-if="actionForm['复审结果'] === '合格'" class="form-item">
            <label>下一次复审日期</label>
            <input v-model="actionForm['新复审日期']" type="date" />
          </div>
        </template>
        <div v-if="actionDialog.action === '登记过期'" class="form-item">
          <label>登记日期</label>
          <input v-model="actionForm['复审日期']" type="date" />
        </div>
        <div v-if="actionDialog.action === '人员调动'" class="form-item">
          <label>调入单位</label>
          <input v-model="actionForm['新单位']" placeholder="接收单位全称" />
        </div>
        <div v-if="actionDialog.action === '人员调动'" class="form-item">
          <label>调动日期</label>
          <input v-model="actionForm['调动日期']" type="date" />
        </div>
        <div class="form-item">
          <label>备注</label>
          <textarea v-model="actionForm['备注']" rows="2" placeholder="选填，随经办记录一并留痕"></textarea>
        </div>
        <p v-if="dialogError" class="error-text">{{ dialogError }}</p>
        <div class="modal-foot">
          <button class="btn ghost" type="button" @click="closeDialog">取消</button>
          <button class="btn primary" type="button" :disabled="submitting" @click="submitAction">
            {{ submitting ? '提交中…' : '确认提交' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 新人员登记 -->
    <div v-if="createDialog" class="modal-mask" @click.self="createDialog = false">
      <div class="modal">
        <h3>登记作业人员</h3>
        <p class="modal-sub">仅可登记本单位（{{ store.unit }}）人员；代其他单位登记须持「证书复审登记」事项授权。</p>
        <div v-for="field in createFields" :key="field.key" class="form-item">
          <label>{{ field.label }}{{ field.required ? ' *' : '' }}</label>
          <input v-model="createForm[field.key]" :type="field.type ?? 'text'" :placeholder="field.placeholder ?? ''" />
        </div>
        <div class="form-item">
          <label>所属单位 *</label>
          <input v-model="createForm['所属单位']" list="unit-options" />
          <datalist id="unit-options">
            <option v-for="unit in units" :key="unit" :value="unit" />
          </datalist>
        </div>
        <p v-if="dialogError" class="error-text">{{ dialogError }}</p>
        <div class="modal-foot">
          <button class="btn ghost" type="button" @click="createDialog = false">取消</button>
          <button class="btn primary" type="button" :disabled="submitting" @click="submitCreate">确认登记</button>
        </div>
      </div>
    </div>

    <!-- 经办记录与单位沿革 -->
    <div v-if="historyRow" class="modal-mask" @click.self="historyRow = null">
      <div class="modal" style="width: 680px">
        <h3>经办记录 · {{ historyRow['姓名'] }}（{{ historyRow['人员编号'] }}）</h3>
        <p class="modal-sub">
          现所属单位：{{ historyRow['所属单位'] }} ｜ 当前状态：{{ historyRow['证书状态'] }}
        </p>
        <div class="history-panel">
          <h4>复审与注销经办记录</h4>
          <table class="data-table">
            <thead>
              <tr><th>时间</th><th>动作</th><th>经办人</th><th>经办单位</th><th>内容</th></tr>
            </thead>
            <tbody>
              <tr v-for="(record, index) in historyRow['复审记录']?.slice().reverse()" :key="index">
                <td>{{ record['经办时间'] }}</td>
                <td>{{ record['动作'] }}</td>
                <td>{{ record['经办人'] }}</td>
                <td>{{ record['经办单位'] }}</td>
                <td>{{ describeRecord(record) }}</td>
              </tr>
              <tr v-if="!historyRow['复审记录']?.length">
                <td colspan="5" class="empty-state">暂无复审经办记录</td>
              </tr>
            </tbody>
          </table>
          <h4>单位沿革（人员调动追溯）</h4>
          <table class="data-table">
            <thead>
              <tr><th>单位</th><th>起</th><th>止</th><th>经办人/经办单位</th><th>备注</th></tr>
            </thead>
            <tbody>
              <tr v-for="(record, index) in historyRow['单位沿革']" :key="index">
                <td>{{ record['单位'] }}</td>
                <td>{{ record['起'] }}</td>
                <td>{{ record['止'] ?? '至今' }}</td>
                <td>{{ record['经办人'] }} · {{ record['经办单位'] }}<br />{{ record['经办时间'] }}</td>
                <td>{{ record['备注'] ?? '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="modal-foot">
          <button class="btn primary" type="button" @click="historyRow = null">关闭</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { fetchJson, postAction } from '@/api/client'
import { useSessionStore } from '@/stores/session'

type Row = Record<string, any>

const ENDPOINT = '/api/operator'
const store = useSessionStore()

const columns = ['人员编号', '姓名', '证书类别', '证书编号', '发证日期', '复审日期', '所属单位', '证书状态']
const statuses = ['持证有效', '即将到期', '逾期未复审', '已过期', '已注销']
const TERMINAL = ['已过期', '已注销']

const rows = ref<Row[]>([])
const total = ref(0)
const units = ref<string[]>([])
const errorMessage = ref('')
const filters = reactive<{ keyword: string; status: string; unit: string }>({ keyword: '', status: '', unit: '' })
const tab = ref<'ledger' | 'roster'>('ledger')

// 复审名单
const rosterRows = ref<Row[]>([])
const rosterPeriod = ref('')
const rosterInput = ref('')
const rosterUnit = ref('')

// 弹窗
const actionDialog = reactive<{ open: boolean; action: string; row: Row | null }>({
  open: false,
  action: '',
  row: null,
})
const actionForm = reactive<Record<string, string>>({})
const createDialog = ref(false)
const createForm = reactive<Record<string, string>>({})
const historyRow = ref<Row | null>(null)
const dialogError = ref('')
const submitting = ref(false)

const createFields = [
  { key: '人员编号', label: '人员编号', required: true, placeholder: 'OPER-0009' },
  { key: '姓名', label: '姓名', required: true },
  { key: '证书类别', label: '证书类别', required: true, placeholder: '如 叉车司机（N1）' },
  { key: '证书编号', label: '证书编号', required: true },
  { key: '发证日期', label: '发证日期', required: true, type: 'date' },
]

const stats = computed(() => {
  const count = (status: string) => rows.value.filter((row) => row['证书状态'] === status).length
  return [
    { label: '持证人员（本页）', value: count('持证有效') + count('即将到期') },
    { label: '即将到期（本页）', value: count('即将到期') },
    { label: '逾期未复审（本页）', value: count('逾期未复审') },
    { label: '终态：过期/注销（本页）', value: count('已过期') + count('已注销') },
  ]
})

function availableActions(row: Row): { name: string; disabled: boolean; reason: string; tone?: string }[] {
  const status = String(row['证书状态'])
  const foreign = !store.isViewer && row['所属单位'] !== store.unit
  const all = [
    { name: '安排复审', disabled: false, reason: '' },
    { name: '登记复审结果', disabled: false, reason: '' },
    { name: '登记过期', disabled: status !== '逾期未复审', reason: '仅逾期未复审、确认不再补办时可登记过期', tone: 'danger' },
    { name: '注销证书', disabled: false, reason: '', tone: 'danger' },
    { name: '人员调动', disabled: false, reason: '' },
  ]
  if (store.isViewer) {
    return all.map((item) => ({ ...item, disabled: true, reason: '只读岗仅可查看' }))
  }
  // 终态锁死：本单位管理员也不能再动；跨单位按钮保留可点，点击后由后端驳回并解释缺哪项授权。
  return all.map((item) =>
    TERMINAL.includes(status)
      ? { ...item, disabled: true, reason: `证件已处于「${status}」终态，不能再复审或注销` }
      : { ...item, reason: foreign ? `外单位证件，代办须持 ${row['所属单位']} 的专项授权，否则将被驳回` : '' },
  )
}

function resetFilters() {
  filters.keyword = ''
  filters.status = ''
  filters.unit = ''
  void reload()
}

function describeRecord(record: Row): string {
  const parts: string[] = []
  if (record['复审期']) parts.push(`复审期 ${record['复审期']}`)
  if (record['复审日期']) parts.push(`日期 ${record['复审日期']}`)
  if (record['复审结果']) parts.push(`结果 ${record['复审结果']}`)
  if (record['新复审日期']) parts.push(`新复审日期 ${record['新复审日期']}`)
  if (record['原单位']) parts.push(`${record['原单位']} → ${record['新单位']}`)
  if (record['修改字段']) parts.push(`修改 ${record['修改字段']}`)
  if (record['备注']) parts.push(record['备注'])
  return parts.join('；')
}

function openCreate() {
  dialogError.value = ''
  for (const key of Object.keys(createForm)) delete createForm[key]
  createForm['所属单位'] = store.unit
  createDialog.value = true
}

async function submitCreate() {
  dialogError.value = ''
  submitting.value = true
  try {
    const response = await fetch(`${ENDPOINT}`, {
      method: 'POST',
      body: JSON.stringify({ values: { ...createForm } }),
    })
    const payload = await response.json()
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.detail ?? payload.message ?? '登记失败')
    }
    createDialog.value = false
    errorMessage.value = payload.message ?? '作业人员已登记'
    await Promise.all([reload(), loadUnits()])
  } catch (error) {
    dialogError.value = error instanceof Error ? error.message : '登记失败'
  } finally {
    submitting.value = false
  }
}

function openAction(action: string, row: Row) {
  dialogError.value = ''
  actionDialog.open = true
  actionDialog.action = action
  actionDialog.row = row
  for (const key of Object.keys(actionForm)) delete actionForm[key]
  if (action === '安排复审') actionForm['复审期'] = rosterPeriod.value || ''
  if (action === '登记复审结果') actionForm['复审结果'] = '合格'
}

function closeDialog() {
  actionDialog.open = false
  actionDialog.row = null
}

async function submitAction() {
  if (!actionDialog.row) return
  dialogError.value = ''
  submitting.value = true
  try {
    const { message } = await postAction(`${ENDPOINT}/${actionDialog.row.id}/actions`, {
      values: { action: actionDialog.action, ...actionForm },
    })
    errorMessage.value = message
    closeDialog()
    await reloadAll()
  } catch (error) {
    dialogError.value = error instanceof Error ? error.message : '操作失败'
  } finally {
    submitting.value = false
  }
}

function openHistory(row: Row) {
  // 台账列表已含完整记录；名单页数据同样来自 serialize，可直接展示
  historyRow.value = row
}

async function exportRows() {
  errorMessage.value = ''
  try {
    const payload = await fetchJson<{ items: Row[] }>(`${ENDPOINT}/export`)
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = '作业人员清单.json'
    link.click()
    URL.revokeObjectURL(url)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '导出失败'
  }
}

async function loadUnits() {
  try {
    const payload = await fetchJson<{ items: string[] }>(`${ENDPOINT}/units`)
    units.value = payload.items ?? []
  } catch {
    // 单位字典失败不阻塞列表
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (filters.keyword) query.set('keyword', filters.keyword)
  if (filters.status) query.set('status', filters.status)
  if (filters.unit) query.set('unit', filters.unit)
  try {
    const payload = await fetchJson<{ items: Row[]; total: number }>(`${ENDPOINT}?${query.toString()}`)
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '作业人员列表读取失败'
  }
}

async function reloadRoster() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (rosterInput.value.trim()) query.set('period', rosterInput.value.trim())
  if (rosterUnit.value) query.set('unit', rosterUnit.value)
  try {
    const payload = await fetchJson<{ items: Row[]; period: string }>(`${ENDPOINT}/roster?${query.toString()}`)
    rosterRows.value = payload.items ?? []
    rosterPeriod.value = payload.period
    rosterInput.value = payload.period
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '复审名单读取失败'
  }
}

function switchToRoster() {
  tab.value = 'roster'
  void reloadRoster()
}

async function reloadAll() {
  await Promise.all([reload(), tab.value === 'roster' ? reloadRoster() : Promise.resolve()])
}

onMounted(async () => {
  await loadUnits()
  await reload()
  // 默认复审期预填为当前季度（由后端 roster 接口给出）
  const query = new URLSearchParams()
  if (filters.unit) query.set('unit', filters.unit)
  try {
    const payload = await fetchJson<{ period: string }>(`${ENDPOINT}/roster?${query.toString()}`)
    rosterPeriod.value = payload.period
    rosterInput.value = payload.period
  } catch {
    // 预填失败不影响台账使用
  }
})
</script>
