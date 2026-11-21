---
title: "AGENTS.md — 通用多目的地旅遊跨社比價與異動監控雷達 AI 多代理協作架構"
aliases:
  - AGENTS
  - Agent Registry
  - 多代理架構手冊
tags:
  - agent-orchestration
  - multi-agent
  - routing
  - architecture
  - travel-radar
type: agent-manifest
created: 2026-11-19
updated: 2026-11-21
---

# AGENTS.md — 通用多目的地旅遊跨社比價與異動監控雷達 (`travel-radar`)

> **知識導航**：[[00_Index|🗺️ 00_Index (MOC 總索引)]] ｜ [[README|📘 README (專案導覽)]] ｜ [[2027_TravelLtinerary|📋 系統計畫規格書]] ｜ [[docs/api_spec|🔌 docs/api_spec]] ｜ [[ConversationRecord|📝 對話紀錄]] ｜ [[REMINDER|⚠️ 提醒事項]]  
> **強制規範**：所有 Agent 在開始任何任務前，必須先閱讀本文件與對應的專案 [[skills/okinawa-discovery/SKILL|skills/okinawa-discovery]]、[[skills/okinawa-extractor/SKILL|skills/okinawa-extractor]]、[[skills/okinawa-calculator/SKILL|skills/okinawa-calculator]] 及 [[2027_TravelLtinerary]]。

## 專案架構總覽

| 層級 | 技術棧 |
|------|--------|
| CLI / 排程 | `src/cli.py` (CLI-First)、GitHub Actions Cron + `data/radar.db` Commit 回 Repo |
| API / Service | Python 3.11+、FastAPI + Uvicorn（選配）、`httpx`、Pydantic v2、PyYAML (`config/trips/*.yaml`) |
| 爬蟲與解析 | `crawl4ai>=0.9.0`、Playwright (Chromium 混合備援)、`fast-flights>=3.1.0` |
| LLM 供應商 | Gemini API (`gemini/gemini-3.8-flash`) 或 Ollama (`ollama/qwen2.5:14b`) |
| 評估與推播 | `src/evaluator/` (`RuleEvaluator`, `DiffEngine`)、`src/notifier/` (`Rich`, Discord, Telegram) |
| 資料庫 | SQLite 3 (`aiosqlite` / `sqlite3` WAL + 事件驅動快照 + `scan_history`) |

---

## Global Definitions

### 共用狀態碼 / 列舉
- **旅行社名稱 (`agency`)**：`可樂旅遊` | `東南旅遊` | `雄獅旅遊` | `山富旅遊` | `世邦旅遊`
- **團次狀態 (`status`)**：`可報名` | `保證出團` | `候補` | `滿團`
- **出發機場 (`departure_airport`)**：`TPE` | `KHH` | `RMQ` | `OTHER`

### Deprecated Features
```yaml
deprecated_features: []
```

### 全域技術限制
- Python 版本須為 `3.11+`，資料驗證統一使用 **Pydantic v2**。
- 爬蟲併發度上限為 `1`（各旅行社依序執行），翻頁間隔隨機延遲 `2.0 ~ 4.5` 秒。
- 不可對已解析且未超過 7 天的團號重複呼叫 LLM。

---

## Agent Registry

```yaml
agent_registry:
  - id: agent-orchestrator
    role: COORDINATOR
    preferred_model: pro
  - id: agent-backend
    role: IMPLEMENTER
    layer: service
    preferred_model: flash
  - id: agent-database
    role: IMPLEMENTER
    layer: data
    preferred_model: flash
  - id: agent-qa
    role: VALIDATOR
    preferred_model: flash
  - id: agent-docs
    role: DOCUMENTER
    preferred_model: flash

routing_priority:
  1: deprecated_features
  2: cross_layer_task
  3: single_layer_match
  4: fallback
```

---

## Orchestrator (`agent-orchestrator`)

```yaml
agent_schema:
  id: agent-orchestrator
  role: COORDINATOR
  preferred_model: pro
  description: >
    負責任務拆解、DAG 排程與跨層協調。根據任務特徵將工作分派給
    agent-backend、agent-database、agent-qa 與 agent-docs，絕不直接撰寫實作程式碼。

  input_types:
    - user_request
  output_types:
    - task_assignment
    - final_summary
    - clarification_request

  triggers:
    - pattern: "所有使用者請求皆由 Orchestrator 統一接收與路由"

  excludes:
    - "直接撰寫 Python、SQL 或測試程式碼"

  depends_on: []
  can_parallel: false
  confidence_threshold: 0.80

  routing_rules:
    - condition: "任務涉及 FastAPI、爬蟲 Adapter、Crawl4AI、fast-flights 或預算試算邏輯"
      target: agent-backend
    - condition: "任務涉及 SQLite DDL、tours/price_snapshots/flight_benchmarks 資料表或 Repository 查詢"
      target: agent-database
    - condition: "任務涉及 pytest 單元測試、XHR 封包驗證或整合測試"
      target: agent-qa
    - condition: "任務涉及 api_spec.md、README.md 或 SKILL.md 文件更新"
      target: agent-docs
    - condition: "任務跨越資料庫與後端服務層"
      target: [agent-database, agent-backend, agent-qa]
      execution: SEQUENTIAL_WITH_DAG

  pipeline_templates:
    new_feature:
      dag:
        - step: 1
          agent: agent-database
          can_parallel: false
        - step: 2
          agent: agent-backend
          depends_on: [agent-database]
          can_parallel: false
        - step: 3
          agent: agent-qa
          depends_on: [agent-backend]
          can_parallel: true
        - step: 4
          agent: agent-docs
          depends_on: [agent-backend]
          can_parallel: true
    bug_fix:
      dag:
        - step: 1
          agent: agent-qa
          can_parallel: false
        - step: 2
          agent: agent-backend
          depends_on: [agent-qa]
          can_parallel: false
        - step: 3
          agent: agent-qa
          depends_on: [agent-backend]
          can_parallel: false

  prohibitions:
    - "禁止直接修改 src/、tests/ 或 SQLite schema"
  pending_decisions: []
```

---

## Backend Agent (`agent-backend`)

```yaml
agent_schema:
  id: agent-backend
  role: IMPLEMENTER
  preferred_model: flash
  layer: service
  description: >
    負責實作 FastAPI 端點、五大旅行社雙模式爬蟲 Adapter、Crawl4AI + LLM 詳情頁解析、
    fast-flights 機票基準查詢，以及家族真實總預算與告警偵測引擎。

  input_types:
    - api_endpoint_requirement
    - business_logic_spec
    - sql_result_schema

  output_types:
    - python_implementation
    - pydantic_schema
    - return_schema

  triggers:
    - keywords: ["FastAPI", "CLI", "Playwright", "Crawl4AI", "fast-flights", "httpx", "Adapter", "XHR", "Notifier"]
    - keywords: ["daily-run", "TourListItem", "TourPackage", "TripConfig", "budget_engine", "RuleEvaluator", "DiffEngine"]
    - pattern: "任務涉及 CLI、API 端點、爬蟲擷取、LLM 解析、規則評分、推播或預算/告警商業邏輯"

  excludes:
    - "直接撰寫或修改 SQLite DDL 結構"
    - "撰寫或執行 pytest 測試檔案"

  depends_on:
    - agent: agent-database
      reason: "Repository 介面與資料表欄位須先就緒"
      dependency_type: SOFT
  can_parallel: false
  confidence_threshold: 0.75

  required_skills:
    - path: "skills/okinawa-discovery/SKILL.md"
      mandatory: true
      reason: "五大旅行社雙模式爬蟲規範"
    - path: "skills/okinawa-extractor/SKILL.md"
      mandatory: true
      reason: "詳情頁增量解析與機票基準規範"
    - path: "skills/okinawa-calculator/SKILL.md"
      mandatory: true
      reason: "家族預算試算與告警規則"

  known_apis:
    - name: "daily_run"
      signature: "POST /api/v1/pipeline/daily-run"
      location: "src/main.py"
      status: ACTIVE
    - name: "health_check"
      signature: "GET /health"
      location: "src/main.py"
      status: ACTIVE
```

### 職責與規範
- 實作 `src/cli.py`、`src/discovery/`、`src/extractor/`、`src/calculator/`、`src/evaluator/`、`src/notifier/`、`src/services/` 與 `src/main.py`。
- 確保 `TripConfig`、`TourListItem` 與 `TourPackage`（含向後相容別名 `OkinawaTourPackage`）嚴格使用 Pydantic v2 驗證。

**Input Format**：`{ "task": "...", "target_files": [...], "constraints": [...] }`  
**Output Format**：`{ "modified_files": [...], "summary": "...", "status": "DONE|BLOCKED" }`

---

## Database Agent (`agent-database`)

```yaml
agent_schema:
  id: agent-database
  role: IMPLEMENTER
  preferred_model: flash
  layer: data
  description: >
    負責 SQLite 3 資料庫連線管理、DDL 初始化與 Repository 層實作，
    包含行程主表去重、每日價格快照寫入與增量解析比對查詢。

  input_types:
    - data_requirement
    - table_name
    - query_spec

  output_types:
    - sql_ddl
    - repository_method
    - column_schema

  triggers:
    - keywords: ["SQLite", "DDL", "aiosqlite", "repository", "snapshot", "tours", "price_snapshots", "flight_benchmarks"]
    - pattern: "任務涉及資料庫 Schema、SQL 查詢或資料持久化層"

  excludes:
    - "修改 FastAPI 路由、爬蟲 Adapter 或預算計算邏輯"

  depends_on: []
  can_parallel: true
  confidence_threshold: 0.75

  known_tables:
    active: ["tours", "price_snapshots", "flight_benchmarks", "alert_logs", "scan_history"]
    planned: []
    deprecated: []
```

### 職責與規範
- 維護 `src/db/database.py` 與 `src/db/repository.py`。
- 確保 `tour_uid` (`"{agency}:{tour_code}:{departure_date}"`) 作為主鍵進行冪等寫入。

**Input Format**：`{ "task": "...", "tables": [...], "query_requirements": [...] }`  
**Output Format**：`{ "modified_files": [...], "schema_changes": [...], "status": "DONE|BLOCKED" }`

---

## QA Agent (`agent-qa`)

```yaml
agent_schema:
  id: agent-qa
  role: VALIDATOR
  preferred_model: flash
  description: >
    負責撰寫與執行 pytest 單元測試、驗證預算試算與告警規則、以及檢查 XHR 攔截輔助腳本。

  input_types:
    - implemented_feature
    - bug_report
    - python_implementation

  output_types:
    - test_case
    - verification_report
    - bug_analysis

  triggers:
    - keywords: ["pytest", "test", "驗證", "單元測試", "inspect_xhr", "bug"]
    - pattern: "任務涉及測試撰寫、邏輯驗證或錯誤重現"

  excludes:
    - "修改 src/ 下的正式業務程式碼"

  depends_on:
    - agent: agent-backend
      reason: "需待後端模組實作完成後進行驗證"
      dependency_type: SOFT
  can_parallel: true
  confidence_threshold: 0.75
```

### 職責與規範
- 維護 `tests/test_budget_engine.py` 與 `tests/test_alert_detector.py`。

**Input Format**：`{ "target_module": "...", "test_scope": [...] }`  
**Output Format**：`{ "passed": int, "failed": int, "report": "..." }`

---

## Docs Agent (`agent-docs`)

```yaml
agent_schema:
  id: agent-docs
  role: DOCUMENTER
  preferred_model: flash
  description: >
    負責維護 docs/api_spec.md、README.md、專案 skills/ 與版本異動紀錄。

  input_types:
    - api_signature
    - feature_completion
    - column_schema

  output_types:
    - api_doc
    - changelog_entry

  triggers:
    - keywords: ["文件", "api_spec", "README", "SKILL.md", "changelog"]
    - pattern: "任務涉及規格文件更新或架構說明撰寫"

  excludes:
    - "修改任何 Python 程式碼或 SQL"

  depends_on: []
  can_parallel: true
  confidence_threshold: 0.75
```

**Input Format**：`{ "doc_target": "...", "changes": [...] }`  
**Output Format**：`{ "updated_files": [...], "status": "DONE" }`

---

## Context Firewall Rules

```yaml
context_firewall:
  rules:
    - id: CONTEXT_ISOLATION
      description: "每個 Sub-agent 僅接收其負責層級所需的檔案與規格上下文"
    - id: NO_DIRECT_COMMUNICATION
      description: "Sub-agent 之間禁止直接通訊，統一透過 Orchestrator 轉發"
    - id: SECRET_EXCLUSION
      description: "禁止在任何 Agent 上下文或日誌中暴露 GEMINI_API_KEY 等機密資訊"
    - id: LAYER_BOUNDARY
      description: "嚴格遵守各 Agent 的 excludes 邊界，禁止越權修改"
    - id: RESULT_ONLY_REPORT
      description: "Sub-agent 僅回報最終結果與異動清單"
```

---

## Orchestrator Auto-Routing Algorithm

```text
STEP 1  檢查 deprecated_features → 若命中則直接 REJECT
STEP 2  提取任務特徵 (input_type, output_need, keywords)
STEP 3  計算各 Agent 分數：triggers (+) 減去 excludes (-)
STEP 4  單一高分匹配 → 直接分派；跨層任務 → 依 pipeline_templates 建立 DAG；無匹配 → 向使用者釐清
```

---

## Version Changelog

| 版本 | 日期 | 異動摘要 |
|------|------|---------|
| v1.0 | 2026-11-19 | 依據 `2027_TravelLtinerary.md` 完成專案初始化，建立 5 個 Agent 定義與 3 個專案 Skills |
| v1.1 | 2026-11-21 | 參考 `tech-training-radar` 全面升級為不限國家地點之通用 `travel-radar` 架構（`config/trips/*.yaml`、`src/cli.py`、`src/evaluator/`、`src/notifier/`、`scan_history` 與 GitHub Actions Cron） |
