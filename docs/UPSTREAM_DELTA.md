# 与上游 MiroFish 的差异

对比基准：https://github.com/666ghj/MiroFish 提交 `39d849138ef254f6c737ab4c4705e5545dbe31d4`（见 `source_info.json`）。
本文件由 `scripts/upstream-delta.py` 生成，只比较来自上游的目录（backend、frontend、locales 与根目录清单）。`local_studio/`、`desktop/`、`packaging/`、`scripts/`、`tests/`、`docs/` 是本衍生版自有的内容。

合并新的上游提交前，先看「已修改」一节：这些文件同时有本地改动和上游改动的风险最高。

## 已修改的上游文件（41）

| 文件 | 变动行数（增+删） |
| --- | ---: |
| `frontend/src/components/Step2EnvSetup.vue` | 921 |
| `frontend/src/components/Step4Report.vue` | 632 |
| `frontend/src/views/MainView.vue` | 527 |
| `backend/app/api/simulation.py` | 237 |
| `frontend/src/components/Step5Interaction.vue` | 207 |
| `backend/app/models/task.py` | 205 |
| `backend/app/services/simulation_runner.py` | 178 |
| `backend/tests/test_zep_simulation_barrier.py` | 177 |
| `frontend/src/components/Step1GraphBuild.vue` | 123 |
| `frontend/src/components/Step3Simulation.vue` | 100 |
| `backend/app/__init__.py` | 50 |
| `frontend/src/App.vue` | 44 |
| `backend/app/services/oasis_profile_generator.py` | 27 |
| `backend/app/utils/zep.py` | 26 |
| `backend/app/services/simulation_manager.py` | 21 |
| `backend/app/utils/logger.py` | 19 |
| `frontend/src/router/index.js` | 18 |
| `package.json` | 17 |
| `backend/app/config.py` | 16 |
| `backend/app/api/report.py` | 16 |
| `frontend/src/views/SimulationView.vue` | 15 |
| `frontend/src/views/SimulationRunView.vue` | 12 |
| `frontend/src/views/InteractionView.vue` | 12 |
| `frontend/src/views/ReportView.vue` | 10 |
| `backend/app/services/report_agent.py` | 10 |
| `frontend/src/store/pendingUpload.js` | 9 |
| `frontend/src/components/GraphPanel.vue` | 8 |
| `frontend/index.html` | 8 |
| `backend/app/api/graph.py` | 8 |
| `backend/app/services/zep_tools.py` | 7 |
| `frontend/vite.config.js` | 6 |
| `frontend/src/api/index.js` | 5 |
| `frontend/package.json` | 5 |
| `backend/run.py` | 5 |
| `frontend/package-lock.json` | 4 |
| `backend/app/models/project.py` | 4 |
| `backend/tests/test_zep_report_barrier.py` | 3 |
| `backend/pyproject.toml` | 2 |
| `backend/app/services/zep_graph_memory_updater.py` | 2 |
| `backend/app/services/zep_entity_reader.py` | 2 |
| `backend/app/services/graph_builder.py` | 2 |

## 本衍生版新增的文件（27）

- `backend/app/studio_runtime.py`
- `backend/app/utils/atomic_io.py`
- `backend/logs/2026-10-17.log`
- `backend/tests/e2e/conftest.py`
- `backend/tests/e2e/fake_llm.py`
- `backend/tests/e2e/fake_zep.py`
- `backend/tests/e2e/stub_scripts/run_parallel_simulation.py`
- `backend/tests/e2e/test_pipeline_graph.py`
- `backend/tests/e2e/test_pipeline_prepare.py`
- `backend/tests/e2e/test_pipeline_recovery.py`
- `backend/tests/e2e/test_pipeline_report.py`
- `backend/tests/e2e/test_pipeline_run.py`
- `backend/tests/test_atomic_io.py`
- `backend/tests/test_studio_checkpoints.py`
- `backend/tests/test_studio_prepare_idempotency.py`
- `backend/tests/test_studio_prepare_restore.py`
- `backend/tests/test_studio_report_reuse.py`
- `backend/tests/test_studio_task_persistence.py`
- `frontend/src/api/studio.js`
- `frontend/src/assets/studio-creation.css`
- `frontend/src/components/studio/StudioIcon.vue`
- `frontend/src/utils/costEstimate.js`
- `frontend/src/utils/reportMarkdown.js`
- `frontend/src/views/NewSimulationView.vue`
- `frontend/src/views/StudioView.vue`
- `frontend/tests/costEstimate.test.mjs`
- `frontend/tests/reportMarkdown.test.mjs`

## 上游有、本衍生版没有的文件（0）

（无）
