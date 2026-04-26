export interface ProxyResult {
  ok: boolean
  message: string
}

export interface ProxyStatusPayload {
  running: boolean
  info?: Record<string, unknown>
}

interface PywebviewApi {
  get_local_ip(): Promise<string>
  get_status(): Promise<{ running: boolean }>
  start_proxy(
    target: string,
    bind: string,
    deviceName: string,
  ): Promise<ProxyResult>
  stop_proxy(): Promise<ProxyResult>
}

declare global {
  interface Window {
    pywebview?: { api: PywebviewApi }
    proxyApp?: {
      appendLog(msg: string): void
      appendLogs(msgs: string[]): void
      onStatus(payload: ProxyStatusPayload): void
      onFatalError(payload: { message: string }): void
    }
  }
}

export {}
