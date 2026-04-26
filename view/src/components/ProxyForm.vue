<script setup lang="ts">
import { useProxy } from '@/composables/useProxy'

const { form, running, busy, onStart, onStop } = useProxy()
</script>

<template>
  <div class="card">
    <div class="row">
      <div class="field">
        <label>Source Device (the real upstream instrument)</label>
        <input
          v-model="form.target"
          :disabled="running"
          placeholder="e.g. 192.168.1.50  or  TCPIP::192.168.1.50::inst0::INSTR"
        />
      </div>
    </div>
    <div class="row">
      <div class="field" style="flex: 2">
        <label>Local Bind Address (this machine's IP)</label>
        <input v-model="form.bind" :disabled="running" placeholder="0.0.0.0" />
      </div>
      <div class="field">
        <label>Exposed Device Name</label>
        <input
          v-model="form.deviceName"
          :disabled="running"
          placeholder="inst0"
        />
      </div>
    </div>
    <div class="row actions">
      <button class="btn-start" :disabled="running || busy" @click="onStart">
        Start Proxy
      </button>
      <button class="btn-stop" :disabled="!running || busy" @click="onStop">
        Stop
      </button>
      <div class="status">
        <span class="dot" :class="running ? 'on' : 'off'"></span>
        <span>{{ running ? 'Running' : 'Stopped' }}</span>
      </div>
    </div>
  </div>
</template>
