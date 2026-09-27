<template>
  <svg class="studio-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">
    <path v-for="(path, index) in paths[name] || paths.spark" :key="index" :d="path" />
  </svg>
</template>

<script setup>
defineProps({ name: { type: String, default: 'spark' } })
const paths = {
  spark: ['M12 3l2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5L12 3Z'],
  grid: ['M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z'],
  cpu: ['M7 7h10v10H7zM9 3v4m6-4v4M9 17v4m6-4v4M3 9h4m-4 6h4m10-6h4m-4 6h4M10 10h4v4h-4z'],
  link: ['M10 13a5 5 0 007 .2l3-3a5 5 0 00-7-7l-1.7 1.7', 'M14 11a5 5 0 00-7-.2l-3 3a5 5 0 007 7l1.7-1.7'],
  archive: ['M3 3h18v5H3zM5 8v13h14V8M9 12h6'],
  arrow: ['M4 12h16m-6-6l6 6-6 6'],
  plus: ['M12 5v14M5 12h14'],
  play: ['M8 4l12 8-12 8V4Z'],
  stop: ['M6 6h12v12H6z'],
  refresh: ['M20 7a9 9 0 00-15-2L2 8m0-6v6h6', 'M4 17a9 9 0 0015 2l3-3m0 6v-6h-6'],
  check: ['M5 12l4 4L19 6'],
  chevron: ['M9 5l7 7-7 7'],
  edit: ['M16 3l5 5M4 20l5-1L21 7a2.1 2.1 0 00-4-4L5 15l-1 5ZM13 20h8'],
  trash: ['M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7'],
  eye: ['M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z', 'M15 12a3 3 0 11-6 0 3 3 0 016 0Z'],
  'eye-off': ['M3 3l18 18M10.5 5.1A12 12 0 0112 5c6.5 0 10 7 10 7a17 17 0 01-3 3.8M6 6.2A18 18 0 002 12s3.5 7 10 7a13 13 0 006-1.8M9.9 9.9a3 3 0 004.2 4.2'],
  close: ['M6 6l12 12M6 18L18 6'],
  download: ['M12 3v12m-5-5l5 5 5-5M4 15v6h16v-6'],
  clock: ['M21 12a9 9 0 11-18 0 9 9 0 0118 0ZM12 7v5l3 2'],
  folder: ['M3 6a2 2 0 012-2h5l2 3h7a2 2 0 012 2v10a2 2 0 01-2 2H5a2 2 0 01-2-2V6Z'],
  file: ['M14 2H5v20h14V7l-5-5ZM14 2v6h5M8 12h8m-8 4h6'],
  external: ['M14 3h7v7M10 14L21 3M10 3H3v18h18v-7'],
  loader: ['M21 12a9 9 0 11-9-9'],
  search: ['M17 10a7 7 0 11-14 0 7 7 0 0114 0ZM15 15l6 6'],
  shield: ['M12 2l9 4v6c0 5-9 10-9 10S3 17 3 12V6l9-4ZM8 12l3 3 5-6'],
  power: ['M12 2v10M6 5a9 9 0 1012 0'],
  info: ['M21 12a9 9 0 11-18 0 9 9 0 0118 0ZM12 11v6M12 7h.01'],
  activity: ['M2 12h5l3-8 4 16 3-8h5'],
  menu: ['M4 6h16M4 12h16M4 18h16'],
  copy: ['M9 9h12v12H9zM15 9V3H3v12h6']
}
</script>

<style scoped>
.studio-icon { display: inline-block; width: 20px; height: 20px; flex: 0 0 auto; vertical-align: middle; }
</style>
