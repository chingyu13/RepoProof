# COMP5339 Energy Assignments - Evaluation Set Draft

這是 RepoProof 的第一版人工評測集（gold set 草稿）。每個 case 都要測兩件事：

1. BM25 top-6 evidence 有沒有找到「預期命中」的 notebook cell；
2. 生成題目有沒有只根據 evidence，且符合 assignment 的概念。

使用前請先人工確認或修改「預期命中」和「不應作為主要證據」。Notebook cell 編號採 Jupyter 的 0-based index，和 RepoProof 顯示的 cell index 相同。

## Sources

| Assignment | Notebook |
| --- | --- |
| A1 - Electricity Sector Data Integration & Augmentation | `energy-etl-pipeline.ipynb` |
| A2 - Electricity Sector Data Streaming and Analysis | `A2_Group200.ipynb` |

## A1 - Static ETL, Augmentation, and Storage

### A1-01 - Retrieve and parse source datasets

- Focus / assignment text: Retrieve NGER, renewable power-station, and ABS data; support CSV and XLSX input.
- Expected evidence: `energy-etl-pipeline.ipynb` cell 5 (`file_info` source URLs), cell 10 (`download_file`, `check_file_exists`, `load_econ_xlsx`).
- Strong evidence should show: HTTP download with timeout/status handling; local-file fallback; ABS workbook parsing of Table 1 and Table 2; column-name normalisation.
- Should not be primary evidence: cell 21 cleaning logic or database cells 61/63.
- Example question target: Why does `check_file_exists` check local paths before downloading, and how does `load_econ_xlsx` handle changed sheet names?

### A1-02 - Clean inconsistent NGER and ABS fields

- Focus / assignment text: Integrate and clean electricity/emissions datasets, including missing values and type conversion.
- Expected evidence: cell 21.
- Strong evidence should show: NGER column-name harmonisation; duplicate-column coalescing; `pd.to_numeric(..., errors="coerce")`; separating `geo_info` from ECON data.
- Should not be primary evidence: geocoding cells 42-47.
- Example question target: How does `_coalesce_duplicate_columns` avoid losing values after annual files are concatenated?

### A1-03 - Geocode facilities with a reliable fallback

- Focus / assignment text: Augment power stations with coordinates via a public geocoding API and document matching quality.
- Expected evidence: cells 42 and 45; cell 47 is supporting evidence for reverse postcode lookup.
- Strong evidence should show: OpenStreetMap/Nominatim attempted first; Google fallback only when coordinates are unavailable; validation uses name similarity, category, and optionally postcode; requests are delayed.
- Should not be primary evidence: cells 54/56, which work on regional GIS layers rather than facility API matching.
- Example question target: Under what condition does `get_address_details` use Google instead of OpenStreetMap, and why is `return_validation` needed?

### A1-04 - Build geographic reference data

- Focus / assignment text: Prepare geographic data suitable for spatial queries and connect regions to postcodes.
- Expected evidence: cells 54 and 56.
- Strong evidence should show: WGS84 and Albers reprojection; area/centroid derivation; SA2-to-SA3-to-SA4-to-state postcode rollup; spatial-join fallback for uncovered regions.
- Should not be primary evidence: facility geocoding cell 45.
- Example question target: Why does `build_postcode_lists` spatially join SA2 first, then roll up to higher ASGS levels?

### A1-05 - Store spatial data in PostgreSQL/PostGIS

- Focus / assignment text: Implement a schema in DuckDB/PostgreSQL with spatial support and verify storage.
- Expected evidence: cells 61, 63, and 64.
- Strong evidence should show: `CREATE EXTENSION IF NOT EXISTS postgis`; bulk insert using `execute_values`; template-specific geometry/JSONB conversion; post-load counts for coordinates and geometries.
- Should not be primary evidence: raw-data download cell 10.
- Example question target: What does `verify_table` check after loading a spatial table, and why are coordinate and geometry counts separate?

## A2 - Streaming, MQTT, Dashboard, and Continuous Execution

### A2-01 - Normalise Open Electricity API responses

- Focus / assignment text: Retrieve per-facility generation and CO2 emissions at five-minute intervals and consolidate them by facility/time.
- Expected evidence: cells 7-8, and cell 14 as supporting retrieval evidence.
- Strong evidence should show: `response_to_df` creates one row per `(timestamp, identifier)`; unit codes can map to facility codes; values for the same metric are accumulated.
- Should not be primary evidence: MQTT cell 29.
- Example question target: How does `response_to_df` choose an identifier when a unit code is absent, and what key prevents duplicate rows?

### A2-02 - Materialise and clean the streaming dataset

- Focus / assignment text: Combine power and emissions records, clean them, and store a CSV cache to avoid repeated API calls.
- Expected evidence: cells 20, 22, and 24.
- Strong evidence should show: duplicate handling, missing-data treatment, and output into the data/cache location.
- Manual review needed: confirm these cells contain the final CSV write and cleaning behaviour before making this case a strict gold label.
- Should not be primary evidence: dashboard cells 40-44.

### A2-03 - Publish ordered, combined MQTT messages

- Focus / assignment text: Publish one combined power-and-emissions message per facility record in event-time order, with a 0.1-second delay.
- Expected evidence: cell 29.
- Strong evidence should show: `df_publish.sort("time_interval_utc")`; grouping by timestamp; JSON contains facility metadata, power, emissions, and optional market fields; QoS 1; `time.sleep(wait)`; inflight acknowledgement handling.
- Should not be primary evidence: subscriber cell 33.
- Example question target: How does `_publish_loop` preserve event-time ordering, and what role does `MAX_INFLIGHT` play?

### A2-04 - Subscribe and maintain the latest facility state

- Focus / assignment text: Subscribe to MQTT messages and make their data available to a live dashboard.
- Expected evidence: cells 32-33.
- Strong evidence should show: callback subscription at QoS 1; JSON parsing; records keyed by `(facility_code, time_interval)` for history; latest record keyed by facility code; lock protection for shared dashboard state.
- Should not be primary evidence: publisher cell 29, except as context for the message schema.
- Example question target: Why does `on_message` maintain both `facility_history` and `mqtt_facility_records`?

### A2-05 - Update a map dashboard from MQTT data

- Focus / assignment text: Dynamically display facility markers, power/emissions, pop-ups, and region/fuel filters.
- Expected evidence: cells 40 and 44.
- Strong evidence should show: markers are created only for new facility codes; marker size changes with power/emissions mode; region/fuel filtering; popup includes facility, fuel, latest values, price, and demand; polling refreshes after new MQTT messages.
- Should not be primary evidence: the continuous publisher cell 47.
- Example question target: How does `newData_update_dashboard` avoid recreating all map markers on each MQTT update?

### A2-06 - Run the stream continuously and publish only changes

- Focus / assignment text: Continuously simulate an unbounded stream, with 0.1-second per-message delay and 60 seconds between retrieval/publish rounds.
- Expected evidence: cells 29 and 47; cell 52 is supporting dashboard timing evidence.
- Strong evidence should show: delta comparison with `_last_published`; `_publish_loop(wait=0.1, delta=True)`; `stop.wait(60)` between rounds; background daemon thread; safe stop event replacement.
- Should not be primary evidence: one-off API parsing cell 8.
- Example question target: What changes after the first publishing round, and how does the code avoid republishing unchanged records?

## Review Sheet for Each Run

Use this small table when comparing RepoProof output with the cases above.

| Case ID | Focus text used | Top-6 includes expected cell? | Wrong evidence ranked above expected? | Question grounded in evidence? | JSON/validator passed? | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| A1-01 |  |  |  |  |  |  |
| A1-02 |  |  |  |  |  |  |
| A1-03 |  |  |  |  |  |  |
| A1-04 |  |  |  |  |  |  |
| A1-05 |  |  |  |  |  |  |
| A2-01 |  |  |  |  |  |  |
| A2-02 |  |  |  |  |  |  |
| A2-03 |  |  |  |  |  |  |
| A2-04 |  |  |  |  |  |  |
| A2-05 |  |  |  |  |  |  |
| A2-06 |  |  |  |  |  |  |

## Initial Retrieval Baseline (2026-07-17)

以下是以目前 analyzer/BM25 對每個 notebook 單獨建立 index、用各 case 的 focus text 取 top-3 的 smoke test。這不是 gold label；它用來記錄改進前的結果。

| Case | Current top-3 result | Initial reading |
| --- | --- | --- |
| A1-01 | cells 5, 12, 10 | Reasonable: source list, loading loop, and download/parser all appear. |
| A1-02 | cells 28, 3, 74 | Weak: expected cleaning cell 21 did not enter top-3. |
| A1-03 | cells 47, 5, 64 | Weak: reverse geocoding appears, but primary matching cell 45 is missing. |
| A1-05 | cells 61, 42, 7 | Partial: PostGIS setup is found, but bulk storage cell 63 is missing. |
| A2-03 | cells 47, 29, 33 | Good: continuous publisher, MQTT publisher, subscriber are all relevant. |
| A2-05 | cells 32, 44, 40 | Good: state setup, dashboard rendering, and update functions are found. |
| A2-06 | cells 47, 29, 50 | Good: continuous loop, delta publisher, and timing chart are found. |

The weak A1 cases should be kept: they are useful regressions for evaluating future query expansion, notebook-aware chunking, or assignment-description query planning.
