<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { CaretRight, VideoPause, Delete } from '@element-plus/icons-vue'

interface ApiResult {
  ok: boolean
  message?: string
}

interface PortField {
  enabled: boolean
  port: number
}

interface EndpointConfig {
  host: string
  vxi11: boolean
  hislip: PortField
  socket: PortField
}

type LogLevel = 'DEBUG' | 'INFO' | 'WARN' | 'ERROR'

interface PyApi {
  start_mapping: (source: EndpointConfig, target: EndpointConfig) => Promise<ApiResult>
  stop_mapping: () => Promise<ApiResult>
  get_status: () => Promise<{
    running: boolean
    source: EndpointConfig | null
    target: EndpointConfig | null
    log_level?: LogLevel
  }>
  get_default_endpoints: () => Promise<{ source: EndpointConfig; target: EndpointConfig }>
  get_persisted_state: () => Promise<{
    source: EndpointConfig | null
    target: EndpointConfig | null
    log_level: LogLevel
  }>
  set_log_level: (level: LogLevel) => Promise<ApiResult & { level?: LogLevel }>
}

interface LogEntry {
  level: string
  time: string
  msg: string
}

const STORAGE_KEYS = {
  // v2: structured config replaces VISA strings. Older keys are abandoned.
  form: 'visa-mapping-form-v2',
  logs: 'visa-mapping-logs',
} as const
const MAX_LOGS = 1000
const HISLIP_DEFAULT_PORT = 4880
const SOCKET_DEFAULT_PORT = 5025

function makeDefault(host: string): EndpointConfig {
  return {
    host,
    vxi11: true,
    hislip: { enabled: true, port: HISLIP_DEFAULT_PORT },
    socket: { enabled: true, port: SOCKET_DEFAULT_PORT },
  }
}

const form = reactive<{ source: EndpointConfig; target: EndpointConfig }>({
  source: makeDefault('0.0.0.0'),
  target: makeDefault('192.168.1.10'),
})

const running = ref(false)
const loading = ref(false)
const logs = ref<LogEntry[]>([])
const logBox = ref<HTMLDivElement>()
const formError = ref('')
const logLevel = ref<LogLevel>('INFO')

const LOG_LEVEL_OPTIONS: { value: LogLevel; label: string }[] = [
  { value: 'DEBUG', label: 'DEBUG' },
  { value: 'INFO', label: 'INFO' },
  { value: 'WARN', label: 'WARN' },
  { value: 'ERROR', label: 'ERROR' },
]

const LOG_LEVEL_PRIORITY: Record<string, number> = {
  DEBUG: 10,
  INFO: 20,
  SUCCESS: 20,
  WARN: 30,
  WARNING: 30,
  ERROR: 40,
}

const visibleLogs = computed(() => {
  const threshold = LOG_LEVEL_PRIORITY[logLevel.value] ?? 20
  return logs.value.filter(
    (entry) => (LOG_LEVEL_PRIORITY[entry.level.toUpperCase()] ?? 20) >= threshold,
  )
})

const buttonText = computed(() => (running.value ? '停止映射' : '开始映射'))
const buttonType = computed(() => (running.value ? 'danger' : 'primary'))
const buttonIcon = computed(() => (running.value ? VideoPause : CaretRight))

function readStorageItem(key: string) {
  try {
    return window.localStorage.getItem(key)
  } catch {
    return null
  }
}

function writeStorageItem(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value)
  } catch {
    // localStorage may be unavailable in restricted webview contexts.
  }
}

function isLogEntry(value: unknown): value is LogEntry {
  if (!value || typeof value !== 'object') return false
  const entry = value as Partial<LogEntry>
  return (
    typeof entry.level === 'string' &&
    typeof entry.time === 'string' &&
    typeof entry.msg === 'string'
  )
}

function isEndpointConfig(value: unknown): value is EndpointConfig {
  if (!value || typeof value !== 'object') return false
  const v = value as Partial<EndpointConfig>
  return (
    typeof v.host === 'string' &&
    typeof v.vxi11 === 'boolean' &&
    !!v.hislip &&
    typeof v.hislip.enabled === 'boolean' &&
    typeof v.hislip.port === 'number' &&
    !!v.socket &&
    typeof v.socket.enabled === 'boolean' &&
    typeof v.socket.port === 'number'
  )
}

function restoreForm() {
  const raw = readStorageItem(STORAGE_KEYS.form)
  if (!raw) return false
  try {
    const saved = JSON.parse(raw)
    if (saved && isEndpointConfig(saved.source) && isEndpointConfig(saved.target)) {
      Object.assign(form.source, saved.source)
      Object.assign(form.target, saved.target)
      return true
    }
  } catch {
    // ignore malformed
  }
  return false
}

function restoreLogs() {
  const raw = readStorageItem(STORAGE_KEYS.logs)
  if (!raw) return
  try {
    const saved = JSON.parse(raw)
    if (Array.isArray(saved)) {
      logs.value = saved.filter(isLogEntry).slice(-MAX_LOGS)
    }
  } catch {
    // ignore malformed saved state
  }
}

function persistForm() {
  writeStorageItem(STORAGE_KEYS.form, JSON.stringify({ source: form.source, target: form.target }))
}

function persistLogs() {
  writeStorageItem(STORAGE_KEYS.logs, JSON.stringify(logs.value.slice(-MAX_LOGS)))
}

const api = (): PyApi | null => {
  const w = window as unknown as { pywebview?: { api?: PyApi } }
  return w.pywebview?.api ?? null
}

async function waitForBridge(timeoutMs = 5000) {
  const start = Date.now()
  while (!api()) {
    if (Date.now() - start > timeoutMs) return false
    await new Promise((r) => setTimeout(r, 50))
  }
  return true
}

function levelTagType(level: string) {
  switch (level.toUpperCase()) {
    case 'ERROR':
      return 'danger'
    case 'SUCCESS':
      return 'success'
    case 'WARN':
    case 'WARNING':
      return 'warning'
    default:
      return 'info'
  }
}

function appendLog(entry: LogEntry) {
  logs.value.push(entry)
  if (logs.value.length > MAX_LOGS) {
    logs.value.splice(0, logs.value.length - MAX_LOGS)
  }
  persistLogs()
  nextTick(() => {
    if (logBox.value) {
      logBox.value.scrollTop = logBox.value.scrollHeight
    }
  })
}

function clearLogs() {
  logs.value = []
  persistLogs()
}

function validatePort(label: string, value: unknown): string | null {
  const n = typeof value === 'number' ? value : Number(value)
  if (!Number.isInteger(n) || n < 1 || n > 65535) {
    return `${label} 端口需在 1–65535 之间`
  }
  return null
}

function validateEndpoint(label: string, cfg: EndpointConfig): string | null {
  if (!cfg.host || !cfg.host.trim()) return `${label}: 主机 IP 不能为空`
  const anyEnabled = cfg.vxi11 || cfg.hislip.enabled || cfg.socket.enabled
  if (!anyEnabled) return `${label}: 至少需要勾选一个协议`
  if (cfg.hislip.enabled) {
    const e = validatePort(`${label} HiSLIP`, cfg.hislip.port)
    if (e) return e
  }
  if (cfg.socket.enabled) {
    const e = validatePort(`${label} SOCKET`, cfg.socket.port)
    if (e) return e
  }
  return null
}

restoreForm()
restoreLogs()
watch(form, persistForm, { deep: true })

async function onLogLevelChange(level: LogLevel) {
  logLevel.value = level
  const bridge = api()
  if (!bridge) return
  try {
    await bridge.set_log_level(level)
  } catch {
    // bridge errors are non-fatal — frontend filter still applies
  }
}

async function toggleMapping() {
  const bridge = api()
  if (!bridge) {
    ElMessage.error('后端尚未就绪')
    return
  }
  if (running.value) {
    loading.value = true
    try {
      const res = await bridge.stop_mapping()
      if (!res.ok) ElMessage.error(res.message || '停止失败')
      else running.value = false
    } finally {
      loading.value = false
    }
    return
  }

  const sourceErr = validateEndpoint('映射设备', form.source)
  const targetErr = validateEndpoint('目标设备', form.target)
  formError.value = sourceErr || targetErr || ''
  if (formError.value) {
    ElMessage.error(formError.value)
    return
  }

  loading.value = true
  try {
    const res = await bridge.start_mapping(form.source, form.target)
    if (!res.ok) {
      ElMessage.error(res.message || '启动失败')
      return
    }
    running.value = true
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  ;(window as unknown as { __pushLog: (e: LogEntry) => void }).__pushLog = appendLog

  const ready = await waitForBridge()
  if (!ready) {
    ElMessage.warning('未检测到 pywebview 后端，请通过 python app.py 启动')
    return
  }
  const bridge = api()!
  const status = await bridge.get_status()
  if (status.log_level) {
    logLevel.value = status.log_level
  }
  if (status.running) {
    running.value = true
    if (status.source) Object.assign(form.source, status.source)
    if (status.target) Object.assign(form.target, status.target)
    return
  }

  // Pickle in the OS temp dir is the source of truth for last-applied
  // inputs. Fall back to /get_default_endpoints when nothing is saved.
  const persisted = await bridge.get_persisted_state()
  if (persisted.log_level) {
    logLevel.value = persisted.log_level
  }
  if (persisted.source && isEndpointConfig(persisted.source)) {
    Object.assign(form.source, persisted.source)
  } else if (form.source.host === '0.0.0.0') {
    const defaults = await bridge.get_default_endpoints()
    Object.assign(form.source, defaults.source)
  }
  if (persisted.target && isEndpointConfig(persisted.target)) {
    Object.assign(form.target, persisted.target)
  }
})

onBeforeUnmount(() => {
  const w = window as unknown as { __pushLog?: unknown }
  delete w.__pushLog
})
</script>

<template>
  <div class="app-shell">
    <el-card class="panel" shadow="never">
      <template #header>
        <div class="panel-header">
          <span>VISA 设备映射工具</span>
          <el-tag :type="running ? 'success' : 'info'" effect="light" round>
            {{ running ? '运行中' : '已停止' }}
          </el-tag>
        </div>
      </template>

      <div class="endpoint-grid" :class="{ disabled: running || loading }">
        <section class="endpoint">
          <div class="endpoint-title">映射设备 (本地)</div>
          <div class="row">
            <label class="row-label">主机 IP</label>
            <el-input
              v-model="form.source.host"
              placeholder="0.0.0.0 或本机 IP"
              :disabled="running || loading"
              clearable
            />
          </div>
          <div class="row">
            <label class="row-label">支持协议</label>
            <div class="proto-list">
              <div class="proto-item">
                <el-checkbox v-model="form.source.vxi11" :disabled="running || loading">
                  VXI-11
                </el-checkbox>
                <span class="proto-hint">portmap 自动发现</span>
              </div>
              <div class="proto-item">
                <el-checkbox v-model="form.source.hislip.enabled" :disabled="running || loading">
                  HiSLIP
                </el-checkbox>
                <el-input-number
                  v-if="form.source.hislip.enabled"
                  v-model="form.source.hislip.port"
                  :min="1"
                  :max="65535"
                  :step="1"
                  :controls="false"
                  :disabled="running || loading"
                  class="port-input"
                />
              </div>
              <div class="proto-item">
                <el-checkbox v-model="form.source.socket.enabled" :disabled="running || loading">
                  SOCKET
                </el-checkbox>
                <el-input-number
                  v-if="form.source.socket.enabled"
                  v-model="form.source.socket.port"
                  :min="1"
                  :max="65535"
                  :step="1"
                  :controls="false"
                  :disabled="running || loading"
                  class="port-input"
                />
              </div>
            </div>
          </div>
        </section>

        <section class="endpoint">
          <div class="endpoint-title">目标设备 (远程)</div>
          <div class="row">
            <label class="row-label">主机 IP</label>
            <el-input
              v-model="form.target.host"
              placeholder="例如 192.168.1.10"
              :disabled="running || loading"
              clearable
            />
          </div>
          <div class="row">
            <label class="row-label">支持协议</label>
            <div class="proto-list">
              <div class="proto-item">
                <el-checkbox v-model="form.target.vxi11" :disabled="running || loading">
                  VXI-11
                </el-checkbox>
                <span class="proto-hint">portmap 自动发现</span>
              </div>
              <div class="proto-item">
                <el-checkbox v-model="form.target.hislip.enabled" :disabled="running || loading">
                  HiSLIP
                </el-checkbox>
                <el-input-number
                  v-if="form.target.hislip.enabled"
                  v-model="form.target.hislip.port"
                  :min="1"
                  :max="65535"
                  :step="1"
                  :controls="false"
                  :disabled="running || loading"
                  class="port-input"
                />
              </div>
              <div class="proto-item">
                <el-checkbox v-model="form.target.socket.enabled" :disabled="running || loading">
                  SOCKET
                </el-checkbox>
                <el-input-number
                  v-if="form.target.socket.enabled"
                  v-model="form.target.socket.port"
                  :min="1"
                  :max="65535"
                  :step="1"
                  :controls="false"
                  :disabled="running || loading"
                  class="port-input"
                />
              </div>
            </div>
          </div>
        </section>
      </div>

      <div v-if="formError" class="form-error">{{ formError }}</div>

      <div class="actions">
        <el-button
          :type="buttonType"
          :icon="buttonIcon"
          :loading="loading"
          size="large"
          @click="toggleMapping"
        >
          {{ buttonText }}
        </el-button>
      </div>
    </el-card>

    <el-card class="panel log-panel" shadow="never">
      <template #header>
        <div class="panel-header">
          <span>实时日志</span>
          <div class="log-actions">
            <el-select
              :model-value="logLevel"
              size="small"
              class="log-level-select"
              @update:model-value="(v: LogLevel) => onLogLevelChange(v)"
            >
              <el-option
                v-for="opt in LOG_LEVEL_OPTIONS"
                :key="opt.value"
                :label="opt.label"
                :value="opt.value"
              />
            </el-select>
            <el-button :icon="Delete" link @click="clearLogs">清空</el-button>
          </div>
        </div>
      </template>

      <div ref="logBox" class="log-box">
        <div v-if="!visibleLogs.length" class="log-empty">暂无日志</div>
        <div v-for="(entry, idx) in visibleLogs" :key="idx" class="log-line">
          <span class="log-time">{{ entry.time }}</span>
          <el-tag :type="levelTagType(entry.level)" size="small" disable-transitions>
            {{ entry.level }}
          </el-tag>
          <span class="log-msg">{{ entry.msg }}</span>
        </div>
      </div>
    </el-card>
  </div>
</template>

<style>
html,
body,
#app {
  height: 100%;
  margin: 0;
  background: #f5f7fa;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
}
</style>

<style scoped>
.app-shell {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 16px;
  height: 100vh;
  box-sizing: border-box;
}

.panel {
  border-radius: 8px;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: 600;
}

.endpoint-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

@media (max-width: 720px) {
  .endpoint-grid {
    grid-template-columns: 1fr;
  }
}

.endpoint {
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  padding: 12px 16px;
  background: #fafafa;
}

.endpoint-title {
  font-weight: 600;
  margin-bottom: 12px;
  color: #303133;
}

.row {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 12px;
}

.row:last-child {
  margin-bottom: 0;
}

.row-label {
  flex-shrink: 0;
  width: 76px;
  color: #606266;
  font-size: 14px;
  line-height: 32px;
}

.proto-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  flex: 1;
}

.proto-item {
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 32px;
}

.proto-hint {
  color: #909399;
  font-size: 12px;
}

.port-input {
  width: 110px;
}

.form-error {
  color: var(--el-color-danger);
  font-size: 13px;
  margin-top: 8px;
}

.actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}

.log-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
}

.log-panel :deep(.el-card__body) {
  flex: 1;
  display: flex;
  flex-direction: column;
  padding: 0;
}

.log-box {
  flex: 1;
  overflow-y: auto;
  background: #1e1e1e;
  color: #d4d4d4;
  padding: 12px 16px;
  font-family: 'Consolas', 'Menlo', 'Courier New', monospace;
  font-size: 13px;
  line-height: 1.6;
  border-radius: 0 0 8px 8px;
}

.log-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.log-level-select {
  width: 110px;
}

.log-empty {
  color: #888;
  font-style: italic;
}

.log-line {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 2px 0;
  white-space: pre-wrap;
  word-break: break-all;
}

.log-time {
  color: #888;
  flex-shrink: 0;
}

.log-msg {
  flex: 1;
}
</style>
