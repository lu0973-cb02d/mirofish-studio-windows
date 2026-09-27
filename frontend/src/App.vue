<template>
  <div v-if="isDesktop" class="desktop-titlebar"><img src="/icon.png" alt="" /><span>MiroFish Studio</span><span class="desktop-titlebar-caption">本地推演工作台</span></div>
  <router-view />
</template>

<script setup>
const isDesktop = Boolean(window.mirofishDesktop)
document.documentElement.classList.toggle('desktop-runtime', isDesktop)
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

.desktop-runtime { --desktop-titlebar-height: 40px; }
.desktop-runtime #app { padding-top: var(--desktop-titlebar-height); }
.desktop-titlebar { position:fixed; inset:0 0 auto; height:40px; padding:0 154px 0 15px; display:flex; align-items:center; gap:8px; background:#f4f7fb; border-bottom:1px solid #e2e8f0; color:#40506a; font:600 12px 'Segoe UI','Microsoft YaHei',sans-serif; z-index:500; -webkit-app-region:drag; user-select:none; }
.desktop-titlebar img { width:18px; height:18px; border-radius:5px; }
.desktop-titlebar-caption { margin-left:7px; padding-left:12px; border-left:1px solid #ccd6e2; color:#607089; font-size:11px; font-weight:400; }
.desktop-runtime #app .studio-sidebar { top:40px; height:calc(100vh - 40px); min-height:0; }
.desktop-runtime #app .studio-shell, .desktop-runtime #app .studio-main, .desktop-runtime #app .new-workspace { min-height:calc(100vh - 40px); }
.desktop-runtime #app .studio-main .topbar { top:40px; }
.desktop-runtime #app .main-view { height:calc(100vh - 40px); }

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
#app .main-view { background:#f4f7fb; font-family:'Segoe UI','Microsoft YaHei',sans-serif; }
#app .main-view .app-header { background:#111c2e; color:#ecf2f9; border-bottom:1px solid #263a51; min-height:64px; }
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
#app .main-view :is(button,a) { transition:background .18s,color .18s,border-color .18s,box-shadow .18s,transform .18s; }
#app .main-view :is(.action-btn.primary,.next-btn):hover:not(:disabled) { background:#087960; border-color:#087960; box-shadow:0 4px 12px #0d8a7030; }
#app .main-view :is(.action-btn,.next-btn):active:not(:disabled) { transform:scale(.985); }
#app .main-view :is(button,a):focus-visible { outline:3px solid #70baa8; outline-offset:3px; }
@media(prefers-reduced-motion:reduce) { #app .main-view :is(button,a) { transition:none; } }
@media(max-width:800px) { #app .main-view .app-header .step-divider { display:none; } #app .main-view .content-area { padding:3px; } }
</style>
