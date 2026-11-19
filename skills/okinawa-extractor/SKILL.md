---
name: okinawa-extractor
description: >
  模組二：詳情頁結構化解析（Crawl4AI + LLM）與同期機票基準查詢（fast-flights）。
  僅針對新上架團號或超過 7 天未更新的行程觸發 LLM 解析，大幅節省 Token 成本。
aliases:
  - okinawa-extractor
  - 模組二：詳情頁解析與機票基準
tags:
  - skill
  - extractor
  - crawl4ai
  - llm
  - fast-flights
  - okinawa-2027
type: skill
created: 2026-11-19
---

# 模組二：詳情頁解析與機票基準 (`src/extractor/`) 開發規範

> **知識導航**：[[00_Index|🗺️ 00_Index (MOC)]] ｜ [[2027_TravelLtinerary|📋 系統計畫規格書]] ｜ [[AGENTS|🤖 多代理協作]] ｜ [[docs/api_spec|🔌 API規格書]]  
> **關聯模組**：[[skills/okinawa-discovery/SKILL|🕷️ 模組一：okinawa-discovery]] ｜ [[skills/okinawa-calculator/SKILL|💰 模組三：okinawa-calculator]]

---

## 核心邏輯

- **兩段式增量解析**：只有當 `tours` 表中無該 `tour_uid`，或 `detail_parsed_at` 超過 7 天時，才呼叫 `detail_crawler.py`。
- **Crawl4AI + LLM**：使用 `LLMExtractionStrategy` 將行程詳情頁解析為統一的 `OkinawaTourPackage` (`src/schemas/tour_schema.py`)，並透過環境變數切換 Gemini API (`gemini/gemini-2.5-flash`) 或 Ollama (`ollama/qwen2.5:14b`)。
- **機票基準 (`flight_benchmark.py`)**：使用 `fast-flights>=3.1.0` 查詢 `TPE/KHH <-> OKA` 同期直飛機票基準價，寫入 `flight_benchmarks` 表供跟團性價比對照。
- 解析後的完整結構與機票基準將交由 [[skills/okinawa-calculator/SKILL|模組三：家族總預算試算]] 進行綜合計價與風險標註。

## 已知地雷 / Gotchas

- 不可對已解析且未過期的團號重複呼叫 LLM，以免造成 Token 浪費。
- 詳情頁可能包含購物站、自費項目、小費與單人房差等非結構化文字，Prompt 需明確要求提取這些欄位。

## 檔案範圍

| 檔案 / 目錄 | 說明 | 關聯文檔 |
|------------|------|---------|
| `src/extractor/detail_crawler.py` | Crawl4AI + LLMExtractionStrategy 封裝 | [[2027_TravelLtinerary]] 第 3.2 節 |
| `src/extractor/flight_benchmark.py` | fast-flights 查詢 TPE/KHH <-> OKA | [[docs/api_spec]] `flight_benchmarks` |
| `src/schemas/tour_schema.py` | 統一 `OkinawaTourPackage` Pydantic 模型 | [[2027_TravelLtinerary]] 核心資料模型 |
