/** 统一请求封装：拼后端地址、自动带操作人身份头、抛网络错误、给页脚留一句可读的说明。 */
import { useSessionStore } from '@/stores/session'

const API_BASE = import.meta.env.VITE_API_BASE ?? ''

export function request(path: string, init?: RequestInit): Promise<Response> {
  const url = path.startsWith('http') ? path : `${API_BASE}${path}`
  const session = useSessionStore()
  return fetch(url, {
    headers: { 'Content-Type': 'application/json', ...session.authHeaders, ...(init?.headers ?? {}) },
    ...init,
  }).catch((error: unknown) => {
    const detail = error instanceof Error ? error.message : '请求未送达'
    throw new Error(`接口请求失败：${detail}`)
  })
}

/** 动作接口统一返回 { ok, message }，把后端的驳回原因原样抛给页面。 */
export async function postAction(path: string, body: unknown): Promise<{ ok: boolean; message: string }> {
  const response = await request(path, { method: 'POST', body: JSON.stringify(body ?? {}) })
  if (response.status === 401 || response.status === 403) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null
    throw new Error(payload?.detail ?? `请求被拒绝（${response.status}）`)
  }
  const payload = (await response.json()) as { ok?: boolean; message?: string }
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.message ?? '操作未生效，请稍后重试')
  }
  return { ok: true, message: payload.message ?? '操作已生效' }
}

export async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await request(path, init)
  if (!response.ok) {
    let detail = ''
    try {
      const payload = (await response.json()) as { detail?: string }
      detail = payload.detail ?? ''
    } catch {
      // 非 JSON 错误体时忽略
    }
    throw new Error(detail || `接口返回 ${response.status}，数据未更新`)
  }
  return (await response.json()) as T
}
