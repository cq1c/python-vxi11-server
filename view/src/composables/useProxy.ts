import { reactive, ref, nextTick } from 'vue'
import type { ProxyStatusPayload } from '@/types/pywebview'

interface LogEntry {
  id: number
  text: string
}

const form = reactive({
  target: '',
  bind: '0.0.0.0',
  deviceName: 'inst0',
})
const running = ref(false)
const busy = ref(false)
const logs = ref<LogEntry[]>([])
const autoScroll = ref(true)
const toast = ref('')
const logBody = ref<HTMLElement | null>(null)

let nextId = 1
let scrollScheduled = false
let toastTimer: ReturnType<typeof setTimeout> | undefined

function showToast(msg: string) {
  toast.value = msg
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => (toast.value = ''), 4000)
}

function lineLevel(line: string) {
  if (/\bERROR\b|\bFATAL\b/.test(line)) return 'error'
  if (/\bWARN(ING)?\b/.test(line)) return 'warn'
  return 'info'
}

function scheduleScroll() {
  if (scrollScheduled || !autoScroll.value) return
  scrollScheduled = true
  nextTick(() => {
    scrollScheduled = false
    if (logBody.value) logBody.value.scrollTop = logBody.value.scrollHeight
  })
}

function appendLog(msg: string) {
  logs.value.push({ id: nextId++, text: msg })
  if (logs.value.length > 5000) logs.value.splice(0, 1000)
  scheduleScroll()
}

function appendLogs(arr: string[]) {
  if (!arr || !arr.length) return
  const items: LogEntry[] = new Array(arr.length)
  for (let i = 0; i < arr.length; i++) items[i] = { id: nextId++, text: arr[i] }
  logs.value.push(...items)
  if (logs.value.length > 5000) logs.value.splice(0, logs.value.length - 4000)
  scheduleScroll()
}

function onStatus(payload: ProxyStatusPayload) {
  running.value = !!payload.running
}

function onFatalError(payload: { message: string }) {
  showToast('Fatal: ' + payload.message)
  running.value = false
}

function clearLog() {
  logs.value = []
}

// Reverse channel: Python pushes log/status into the page by calling
// window.proxyApp.<fn>(). Register synchronous handlers — never `async`,
// or pywebview's bridge will try to serialize the returned Promise and
// recurse on window.native.AccessibilityObject.Bounds.Empty.Empty...
function registerBridge() {
  window.proxyApp = { appendLog, appendLogs, onStatus, onFatalError }
}

async function init() {
  registerBridge()
  appendLog('[ready] GUI initialized. Fill in source device and click Start.')

  const api = window.pywebview?.api
  if (!api) return

  try {
    const ip = await api.get_local_ip()
    if (ip && form.bind === '0.0.0.0') form.bind = ip
  } catch {
    /* keep default */
  }

  try {
    const status = await api.get_status()
    running.value = !!status.running
  } catch {
    /* ignore */
  }
}

async function onStart() {
  const api = window.pywebview?.api
  if (!api) return
  busy.value = true
  try {
    const r = await api.start_proxy(
      form.target.trim(),
      form.bind.trim() || '0.0.0.0',
      form.deviceName.trim() || 'inst0',
    )
    if (!r.ok) showToast(r.message)
    else running.value = true
  } finally {
    busy.value = false
  }
}

async function onStop() {
  const api = window.pywebview?.api
  if (!api) return
  busy.value = true
  try {
    const r = await api.stop_proxy()
    if (!r.ok) showToast(r.message)
    else running.value = false
  } finally {
    busy.value = false
  }
}

export function useProxy() {
  return {
    form,
    running,
    busy,
    logs,
    autoScroll,
    toast,
    logBody,
    init,
    onStart,
    onStop,
    clearLog,
    lineLevel,
  }
}
