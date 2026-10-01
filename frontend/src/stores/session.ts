import { defineStore } from 'pinia'

export type OperatorRole = '证书管理员' | '只读岗'

export interface Identity {
  name: string
  role: OperatorRole
  unit: string
}

/** 预置值班身份，便于演示本单位经办、跨单位代办与只读岗三种场景。 */
export const IDENTITY_PRESETS: Identity[] = [
  { name: '林芳', role: '证书管理员', unit: '华东热力分公司' },
  { name: '许磊', role: '证书管理员', unit: '江北电梯维保中心' },
  { name: '高敏', role: '证书管理员', unit: '宏远装卸运输队' },
  { name: '外协老高', role: '证书管理员', unit: '外协检修公司' },
  { name: '见习员小钱', role: '只读岗', unit: '华东热力分公司' },
]

const STORAGE_KEY = 'operator-identity'

function loadIdentity(): Identity {
  const raw = window.localStorage.getItem(STORAGE_KEY)
  if (raw) {
    try {
      return JSON.parse(raw) as Identity
    } catch {
      // 落盘内容损坏时回落到默认身份
    }
  }
  return { ...IDENTITY_PRESETS[0] }
}

export const useSessionStore = defineStore('session', {
  state: () => {
    const identity = loadIdentity()
    return {
      operator: identity.name,
      shiftLabel: '白班 08:00-20:00',
      scope: '特种设备安全管理平台',
      role: identity.role,
      unit: identity.unit,
    }
  },
  getters: {
    canOperate: (state) => state.operator.length > 0,
    identity: (state): Identity => ({ name: state.operator, role: state.role as OperatorRole, unit: state.unit }),
    isViewer: (state) => state.role === '只读岗',
    authHeaders(state): Record<string, string> {
      // HTTP 头只接受 ASCII：姓名、单位做百分号编码，岗位走角色码。
      return {
        'X-Operator-Name': encodeURIComponent(state.operator),
        'X-Operator-Role': state.role === '只读岗' ? 'viewer' : 'admin',
        'X-Operator-Unit': encodeURIComponent(state.unit),
      }
    },
  },
  actions: {
    setIdentity(identity: Identity) {
      this.operator = identity.name
      this.role = identity.role
      this.unit = identity.unit
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(identity))
    },
    setShift(label: string) {
      this.shiftLabel = label
    },
  },
})
