<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { CaretRight, VideoPause, Delete } from '@element-plus/icons-vue'

interface ApiResult {
  ok: boolean
  message?: string
}

interface PyApi {
  start_mapping: (source: string, target: string) => Promise<ApiResult>
  stop_mapping: () => Promise<ApiResult>
  validate_address: (addr: string) => Promise<ApiResult>
  get_status: () => Promise<{ running: boolean; source: string | null; target: string | null }>
}

interface LogEntry {
  level: string
  time: string
  msg: string
}

const VISA_RE = /^TCPIP\d*::[A-Za-z0-9_.\-]+(?:::[A-Za-z0-9_]+)?::INSTR$/i

const formRef = ref<FormInstance>()
const form = reactive({
  source: 'TCPIP::127.0.0.1::inst0::INSTR',
  target: 'TCPIP::192.168.1.10::inst0::INSTR',
})
const running = ref(false)
const loading = ref(false)
const logs = ref<LogEntry[]>([])
const logBox = ref<HTMLDivElement>()

const rules: FormRules = {
  source: [
    { required: true, message: '请输入映射设备地址', trigger: 'blur' },
    {
      pattern: VISA_RE,
      message: '格式: TCPIP[board]::host[::device]::INSTR',
      trigger: 'blur',
    },
  ],
  target: [
    { required: true, message: '请输入目标设备地址', trigger: 'blur' },
    {
      pattern: VISA_RE,
      message: '格式: TCPIP[board]::host[::device]::INSTR',
      trigger: 'blur',
    },
  ],
}

const buttonText = computed(() => (running.value ? '停止映射' : '开始映射'))
const buttonType = computed(() => (running.value ? 'danger' : 'primary'))
const buttonIcon = computed(() => (running.value ? VideoPause : CaretRight))

const api = (): PyApi | null => {
  // pywebview injects window.pywebview.api once the bridge is ready.
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
  if (logs.value.length > 1000) {
    logs.value.splice(0, logs.value.length - 1000)
  }
  nextTick(() => {
    if (logBox.value) {
      logBox.value.scrollTop = logBox.value.scrollHeight
    }
  })
}

function clearLogs() {
  logs.value = []
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

  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

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
  if (status.running) {
    running.value = true
    if (status.source) form.source = status.source
    if (status.target) form.target = status.target
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

      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-width="120px"
        :disabled="running || loading"
      >
        <el-form-item label="映射设备地址" prop="source">
          <el-input
            v-model="form.source"
            placeholder="TCPIP::127.0.0.1::inst0::INSTR"
            clearable
          />
        </el-form-item>
        <el-form-item label="目标设备地址" prop="target">
          <el-input
            v-model="form.target"
            placeholder="TCPIP::192.168.1.10::inst0::INSTR"
            clearable
          />
        </el-form-item>
      </el-form>

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
          <el-button :icon="Delete" link @click="clearLogs">清空</el-button>
        </div>
      </template>

      <div ref="logBox" class="log-box">
        <div v-if="!logs.length" class="log-empty">暂无日志</div>
        <div v-for="(entry, idx) in logs" :key="idx" class="log-line">
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

.actions {
  display: flex;
  justify-content: flex-end;
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
