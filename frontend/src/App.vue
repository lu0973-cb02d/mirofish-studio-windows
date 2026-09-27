<template>
  <router-view />
</template>

<script setup>
// 使用 Vue Router 来管理页面
</script>

<style>
/* 全局样式重置 */
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

#app {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Microsoft YaHei', 'Noto Sans SC', sans-serif;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  color: #000000;
  background-color: #ffffff;
}

/* 滚动条样式 */
::-webkit-scrollbar {
  width: 8px;
  height: 8px;
}

::-webkit-scrollbar-track {
  background: #f1f1f1;
}

::-webkit-scrollbar-thumb {
  background: #a0b3a8;
  border-radius: 6px;
}

::-webkit-scrollbar-thumb:hover {
  background: #708d7d;
}

/* 全局按钮样式 */
button {
  font-family: inherit;
}

/* The five-stage workspace shares the Studio palette and typography. */
#app .main-view { background:#f6f7f5; font-family:'Segoe UI','Microsoft YaHei',sans-serif; }
#app .main-view .app-header { background:#152824; color:#ecf2ed; border-bottom:1px solid #263e33; min-height:64px; }
#app .main-view .app-header .brand { color:#ecf2ed; text-decoration:none; font-family:inherit; font-size:20px; letter-spacing:-.5px; display:flex; align-items:baseline; gap:7px; }
#app .main-view .app-header .brand span { font-size:12px; color:#aec7b6; font-weight:400; letter-spacing:.7px; }
#app .main-view .app-header .step-num { color:#a6bfaf; }
#app .main-view .app-header .step-name { color:#eff4f0; }
#app .main-view .app-header .view-switcher { background:#263e33; border:1px solid #385044; border-radius:8px; }
#app .main-view .app-header .switch-btn { color:#bfd0c4; background:transparent; border-radius:5px; }
#app .main-view .app-header .switch-btn.active { color:#183c2a; background:#e9f3ea; }
#app .main-view .app-header .status-indicator { color:#d8e8dd; }
#app .main-view .app-header .status-indicator.error { color:#ffc3aa; }
#app .main-view .content-area { padding:9px; background:#f6f7f5; }
#app .main-view .panel-wrapper { padding:5px; background:transparent; }
#app .main-view .panel-wrapper > div { border:1px solid #dfe7df; border-radius:12px; overflow:hidden; font-family:'Segoe UI','Microsoft YaHei',sans-serif; }
#app .main-view .action-btn.primary, #app .main-view .next-btn { background:#147d64; border-color:#147d64; border-radius:7px; }
@media(max-width:800px) { #app .main-view .app-header .step-divider { display:none; } #app .main-view .content-area { padding:3px; } }
</style>
