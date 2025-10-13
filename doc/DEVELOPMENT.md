# AstrBot Bilibili 私信適配器插件開發文檔

## 1. 項目概述（當前實現）

- **定位**: 基於逆向工程的非官方 API 的 Bilibili 私信平台適配器插件。
- **技術棧**: Python 3.10、asyncio、aiohttp、AstrBot 插件機制。
- **認證**: 瀏覽器 Cookie（`SESSDATA`, `bili_jct`）+ 设备標識（`device_id`, `user_agent`）。
- **消息類型**: 文本、圖片（更多類型可擴展）。

## 2. 架構與文件

- **`bilibili_client.py`**: Bilibili API 客戶端。負責 HTTP 請求、圖片上傳、消息獲取/發送、ACK 更新等。
- **`bilibili_adapter.py`**: 平台適配器。負責註冊、初始化、主輪詢、會話處理、消息轉換與事件提交。
- **`bilibili_event.py`**: 平台事件。負責發送策略（文本合併、圖片上傳與發送、接收者解析）。
- **`main.py`**: 插件入口。負責導入與卸載清理（熱重載）。

## 3. 平台註冊與熱重載策略

- 使用 `@register_platform_adapter("bilibili", "Bilibili Adapter", default_config_tmpl=..., adapter_display_name="Bilibili", logo_path="assets/bilibili.svg")` 註冊。
- 插件初始化時，`main.py` 在導入適配器前嘗試清理既有的 `bilibili` 註冊（僅清理本插件來源），避免熱重載重複註冊。無模組頂層副作用，不使用 `__del__`。
- 核心 `register.py` 對重名有嚴格保護：若重複註冊將直接 `ValueError`。

## 4. 配置與表單注入

- `default_config_tmpl`（節選）：
  - 核心：`id`, `type=bilibili`, `enable`, `SESSDATA`, `bili_jct`, `device_id`, `user_agent`。
  - 輪詢：`polling_interval`, `min_polling_interval`, `max_polling_interval`, `max_retry_count`。
  - 網絡：`timeout_total`, `timeout_connect`, `timeout_sock_read`, `connection_limit`, `connection_limit_per_host`, `dns_cache_ttl`, `keepalive_timeout`。
  - API：`message_batch_size`, `api_build_version`, `api_mobi_app`。
  - 訊息處理（可選）：`process_read_messages`（默認 False）、`read_prefetch_window`（範圍 1-10，默認 1）。
- UI 字段元數據注入：`_inject_astrbot_field_metadata()` 謹慎補齊 `CONFIG_METADATA_2` 的 `items` 描述（只在結構匹配時生效）。不匹配時靜默跳過並打印 debug 日誌。

## 5. 客戶端與端點

- 端點：
  - `GET /x/space/myinfo`（獲取自身 UID）。
  - `GET /session_svr/v1/session_svr/new_sessions`（拉取新會話）。
  - `GET /svr_sync/v1/svr_sync/fetch_session_msgs`（拉取會話內消息）。
  - `POST /web_im/v1/web_im/send_msg`（發送文本/圖片消息）。
  - `POST /x/dynamic/feed/draw/upload_bfs`（圖片上傳）。
  - `POST /session_svr/v1/session_svr/update_ack`（更新 ACK）。
- 客戶端要點：
  - 統一 `aiohttp.ClientSession` 與連接池配置；安全 JSON 解析；圖片上傳快取；自動關停 session。

## 6. 主循環與消息處理

- 啟動：創建 `BilibiliClient` -> `get_my_info()` 成功後開始輪詢。
- 拉取：`get_new_sessions(begin_ts)` -> 遍歷 `session_list`（忽略 `talker_id=0` 系統通知）。
- 處理會話：`_process_unread_session()` -> `get_messages()` -> 依序轉換並提交事件 -> `update_ack()`。
- 已讀處理（可選）：當 `unread_count == 0` 且檢測到 ACK 提升，且 `process_read_messages=true` 時，觸發 `_process_recent_read_session()`，以 `read_prefetch_window`（1-10）回溯近期消息，結合啟動時間與已處理水位去重。
- 轉換：`convert_message()` 生成 `AstrBotMessage`：
  - 文本：`[Plain(text)]`。
  - 圖片：`[Image.fromURL(url)]`。
  - 時間戳兼容（毫秒/秒）；`abm.id = f"{session_talker_id}-{msg_seqno}"`；`abm.session_id = str(session_talker_id)`；`abm.self_id` 取自啟動時獲得的 UID。

## 7. 發送策略（BilibiliPlatformEvent）

- **文本合併**：遍歷消息段列表（兼容 `MessageChain`/`list`），連續的 `Plain` 合併為單條私信，符合用戶期望的 UX。
- **接收者解析**：優先將 `session_id` 轉為整數；失敗時回退到 `message_obj.sender.user_id`。
- **圖片處理**：
  - 支援 `path`/`url`/`raw` 三種來源；本地讀檔使用 `asyncio.to_thread()` 避免阻塞。
  - 上傳至 BFS，命中快取則復用；成功後再發送圖片私信。
- **可觀測性**：不支持的組件記錄 `warning`，便於檢測消息缺失。

## 8. 網絡與性能

- 可配置的超時（total/connect/read）、連接池（limit/per_host）、DNS TTL、Keep-Alive。
- 啟動時間戳 `_startup_ts` 過濾離線期間舊消息（只 ACK，不回覆）。
- 自適應輪詢間隔：連續空輪詢逐步放大，收到消息時收斂。

## 9. 安全與日誌

- 日誌只使用 `from astrbot.api import logger`。
- API 調用與關鍵節點全面 `try/except`，並打印簡潔上下文。

## 10. 測試與驗收建議

  - 文本聚合：`Plain('A'), Plain('B')` 僅發一條 `AB`。
  - 圖文混排：文本→圖片→文本，圖片前應先沖刷文本。
  - `session_id` 非數字時使用回退 ID。
