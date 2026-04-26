<script setup lang="ts">
import { useProxy } from '@/composables/useProxy'

const { logs, autoScroll, logBody, clearLog, lineLevel } = useProxy()
</script>

<template>
  <div class="card log-card">
    <div class="log-header">
      <span>Connection Log</span>
      <span class="spacer"></span>
      <label class="auto-scroll-toggle">
        <input v-model="autoScroll" type="checkbox" /> auto-scroll
      </label>
      <button class="btn-clear" @click="clearLog">Clear</button>
    </div>
    <div ref="logBody" class="log-body">
      <div
        v-for="entry in logs"
        :key="entry.id"
        class="log-line"
        :class="lineLevel(entry.text)"
      >
        {{ entry.text }}
      </div>
    </div>
  </div>
</template>

<style scoped>
.auto-scroll-toggle {
  display: flex;
  align-items: center;
  gap: 4px;
  cursor: pointer;
}
</style>
