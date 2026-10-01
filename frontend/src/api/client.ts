/** 统一请求封装：拼后端地址、附带当前经办人、抛网络错误、给页脚留一句可读的说明。 */
const API_BASE = import.meta.env.VITE_API_BASE ?? ''

/** 读当前经办人 key（由会话 store 持久化到 localStorage）。 */
function actorHeaders(init?: RequestInit): HeadersInit {
  const headers = new Headers(init?.headers ?? { 'Content-Type': 'application/json' })
  if (!headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  try {
    const key = window.localStorage.getItem('operator.actorKey')
    if (key) headers.set('X-Actor-Key', key)
  } catch {
    // localStorage 不可用时退回匿名（后端会用默认经办人），不阻断页面
  }
  return headers
}

export function request(path: string, init?: RequestInit): Promise<Response> {
  const url = path.startsWith('http') ? path : `${API_BASE}${path}`
  return fetch(url, { ...init, headers: actorHeaders(init) }).catch((error: unknown) => {
    const detail = error instanceof Error ? error.message : '请求未送达'
    throw new Error(`接口请求失败：${detail}`)
  })
}

export async function fetchJson<T>(path: string): Promise<T> {
  const response = await request(path)
  if (!response.ok) {
    throw new Error(`接口返回 ${response.status}，数据未更新`)
  }
  return (await response.json()) as T
}
