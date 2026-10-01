<template>
  <section class="page" data-module="operator">
    <header class="page-head">
      <div>
        <h2>作业人员管理</h2>
        <p class="page-desc">
          证书按归属单位管理：只有本单位证书管理员能登记复审、注销与改证；跨单位代办须持授权；只读岗仅可查看。
        </p>
      </div>
      <div class="page-actions">
        <button v-if="store.isCertAdmin" class="btn primary" type="button" @click="openCreate">登记作业人员</button>
        <button class="btn" type="button" @click="exportRows">导出作业人员清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <div class="tab-bar">
      <button class="tab-btn" :class="{ active: tab === 'ledger' }" type="button" @click="switchTab('ledger')">
        人员台账
      </button>
      <button class="tab-btn" :class="{ active: tab === 'roster' }" type="button" @click="switchTab('roster')">
        下一期复审名单<span v-if="rosterTotal">（{{ rosterTotal }}）</span>
      </button>
    </div>

    <!-- 归属提示条 -->
    <p class="hint-line">
      当前经办人：<strong>{{ store.operator }}</strong>（{{ store.currentUnit }} ·
      {{ store.isCertAdmin ? '证书管理员，可办理本单位证件' : '只读岗，只能查看' }}）<template
        v-if="delegatedUnits.length">；已持代办授权：{{ delegatedUnits.join('、') }}</template>
      <template v-else-if="store.isCertAdmin">；暂无跨单位代办授权</template>
    </p>

    <form v-if="tab === 'ledger'" class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>关键字</span>
        <input v-model="filters.keyword" placeholder="按人员编号/姓名/证书编号检索" />
      </label>
      <label class="filter-item">
        <span>所属单位</span>
        <input v-model="filters.unit" placeholder="按所属单位检索" />
      </label>
      <label class="filter-item">
        <span>证书状态</span>
        <select v-model="filters.status">
          <option value="">全部</option>
          <option v-for="s in statuses" :key="s" :value="s">{{ s }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>锁定</th>
          <th>经办/可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in shownRows" :key="String(row.id)">
          <td>{{ row['人员编号'] }}</td>
          <td>{{ row['姓名'] }}</td>
          <td>{{ row['证书类别'] }}</td>
          <td>{{ row['证书编号'] }}</td>
          <td>{{ row['发证日期'] }}</td>
          <td>{{ row['复审日期'] }}</td>
          <td>
            <span :class="isSelfUnit(row['所属单位']) ? 'unit-self' : 'unit-other'">
              {{ row['所属单位'] }}
            </span>
          </td>
          <td><span class="badge" :class="badgeClass(row['证书状态'])">{{ row['证书状态'] }}</span></td>
          <td>{{ row.locked ? '已锁定' : '正常' }}</td>
          <td class="row-actions">
            <button class="link" type="button" @click="openHistory(row)">经办记录</button>
            <template v-if="store.isCertAdmin">
              <button class="link" type="button" :disabled="!can(row, '复审登记')"
                      :title="denyReason(row, '复审登记')" @click="openReview(row)">登记复审</button>
              <button class="link" type="button" :disabled="!can(row, '登记过期')"
                      :title="denyReason(row, '登记过期')" @click="doExpire(row)">登记过期</button>
              <button class="link" type="button" :disabled="!can(row, '注销证书')"
                      :title="denyReason(row, '注销证书')" @click="doRevoke(row)">注销证书</button>
              <button class="link" type="button" :disabled="!can(row, '人员调动')"
                      :title="denyReason(row, '人员调动')" @click="openTransfer(row)">人员调动</button>
              <button class="link" type="button" :disabled="!can(row, '变更证书')"
                      :title="denyReason(row, '变更证书')" @click="openEdit(row)">改证</button>
            </template>
            <span v-else class="hint-line" style="margin:0">只读</span>
          </td>
        </tr>
        <tr v-if="!shownRows.length">
          <td :colspan="columns.length + 2" class="empty-state">
            {{ tab === 'roster' ? '下一期复审名单为空：没有临近/逾期且未锁定的证件' : '暂无作业人员数据，可先登记作业人员' }}
          </td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条记录</span>
      <span v-if="okMessage" class="ok-text">{{ okMessage }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <!-- 复审登记弹窗 -->
    <div v-if="dialog.review" class="modal-mask" @click.self="closeDialog">
      <div class="modal">
        <h3>登记证书复审 · {{ dialog.row?.['姓名'] }}（{{ dialog.row?.['人员编号'] }}）</h3>
        <p class="modal-note">所属单位：{{ dialog.row?.['所属单位'] }}；当前复审日期：{{ dialog.row?.['复审日期'] }}</p>
        <div class="form-grid">
          <label class="full">
            复审结果
            <select v-model="dialog.reviewResult">
              <option value="合格">合格（证书有效，顺延复审日期）</option>
              <option value="不合格">不合格（当场登记为已过期并锁定，不再排复审）</option>
            </select>
          </label>
          <label v-if="dialog.reviewResult === '合格'" class="full">
            下一次复审日期（留空按复审周期自动顺延）
            <input v-model="dialog.nextReviewDate" type="date" />
          </label>
          <label class="full">
            备注
            <textarea v-model="dialog.remark" placeholder="可选：记录复审机构、考核情况等"></textarea>
          </label>
        </div>
        <div class="modal-foot">
          <button class="btn ghost" type="button" @click="closeDialog">取消</button>
          <button class="btn primary" type="button" :disabled="dialog.submitting" @click="submitReview">提交复审</button>
        </div>
      </div>
    </div>

    <!-- 人员调动弹窗 -->
    <div v-if="dialog.transfer" class="modal-mask" @click.self="closeDialog">
      <div class="modal">
        <h3>人员调动 · {{ dialog.row?.['姓名'] }}</h3>
        <p class="modal-note">现归属：{{ dialog.row?.['所属单位'] }}。调动须由现归属单位证书管理员发起，历史会保留原经办单位。</p>
        <div class="form-grid">
          <label class="full">
            调入单位
            <input v-model="dialog.targetUnit" placeholder="填写调入单位全称" />
          </label>
          <label class="full">
            备注
            <textarea v-model="dialog.remark" placeholder="可选"></textarea>
          </label>
        </div>
        <div class="modal-foot">
          <button class="btn ghost" type="button" @click="closeDialog">取消</button>
          <button class="btn primary" type="button" :disabled="dialog.submitting" @click="submitTransfer">确认调动</button>
        </div>
      </div>
    </div>

    <!-- 改证弹窗 -->
    <div v-if="dialog.edit" class="modal-mask" @click.self="closeDialog">
      <div class="modal">
        <h3>变更证书信息 · {{ dialog.row?.['姓名'] }}</h3>
        <p class="modal-note">证书类别与复审日期为受控字段，仅本单位证书管理员可改，只读岗与越权代办会被驳回。</p>
        <div class="form-grid">
          <label class="full">
            证书类别
            <input v-model="dialog.certCategory" />
          </label>
          <label class="full">
            复审日期
            <input v-model="dialog.reviewDate" type="date" />
          </label>
        </div>
        <div class="modal-foot">
          <button class="btn ghost" type="button" @click="closeDialog">取消</button>
          <button class="btn primary" type="button" :disabled="dialog.submitting" @click="submitEdit">保存</button>
        </div>
      </div>
    </div>

    <!-- 新建弹窗 -->
    <div v-if="dialog.create" class="modal-mask" @click.self="closeDialog">
      <div class="modal">
        <h3>登记作业人员证书</h3>
        <p class="modal-note">将以经办人「{{ store.operator }}」的归属单位口径校验；可手动指定所属单位（需对该单位有授权）。</p>
        <div class="form-grid">
          <label><span>人员编号 *</span><input v-model="dialog.form.人员编号" /></label>
          <label><span>姓名 *</span><input v-model="dialog.form.姓名" /></label>
          <label class="full"><span>证书类别 *</span><input v-model="dialog.form.证书类别" /></label>
          <label><span>证书编号 *</span><input v-model="dialog.form.证书编号" /></label>
          <label><span>所属单位 *</span><input v-model="dialog.form.所属单位" :placeholder="store.currentUnit" /></label>
          <label><span>发证日期</span><input v-model="dialog.form.发证日期" type="date" /></label>
          <label><span>复审日期</span><input v-model="dialog.form.复审日期" type="date" /></label>
        </div>
        <div class="modal-foot">
          <button class="btn ghost" type="button" @click="closeDialog">取消</button>
          <button class="btn primary" type="button" :disabled="dialog.submitting" @click="submitCreate">登记</button>
        </div>
      </div>
    </div>

    <!-- 经办记录弹窗 -->
    <div v-if="dialog.history" class="modal-mask" @click.self="closeDialog">
      <div class="modal">
        <h3>经办记录 · {{ dialog.row?.['姓名'] }}（{{ dialog.row?.['人员编号'] }}）</h3>
        <p class="modal-note">当前归属：{{ dialog.row?.['所属单位'] }}。历史保留每次动作的经办时点单位，调动后仍可追溯。</p>
        <ul v-if="dialog.historyList.length" class="timeline">
          <li v-for="(rec, idx) in dialog.historyList" :key="idx">
            <div><strong>{{ rec['动作'] }}</strong> · {{ rec['结果'] }}</div>
            <div class="t-meta">{{ rec['经办日期'] }} · {{ rec['经办人'] }}（经办时单位：{{ rec['经办单位'] }}）</div>
            <div v-if="rec['备注']">{{ rec['备注'] }}</div>
          </li>
        </ul>
        <p v-else class="modal-note">暂无经办记录。</p>
        <div class="modal-foot">
          <button class="btn primary" type="button" @click="closeDialog">关闭</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'

import { request } from '@/api/client'
import { useSessionStore } from '@/stores/session'

type Row = Record<string, string | number | boolean | null> & {
  id: number
  locked?: boolean
  permissions?: {
    reviewable: boolean
    expirable: boolean
    revocable: boolean
    transferable: boolean
    editable: boolean
    denyReasons: Record<string, string>
  }
}
type HistoryRecord = Record<string, string>

const ENDPOINT = '/api/operator'
const store = useSessionStore()

const columns = ['人员编号', '姓名', '证书类别', '证书编号', '发证日期', '复审日期', '所属单位', '证书状态']
const statuses = ['持证有效', '即将到期', '已过期', '已注销']

const tab = ref<'ledger' | 'roster'>('ledger')
const rows = ref<Row[]>([])
const rosterRows = ref<Row[]>([])
const rosterTotal = ref(0)
const total = ref(0)
const errorMessage = ref('')
const okMessage = ref('')
const filters = reactive({ keyword: '', unit: '', status: '' })

const dialog = reactive({
  review: false,
  transfer: false,
  edit: false,
  create: false,
  history: false,
  submitting: false,
  row: null as Row | null,
  reviewResult: '合格',
  nextReviewDate: '',
  targetUnit: '',
  certCategory: '',
  reviewDate: '',
  remark: '',
  form: {} as Record<string, string>,
  historyList: [] as HistoryRecord[],
})

const shownRows = computed<Row[]>(() => (tab.value === 'roster' ? rosterRows.value : rows.value))
const delegatedUnits = computed(() => store.actor?.delegatedUnits ?? [])

const stats = computed(() => {
  const source = rows.value
  const count = (s: string) => source.filter((r) => r['证书状态'] === s).length
  return [
    { label: '持证人员', value: count('持证有效') },
    { label: '到期/临期人员', value: count('即将到期') + count('已过期') },
    { label: '已锁定（过期/注销）', value: source.filter((r) => r.locked).length },
  ]
})

function badgeClass(status: string | number | boolean | null | undefined): string {
  switch (status) {
    case '持证有效': return 'valid'
    case '即将到期': return 'expiring'
    case '已过期': return 'overdue locked'
    case '已注销': return 'revoked'
    default: return ''
  }
}

function isSelfUnit(unit: string | number | boolean | null | undefined): boolean {
  return String(unit ?? '') === store.currentUnit
}

/** 前端按钮置灰口径，与后端 permissions 完全对齐（后端仍会再判一次）。 */
function can(row: Row, action: string): boolean {
  const p = row.permissions
  if (!p) return false
  switch (action) {
    case '复审登记': return p.reviewable
    case '登记过期': return p.expirable
    case '注销证书': return p.revocable
    case '人员调动': return p.transferable
    case '变更证书': return p.editable
    default: return false
  }
}

function denyReason(row: Row, action: string): string {
  return row.permissions?.denyReasons?.[action] ?? '当前身份无权执行该操作'
}

function resetFilters() {
  filters.keyword = ''
  filters.unit = ''
  filters.status = ''
  void reload()
}

function switchTab(next: 'ledger' | 'roster') {
  tab.value = next
  if (next === 'roster') void loadRoster()
  else void reload()
}

async function callAction(url: string, body: Record<string, unknown>, method = 'POST') {
  errorMessage.value = ''
  const response = await request(url, { method, body: JSON.stringify(body) })
  const payload = await response.json().catch(() => ({}))
  if (!response.ok || payload.ok === false) {
    // 403/409 等驳回：把后端那句“缺哪项授权”的说明原样提示出来。
    throw new Error(payload.message || payload.detail || '操作未生效')
  }
  return payload
}

function flash(message: string) {
  okMessage.value = message
  window.setTimeout(() => { okMessage.value = '' }, 4000)
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (filters.keyword) query.set('keyword', filters.keyword)
  if (filters.unit) query.set('unit', filters.unit)
  if (filters.status) query.set('status', filters.status)
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) throw new Error('作业人员列表读取失败')
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '作业人员列表读取失败'
  }
}

async function loadRoster() {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/review-roster`)
    if (!response.ok) throw new Error('复审名单读取失败')
    const payload = await response.json()
    rosterRows.value = payload.items ?? []
    rosterTotal.value = payload.total ?? rosterRows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '复审名单读取失败'
  }
}

function exportRows() {
  // 直接打开导出地址；actor 头在地址栏打开时带不上，导出本身是只读，后端有默认经办人兜底。
  window.open(`${ENDPOINT}/export`, '_blank')
}

// ---------- 弹窗动作 ----------
function closeDialog() {
  dialog.review = dialog.transfer = dialog.edit = dialog.create = dialog.history = false
  dialog.row = null
}

function openReview(row: Row) {
  dialog.row = row
  dialog.reviewResult = '合格'
  dialog.nextReviewDate = ''
  dialog.remark = ''
  dialog.review = true
}

function openTransfer(row: Row) {
  dialog.row = row
  dialog.targetUnit = ''
  dialog.remark = ''
  dialog.transfer = true
}

function openEdit(row: Row) {
  dialog.row = row
  dialog.certCategory = String(row['证书类别'] ?? '')
  dialog.reviewDate = String(row['复审日期'] ?? '')
  dialog.edit = true
}

function openCreate() {
  dialog.form = { 所属单位: store.currentUnit }
  dialog.create = true
}

async function submitReview() {
  if (!dialog.row) return
  dialog.submitting = true
  try {
    const payload = await callAction(`${ENDPOINT}/${dialog.row.id}/review`, {
      result: dialog.reviewResult,
      next_review_date: dialog.nextReviewDate || null,
      remark: dialog.remark || null,
    })
    flash(payload.message || '复审已登记')
    closeDialog()
    await refreshAll()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '复审登记失败'
  } finally {
    dialog.submitting = false
  }
}

async function doExpire(row: Row) {
  if (!window.confirm(`确认将「${row['姓名']}」的证书登记为已过期？登记后锁定，不再排进下一期复审。`)) return
  try {
    const payload = await callAction(`${ENDPOINT}/${row.id}/expire`, { remark: null })
    flash(payload.message || '已登记过期')
    await refreshAll()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '登记过期失败'
  }
}

async function doRevoke(row: Row) {
  if (!window.confirm(`确认注销「${row['姓名']}」的证书？注销后状态终局为已注销。`)) return
  try {
    const payload = await callAction(`${ENDPOINT}/${row.id}/revoke`, { remark: null })
    flash(payload.message || '证书已注销')
    await refreshAll()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '注销失败'
  }
}

async function submitTransfer() {
  if (!dialog.row) return
  if (!dialog.targetUnit.trim()) {
    errorMessage.value = '请填写调入单位'
    return
  }
  dialog.submitting = true
  try {
    const payload = await callAction(`${ENDPOINT}/${dialog.row.id}/transfer`, {
      target_unit: dialog.targetUnit.trim(),
      remark: dialog.remark || null,
    })
    flash(payload.message || '调动完成')
    closeDialog()
    await refreshAll()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '调动失败'
  } finally {
    dialog.submitting = false
  }
}

async function submitEdit() {
  if (!dialog.row) return
  dialog.submitting = true
  try {
    const payload = await callAction(`${ENDPOINT}/${dialog.row.id}/cert`, {
      values: { 证书类别: dialog.certCategory, 复审日期: dialog.reviewDate },
    }, 'PUT')
    flash(payload.message || '证书信息已更新')
    closeDialog()
    await refreshAll()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '证书信息更新失败'
  } finally {
    dialog.submitting = false
  }
}

async function submitCreate() {
  dialog.submitting = true
  try {
    const payload = await callAction(ENDPOINT, { values: { ...dialog.form } })
    flash(payload.message || '作业人员已登记')
    closeDialog()
    await refreshAll()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '登记失败'
  } finally {
    dialog.submitting = false
  }
}

async function openHistory(row: Row) {
  dialog.row = row
  dialog.historyList = []
  dialog.history = true
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) throw new Error('经办记录读取失败')
    const detail = await response.json()
    dialog.historyList = detail.history ?? []
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '经办记录读取失败'
  }
}

async function refreshAll() {
  await reload()
  if (tab.value === 'roster') await loadRoster()
}

onMounted(async () => {
  await store.ensureActors()
  await reload()
})

// 切换经办人后，归属/岗位决定的按钮可用态要立刻按新身份重算。
watch(() => store.actorKey, () => {
  closeDialog()
  void refreshAll()
})
</script>
