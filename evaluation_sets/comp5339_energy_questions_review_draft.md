# COMP5339 Energy Assignments - Questions for Human Review

這份才是給你手動 review 的題目草稿。每題都是多選題（MAQ），有 4 個選項、1 至 3 個正確答案。請直接修改題目、選項、答案或 evidence cell；確認後可再轉成正式 gold set。

## Assignment 1 - Data Integration and Augmentation

### Q1 - Download and local-file fallback

**Target difficulty:** 3 / 5

**Evidence:** `energy-etl-pipeline.ipynb`, cell 10 (`check_file_exists`, `download_file`)

**Question:** 關於此 notebook 的資料取得流程，下列哪些敘述正確？

- A. 它會先檢查多個可能的本機路徑，再決定是否下載檔案。
- B. 找不到檔案時，它會將下載內容存入目前工作目錄下的 `data/` 資料夾。
- C. 每次使用者重新執行下載 cell 時，即使候選本機路徑已找到檔案，程式仍會重新下載並覆寫該檔案。
- D. 若伺服器回傳非成功 HTTP status 但仍附帶 response body，`download_file` 會把該 body 當成有效 dataset 寫入檔案。

**Correct answers:** A, B

**Reason:** `check_file_exists` 逐一檢查候選 path，只有全部不存在才建立 `data/` 並下載；`download_file` 會先呼叫 `raise_for_status()`。

### Q2 - Cleaning annual NGER data

**Target difficulty:** 3 / 5

**Evidence:** `energy-etl-pipeline.ipynb`, cell 21 (`_coalesce_duplicate_columns` and NGER cleaning)

**Question:** 此 notebook 如何處理合併多年份 NGER 檔案後的資料一致性？

- A. 將舊欄位名稱重新命名為統一的欄位名稱。
- B. 對重複欄位逐列保留第一個非空值。
- C. 清洗後的 NGER 與 ECON 欄位會統一轉為 pandas 的 string dtype，讓後續合併不受資料型別影響。
- D. 對指定的數值欄位使用 `pd.to_numeric(..., errors="coerce")`。

**Correct answers:** A, B, D

**Reason:** cell 21 有 `column_mapping`、`_coalesce_duplicate_columns()`，並只對列出的 numeric columns 進行數值轉換；不是把所有欄位轉字串。

### Q3 - Facility geocoding fallback and validation

**Target difficulty:** 3 / 5

**Evidence:** `energy-etl-pipeline.ipynb`, cells 42 and 45

**Question:** `get_address_details` 與相關 helper 如何提高電力設施 geocoding 的可靠性？

- A. 先查詢 OpenStreetMap/Nominatim，缺少座標時才改查 Google。
- B. Google 結果會以名稱相似度、地點類別與可用時的 postcode 進行驗證。
- C. OpenStreetMap 和 Google 都不會設定 request delay。
- D. Google API 回傳至少一筆搜尋結果後，`address_details_google` 不再檢查名稱、地點類別或 postcode 就使用第一筆座標。

**Correct answers:** A, B

**Reason:** `get_address_details` 將 OSM 作為第一個來源；Google path 呼叫 `return_validation`。兩個 provider 的程式都含有等待／驗證邏輯。

### Q4 - PostGIS storage verification

**Target difficulty:** 3 / 5

**Evidence:** `energy-etl-pipeline.ipynb`, cells 61, 63, and 64

**Question:** 下列哪些是 notebook 對 PostgreSQL/PostGIS 儲存層所做的工作？

- A. 透過 `CREATE EXTENSION IF NOT EXISTS postgis` 啟用空間 extension。
- B. 以 `psycopg2.extras.execute_values` 批次插入 DataFrame 資料。
- C. 只檢查資料表總筆數，不會檢查幾何欄位。
- D. 載入後會分別統計座標與 PostGIS geometry 非空的筆數。

**Correct answers:** A, B, D

**Reason:** cell 64 除了總筆數，也分別檢查 `coords_col` 與 `geom_col` 的非空數量。

## Assignment 2 - Streaming and Dashboard

### Q5 - Open Electricity response normalisation

**Target difficulty:** 3 / 5

**Evidence:** `A2_Group200.ipynb`, cell 8 (`response_to_df`)

**Question:** `response_to_df` 如何把 Open Electricity API 回應整理成 long-format Polars DataFrame？

- A. 它以 `(timestamp, identifier)` 作為一列資料的 key。
- B. 有 unit code 時可透過 `unit_to_facility` 將 unit 映射為 facility identifier。
- C. 相同 metric 在同一 key 出現多次時，程式會直接丟棄後續值。
- D. 沒有 unit code 但有 network region 時，network region 可作為 identifier。

**Correct answers:** A, B, D

**Reason:** cell 8 使用 `(p.timestamp, identifier)` 當 key；同 metric 的非空值會累加，不是丟棄。

### Q6 - Ordered MQTT publishing

**Target difficulty:** 3 / 5

**Evidence:** `A2_Group200.ipynb`, cell 29 (`_publish_loop`)

**Question:** `_publish_loop` 如何符合 assignment 對 MQTT 模擬資料流的要求？

- A. 先依 `time_interval_utc` 排序，再依 timestamp 分組發布。
- B. 每個 message 都包含 facility、power 和 emissions 等整合後欄位。
- C. 使用 QoS 1 並在 pending message 達上限時等待較早的 publish acknowledgement。
- D. 所有 message 都以保留訊息（retained message）方式發布。

**Correct answers:** A, B, C

**Reason:** 程式使用 `sort("time_interval_utc")`、`json.dumps(...)` 組合訊息、QoS 1 和 pending ACK；`retain=False`。

### Q7 - Subscriber state for live visualisation

**Target difficulty:** 3 / 5

**Evidence:** `A2_Group200.ipynb`, cell 33 (`on_message`)

**Question:** 為什麼 `on_message` 同時更新 `facility_history` 和 `mqtt_facility_records`？

- A. `facility_history` 以 `(facility_code, time_interval)` 保留各時間點紀錄，可供歷史分析使用。
- B. `mqtt_facility_records` 以 facility code 保存該設施最新訊息，適合地圖顯示。
- C. 兩者是完全重複的資料結構，沒有不同用途。
- D. 更新共享資料時使用 lock，避免 dashboard 和 MQTT callback 同時讀寫造成 race condition。

**Correct answers:** A, B, D

**Reason:** 兩個 dict 的 key 與使用情境不同；程式將更新包在 `with mqtt_data_lock` 中。

### Q8 - Continuous publishing and delta mode

**Target difficulty:** 3 / 5

**Evidence:** `A2_Group200.ipynb`, cells 29 and 47

**Question:** continuous execution 啟動後，第二輪與第一輪 publishing 的主要差異是什麼？

- A. 第一輪會以完整資料集開始，後續輪次使用 delta mode。
- B. delta mode 會比較 `(code, timestamp)` 對應的 power、emissions、price、demand signature，只發布新增或改變的紀錄。
- C. 每輪結束後程式固定等待 60 秒才開始下一輪。
- D. delta mode 會完全略過所有 MQTT publish，因此沒有新的資料會送出。

**Correct answers:** A, B, C

**Reason:** `continuous_publish` 對 `_publish_loop(wait=0.1, delta=True)` 呼叫；cell 29 透過 `_last_published` 篩選變更；完成後使用 `stop.wait(60)`。

### Q9 - Reading the delta-detection code

**Target difficulty:** 3 / 5

**Evidence:** `A2_Group200.ipynb`, cell 29 (`_publish_loop`)

**Question:** 閱讀下列 delta mode 的核心邏輯後，下列哪些敘述正確？

```python
key = (row["code"], str(row["time_interval_utc"]))
sig = (row["power"], row["emissions"],
       row.get("market_price"), row.get("market_demand"))
new_snapshot[key] = sig
if _last_published.get(key) != sig:
    sorted_rows.append(row)
```

- A. 同一 facility 在同一 timestamp 的 power、emissions、price、demand 都未改變時，該 row 不會加入本輪待發布清單。
- B. `new_snapshot` 會成為下一輪比較的基準，因此程式可以偵測已知 `(code, timestamp)` 的值是否改變。
- C. 只要 facility code 相同，程式就把所有 timestamp 視為同一筆資料。
- D. 即使 price 或 demand 改變，但 power 和 emissions 沒變，程式也不會發布該 row。

**Correct answers:** A, B

**Reason:** key 同時包含 code 和 timestamp；signature 同時包含四種數值，因此任一項改變都會讓 row 進入 `sorted_rows`。

### Q10 - Safe message-processing order

**Target difficulty:** 4-5 / 5

**Evidence:** `A2_Group200.ipynb`, cell 33 (`on_message`)

**Question:** MQTT callback 收到一則 message 後，請選出最符合 `on_message`、且能避免未定義 facility code 或共享狀態 race condition 的處理順序。

- A. Parse JSON → read and validate `facility_code` → build `record` → acquire `mqtt_data_lock` and update history/latest state.
- B. Acquire `mqtt_data_lock` → update history with raw payload → parse JSON → validate `facility_code`.
- C. Read `facility_code` from raw payload → build `record` → parse JSON → update latest state without a lock.
- D. Parse JSON → build `record` → update dashboard state → check whether `facility_code` exists.

**Correct answer:** A

**Reason:** cell 33 先用 `json.loads` 解析，再確認 `facility_code` 存在，接著建立 record，最後才在 `mqtt_data_lock` 內同步更新 `facility_history`、`mqtt_facility_records` 和 counter。

## Review Checklist

每題請檢查：

- evidence cell 是否真的支持所有正確選項；
- 錯誤選項是否明確可由 evidence 反駁，而不是只是沒提到；
- 題目難度是否符合你要測的 data-engineering 概念；
- 正確答案數量是否符合你希望的 MAQ 設定。
