# Bilibili 私信適配器 - 技術文檔

## 1. 概述

面向 AstrBot 的 Bilibili 私信平台適配器插件（非官方 API）。支持接收與發送私信，目前覆蓋文本與圖片。使用 Cookie（`SESSDATA`, `bili_jct`）與設備標識進行認證，採用異步輪詢與連接池優化提升穩定性。

---

## 2. 核心組件

核心文件與職責如下：

### `bilibili_adapter.py` - 適配器主體

 該文件實現平台適配器主體。`BilibiliAdapter` 類繼承自 AstrBot 的 `Platform`，負責適配器的生命週期與輪詢邏輯。
 插件入口位於 `main.py` 的 `BilibiliPlugin`，其在初始化時導入本適配器以完成註冊。

- **初始化 (`__init__`)**: 校驗配置，設置輪詢與網絡參數。
- **消息輪詢 (`run`)**: 異步拉取新會話與新消息，忽略 `talker_id=0` 的系統通知，支持自適應輪詢間隔與 ACK 更新。
- **消息轉換 (`convert_message`)**: 轉換為 `AstrBotMessage`，統一 `message` 為 `MessageChain`，時間戳與 ID 兼容處理（`{session_talker_id}-{msg_seqno}`）。
- **事件提交 (`handle_msg`)**: 組裝 `BilibiliPlatformEvent` 並提交。

### `bilibili_client.py` - API 客戶端

該文件封裝了所有與 Bilibili 後端 API 的直接交互，將底層的 HTTP 請求抽象為語義清晰的方法。這使得主適配器邏輯無需關心 API 的具體細節。

- **會話與消息**: `get_new_sessions`, `get_messages`, `update_ack`。
- **發送消息**: `send_text_message`（文本）、`send_image_message`（圖片）。
- **圖片上載**: `upload_image`，帶內存快取（按 path/url 鍵）。
- **網絡配置**: 超時、連接池、DNS TTL、Keep-Alive 可配置；安全 JSON 解析；自動關閉 `ClientSession`。

### `bilibili_event.py` - 平台事件

定義了特定於 Bilibili 平台的事件對象 `BilibiliPlatformEvent`，它繼承自 `AstrMessageEvent`。

- **消息發送 (`send`)**: 文本支持連續 `Plain` 自動合併為單條私信；圖片支持 `path/url/raw`，先上傳後發送；遇到不支持的組件輸出 `warning`。
- **接收者解析**: 優先使用 `session_id` 轉整型，失敗回退為 `sender.user_id`。
- **概要生成**: `get_message_outline()` 兼容 `MessageChain` 與 `list` 兩種形態以提升兼容性。

---

## 3. 關鍵設計與實現細節

### 消息處理流程

- **接收**: `Adapter.run` -> `Client.get_new_sessions` -> `Client.get_messages` -> `Adapter.convert_message` -> `Adapter.handle_msg`
- **發送**: `Skill` -> `Event.send` -> `Client.upload_image`(可選) -> `Client.send_*`

### 性能優化與健壯性

- **忽略系統通知**：自動忽略 `talker_id=0` 會話。
- **圖片上載緩存**：命中緩存時跳過上載。
- **自適應輪詢**：空輪詢擴大間隔，有消息時收斂。

---

## 4. 安裝與配置

1) 安裝依賴：

```bash
pip install -r requirements.txt
```

2) 配置必填項

- `SESSDATA`, `bili_jct`（Cookie）
- `device_id`, `user_agent`（設備標識）
- （可選）輪詢與網絡參數：`polling_interval`、`timeout_total`、`connection_limit` 等

---

## 5. 運行與熱重載

- 啟用平台配置後，AstrBot 將自動加載適配器。
- 熱重載：卸載時 `main.py::__del__()` 清理；註冊前 `_pre_unregister_platform()` 僅清理“本插件來源”的殘留，避免誤刪。

---

## 6. 已知限制

- 非官方 API 存在變更風險，請保持 Cookie 有效。
- 僅支持文本與圖片，其它類型可按需擴展。

---

## 7. 故障排查

- **啟動報錯/無法獲取 UID**：檢查 `SESSDATA` 與 `bili_jct` 是否有效；檢查網絡與代理。
- **熱重載“已註冊過”**：確保單插件運行；查看日誌 `_pre_unregister_platform()` 是否執行。
- **圖片發送失敗**：檢查圖片來源；觀察是否命中上載緩存；查看 API 返回碼。

## 8. 授權與風險聲明

本項目基於逆向工程，僅供學習與研究，請遵守相關法律與站點條款。