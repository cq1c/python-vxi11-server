<script setup lang="ts">
import { onMounted, ref } from 'vue'
import ProxyForm from '@/components/ProxyForm.vue'
import ProxyLog from '@/components/ProxyLog.vue'
import { useProxy } from '@/composables/useProxy'

const { toast, init } = useProxy()
const ready = ref(false)

function initBridge() {
  ready.value = true
  window.removeEventListener('pywebviewready', listener)
  void init()
}

const listener = () => initBridge()

onMounted(() => {
  if (window.pywebview) {
    initBridge()
  } else {
    window.addEventListener('pywebviewready', listener, { once: true })
  }
})
</script>

<template>
  <div v-if="ready" id="app-root">
    <h1>VXI-11 Proxy</h1>
    <ProxyForm />
    <ProxyLog />
    <div v-if="toast" class="toast">{{ toast }}</div>
  </div>
</template>
