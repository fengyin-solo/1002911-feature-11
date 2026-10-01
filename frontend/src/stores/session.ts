import { defineStore } from 'pinia'

export interface ActorInfo {
  key: string
  name: string
  unit: string
  role: string
  delegatedUnits: string[]
  writable: boolean
}

/**
 * 会话态：当前经办人（单位 + 岗位 + 跨单位代办授权）。
 * 平台没有真正登录，这里用后端 /api/operator/actors 下发的可切换身份模拟，
 * 切换后所有写请求都会带上 X-Actor-Key，由后端做归属与岗位判定。
 */
export const useSessionStore = defineStore('session', {
  state: () => ({
    operator: '值班管理员',
    shiftLabel: '白班 08:00-20:00',
    scope: '特种设备安全管理平台',
    actors: [] as ActorInfo[],
    actorKey: '',
    loaded: false,
  }),
  getters: {
    canOperate: (state) => state.operator.length > 0,
    actor(state): ActorInfo | null {
      return state.actors.find((item) => item.key === state.actorKey) ?? null
    },
    /** 当前身份是否为证书管理员（可写岗）。只读岗为 false。 */
    isCertAdmin(): boolean {
      return this.actor?.writable === true
    },
    /** 当前经办人归属单位。 */
    currentUnit(): string {
      return this.actor?.unit ?? ''
    },
  },
  actions: {
    async ensureActors(force = false) {
      if (this.loaded && !force) return
      const resp = await fetch('/api/operator/actors')
      if (!resp.ok) return
      const payload = (await resp.json()) as { items: ActorInfo[] }
      this.actors = payload.items ?? []
      const saved = window.localStorage.getItem('operator.actorKey')
      this.actorKey = (saved && this.actors.some((a) => a.key === saved))
        ? saved
        : (this.actors[0]?.key ?? '')
      this.syncOperator()
      this.loaded = true
    },
    setActor(key: string) {
      this.actorKey = key
      window.localStorage.setItem('operator.actorKey', key)
      this.syncOperator()
    },
    syncOperator() {
      const current = this.actor
      if (current) {
        this.operator = current.name
        this.scope = current.unit
      }
    },
    setShift(label: string) {
      this.shiftLabel = label
    },
  },
})
