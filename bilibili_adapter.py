import asyncio
import json
from datetime import datetime
from typing import Optional

from astrbot.api import logger
from astrbot.api.event import MessageChain
from astrbot.api.message_components import Image, Plain
from astrbot.api.platform import (
    AstrBotMessage,
    MessageMember,
    Platform,
    PlatformMetadata,
    register_platform_adapter,
    MessageType,
)

from .bilibili_client import BilibiliClient
from .bilibili_event import BilibiliPlatformEvent

def _inject_astrbot_field_metadata():
    try:
        from astrbot.core.config.default import CONFIG_METADATA_2

        pg = CONFIG_METADATA_2.get("platform_group")
        if not isinstance(pg, dict):
            return
        metadata = pg.get("metadata")
        if not isinstance(metadata, dict):
            return
        platform = metadata.get("platform")
        if not isinstance(platform, dict):
            return
        items = platform.get("items")
        if not isinstance(items, dict):
            return

        bilibili_items = {
            # 核心认证
            "SESSDATA": {
                "description": "SESSDATA",
                "type": "string",
                "hint": "必填项。浏览器 Cookie 中的 SESSDATA，用于认证。建议定期更新。",
                "obvious_hint": True,
            },
            "bili_jct": {
                "description": "bili_jct",
                "type": "string",
                "hint": "必填项。浏览器 Cookie 中的 bili_jct（CSRF Token）。发送消息必需。",
                "obvious_hint": True,
            },
            "device_id": {
                "description": "设备ID",
                "type": "string",
                "hint": "必填。用于模拟设备标识。",
                "obvious_hint": True,
            },
            "user_agent": {
                "description": "User-Agent",
                "type": "string",
                "hint": "必填。需提供浏览器 UA 字符串。",
                "obvious_hint": True,
            },

            # 轮询
            "polling_interval": {
                "description": "轮询间隔(秒)",
                "type": "int",
                "hint": "默认 5。用于拉取新会话的基础间隔。",
            },
            "min_polling_interval": {
                "description": "最小轮询间隔(秒)",
                "type": "int",
                "hint": "默认 2。自适应调整下限。",
            },
            "max_polling_interval": {
                "description": "最大轮询间隔(秒)",
                "type": "int",
                "hint": "默认 30。自适应调整上限。",
            },
            "max_retry_count": {
                "description": "最大重试次数",
                "type": "int",
                "hint": "默认 3。连续异常时的最大重试次数。",
            },

            # 网络
            "timeout_total": {
                "description": "总超时(秒)",
                "type": "int",
                "hint": "默认 30。整体请求的最大耗时。",
            },
            "timeout_connect": {
                "description": "连接超时(秒)",
                "type": "int",
                "hint": "默认 10。TCP 连接建立超时。",
            },
            "timeout_sock_read": {
                "description": "读取超时(秒)",
                "type": "int",
                "hint": "默认 20。收到响应后的读取超时。",
            },
            "connection_limit": {
                "description": "连接池限额",
                "type": "int",
                "hint": "默认 100。HTTP 客户端总并发连接上限。",
            },
            "connection_limit_per_host": {
                "description": "单主机连接上限",
                "type": "int",
                "hint": "默认 30。对同一主机的并发连接上限。",
            },
            "dns_cache_ttl": {
                "description": "DNS 缓存 TTL(秒)",
                "type": "int",
                "hint": "默认 300。DNS 解析缓存时间。",
            },
            "keepalive_timeout": {
                "description": "Keep-Alive 超时(秒)",
                "type": "int",
                "hint": "默认 60。空闲连接保活时间。",
            },

            # API
            "message_batch_size": {
                "description": "消息批量大小",
                "type": "int",
                "hint": "默认 20。每次获取的消息数量。",
            },
            "api_build_version": {
                "description": "API 构建版本",
                "type": "int",
                "hint": "默认 0。保留字段。",
            },
            "api_mobi_app": {
                "description": "应用标识",
                "type": "string",
                "hint": "默认 web。",
            },
        }

        # 仅在缺失时新增；若已存在则尽量补齐缺失的字段
        for k, v in bilibili_items.items():
            if k not in items:
                items[k] = v
            else:
                it = items[k]
                if "description" not in it and "description" in v:
                    it["description"] = v["description"]
                if "type" not in it and "type" in v:
                    it["type"] = v["type"]
                if "hint" not in it and "hint" in v:
                    it["hint"] = v["hint"]
                if "obvious_hint" not in it and "obvious_hint" in v:
                    it["obvious_hint"] = v["obvious_hint"]

        logger.debug("已为 Bilibili 适配器注入字段元数据")
    except Exception as e:
        try:
            logger.debug(f"注入 bilibili 字段元数据失败: {e}")
        except Exception:
            pass


_inject_astrbot_field_metadata()
 
def _pre_unregister_platform():
    """在注册适配器前，预清理可能残留的注册（仅本插件来源），避免热重载冲突。"""
    try:
        from astrbot.core.platform.register import platform_cls_map
        existing = platform_cls_map.get("bilibili")
        if existing is not None:
            mod = getattr(existing, "__module__", "")
            # 仅当旧注册来自本插件时才清理，避免误删他人适配器
            if isinstance(mod, str) and "astrbot_plugin_bilibili" in mod:
                del platform_cls_map["bilibili"]
                logger.debug("预清理：移除本插件残留的 bilibili 注册。")
    except Exception:
        # 静默处理，避免因核心结构差异影响加载
        pass

_pre_unregister_platform()

@register_platform_adapter(
    "bilibili",
    "Bilibili Adapter",
    default_config_tmpl={
        # 核心
        "id": "default",
        "type": "bilibili",
        "enable": False,
        "hint": "非官方 API 适配器：需提供浏览器 Cookie 的 SESSDATA 与 bili_jct；网络参数可按需调整。",
        "SESSDATA": "",
        "bili_jct": "",
        "device_id": "",
        "user_agent": "",
        # 輪詢
        "polling_interval": 5,
        "min_polling_interval": 2,
        "max_polling_interval": 30,
        "max_retry_count": 3,
        # 網絡
        "timeout_total": 30,
        "timeout_connect": 10,
        "timeout_sock_read": 20,
        "connection_limit": 100,
        "connection_limit_per_host": 30,
        "dns_cache_ttl": 300,
        "keepalive_timeout": 60,
        # API
        "message_batch_size": 20,
        "api_build_version": 0,
        "api_mobi_app": "web",
    },
    adapter_display_name="Bilibili",
    logo_path="assets/bilibili.svg",
)
class BilibiliAdapter(Platform):
    """Bilibili Adapter"""

    def __init__(
        self, platform_config: dict, platform_settings: dict, event_queue: asyncio.Queue
    ):
        super().__init__(event_queue)
        logger.info("Bilibili Adapter 正在初始化...")

        # 配置驗證
        self._validate_config(platform_config)

        logger.info("Bilibili Adapter 配置驗證通過。")
        self.config = platform_config
        self.settings = platform_settings
        self.poll_interval = platform_config.get("polling_interval", 5)
        self.min_poll_interval = platform_config.get("min_polling_interval", 2)
        self.max_poll_interval = platform_config.get("max_polling_interval", 30)
        self.current_poll_interval = self.poll_interval
        self.consecutive_empty_polls = 0
        # 兼容旧键名 max_retry_attempts，优先使用与校验一致的 max_retry_count
        self.max_retry_count = platform_config.get(
            "max_retry_count", platform_config.get("max_retry_attempts", 3)
        )
        self.client: Optional[BilibiliClient] = None
        self._self_uid: Optional[int] = None
        # 适配器启动时间戳，用于忽略启动前的离线消息（只ACK不响应）
        self._startup_ts: Optional[int] = None
        self._running = False
        logger.info("Bilibili Adapter 初始化完成。")

    def _validate_config(self, config: dict):
        """验证配置参数"""
        # 验证核心必填配置项
        required_configs = {
            "SESSDATA": "",
            "bili_jct": "",
            "device_id": "",
            "user_agent": "",
        }

        for config_key, default_value in required_configs.items():
            value = config.get(config_key)
            if not value:
                logger.critical(
                    f"Bilibili Adapter 配置不完整，缺少 {config_key}。請檢查配置文件。"
                )
                raise ValueError(
                    f"Bilibili Adapter 配置不完整：缺少必需的配置项 {config_key}"
                )

        # 验证数值参数范围
        numeric_params = {
            # 輪詢配置
            "polling_interval": (1, 300),
            "min_polling_interval": (1, 60),
            "max_polling_interval": (5, 600),
            "max_retry_count": (1, 10),
            # 網絡配置
            "timeout_total": (5, 300),
            "timeout_connect": (1, 60),
            "timeout_sock_read": (1, 120),
            "connection_limit": (1, 1000),
            "connection_limit_per_host": (1, 100),
            "dns_cache_ttl": (60, 3600),
            "keepalive_timeout": (10, 300),
            # API 配置
            "message_batch_size": (1, 100),
        }

        for param, (min_val, max_val) in numeric_params.items():
            value = config.get(param)
            if value is not None and not (min_val <= value <= max_val):
                logger.critical(f"配置参数 {param} 超出有效范围 [{min_val}, {max_val}]")
                raise ValueError(
                    f"配置错误：{param} 必须在 {min_val} 到 {max_val} 之间"
                )

        # 验证逻辑关系
        min_poll = config.get("min_polling_interval", 2)
        max_poll = config.get("max_polling_interval", 30)
        if min_poll >= max_poll:
            logger.critical(
                "轮询间隔配置错误：『最小轮询间隔』必须小于『最大轮询间隔』"
            )
            raise ValueError("配置错误：『最小轮询间隔』必须小于『最大轮询间隔』")

    def meta(self) -> "PlatformMetadata":
        return PlatformMetadata(
            name="bilibili",
            description="Bilibili Adapter",
            id=self.config.get("id"),
            adapter_display_name="Bilibili",
            logo_path="assets/bilibili.svg",
        )

    async def shutdown(self):
        logger.info("Bilibili Adapter 正在離開...")
        self._running = False
        if self.client:
            logger.info("Bilibili Client 正在離開...")
            try:
                await self.client.close()
            finally:
                self.client = None
        logger.info("Bilibili Adapter 已成功離開。")

    async def run(self):
        try:
            logger.info("Bilibili Adapter 正在啟動並創建客戶端...")
            self.client = BilibiliClient(
                sessdata=self.config["SESSDATA"],
                bili_jct=self.config["bili_jct"],
                device_id=self.config["device_id"],
                user_agent=self.config["user_agent"],
                # 網絡配置（可選）
                timeout_total=self.config.get("timeout_total", 30),
                timeout_connect=self.config.get("timeout_connect", 10),
                timeout_sock_read=self.config.get("timeout_sock_read", 20),
                connection_limit=self.config.get("connection_limit", 100),
                connection_limit_per_host=self.config.get(
                    "connection_limit_per_host", 30
                ),
                dns_cache_ttl=self.config.get("dns_cache_ttl", 300),
                keepalive_timeout=self.config.get("keepalive_timeout", 60),
                # API 配置（可選）
                message_batch_size=self.config.get("message_batch_size", 20),
                api_build_version=self.config.get("api_build_version", 0),
                api_mobi_app=self.config.get("api_mobi_app", "web"),
            )
            success, uid = await self.client.get_my_info()
            if not success:
                logger.critical("啟動失敗，無法獲取 Bilibili 使用者信息。")
                try:
                    await self.client.close()
                except Exception:
                    pass
                self.client = None
                return
            self._self_uid = uid
            self._running = True
            logger.info(
                f"Bilibili Adapter 啟動成功，UID: {self._self_uid}。開始輪詢消息……"
            )
        except Exception as e:
            logger.critical(f"Bilibili Adapter 啟動失敗: {e}", exc_info=True)
            if self.client:
                try:
                    await self.client.close()
                except Exception:
                    pass
                self.client = None
            return

        begin_ts = int(datetime.now().timestamp())
        # 记录启动时间，用于过滤离线期间的旧消息（只 ACK，不进入处理流水线）
        self._startup_ts = begin_ts
        retry_count = 0

        while self._running:
            try:
                sessions_data = await self.client.get_new_sessions(begin_ts)

                # 檢查 Cookie 調用是否成功
                if sessions_data is None:
                    logger.warning("New Session 獲取失敗，跳過本次輪詢")
                    await asyncio.sleep(self.current_poll_interval)
                    continue

                if sessions_data.get("session_list"):
                    has_messages = False
                    for session_info in sessions_data["session_list"]:
                        # 忽略 Bilibili 官方系統通知 (talker_id 為 0)
                        if session_info.get("talker_id") == 0:
                            continue

                        if session_info.get("unread_count", 0) > 0:
                            await self._process_unread_session(session_info)
                            has_messages = True

                    # 自適應輪詢間隔調整
                    if has_messages:
                        self.consecutive_empty_polls = 0
                        self.current_poll_interval = max(
                            self.min_poll_interval, self.current_poll_interval * 0.8
                        )
                    else:
                        self.consecutive_empty_polls += 1
                        if self.consecutive_empty_polls > 3:
                            self.current_poll_interval = min(
                                self.max_poll_interval, self.current_poll_interval * 1.2
                            )

                # 安全更新時間戳
                if sessions_data and "ack_ts" in sessions_data:
                    begin_ts = sessions_data["ack_ts"]
                    logger.debug(f"更新時間戳為: {begin_ts}")
                # 如果沒有 ack_ts，保持原來的 begin_ts 不變

                retry_count = 0  # 重置重試次數

                await asyncio.sleep(self.current_poll_interval)
            except Exception as e:
                retry_count += 1
                logger.error(
                    f"Bilibili Adapter 運行時發生未預期的錯誤 (重试 {retry_count}/{self.max_retry_count}): {e}",
                    exc_info=True,
                )

                if retry_count >= self.max_retry_count:
                    logger.critical("達到最大重試次數，适配器将停止运行")
                    break

                # 指數退避重試
                backoff_time = min(60, self.poll_interval * (2**retry_count))
                await asyncio.sleep(backoff_time)

        # 运行结束，确保资源释放
        self._running = False
        if self.client:
            try:
                await self.client.close()
            except Exception:
                try:
                    logger.error("退出時關閉 Bilibili Client 失敗", exc_info=True)
                except Exception:
                    pass
            self.client = None
        logger.info("Bilibili Adapter 已结束运行。")
    async def _process_unread_session(self, session_info: dict):
        talker_id = session_info.get("talker_id")
        session_type = session_info.get("session_type")
        ack_seqno = session_info.get("ack_seqno", 0)

        logger.info(f"發現來自 talker_id: {talker_id} 的未讀消息，正在拉取……")

        try:
            messages_data = await self.client.get_messages(
                talker_id, session_type, ack_seqno
            )

            # 檢查消息獲取是否成功
            if messages_data is None:
                logger.warning(f"獲取 Session {talker_id} 的訊息失敗，跳過處理")
                return

            if messages_data.get("messages"):
                messages = messages_data["messages"]
                max_seqno_in_batch = 0
                for msg_data in messages:
                    if (
                        msg_data["msg_seqno"] > ack_seqno
                        and msg_data.get("sender_uid") != self._self_uid
                    ):
                        # 启动前收到的旧消息：仅 ACK 不回覆
                        msg_ts = msg_data.get("timestamp", 0)
                        # 兼容毫秒级时间戳
                        if isinstance(msg_ts, (int, float)) and msg_ts > 10**12:
                            msg_ts = int(msg_ts // 1000)
                        is_backlog = (
                            self._startup_ts is not None and msg_ts < self._startup_ts
                        )

                        if is_backlog:
                            logger.debug(
                                f"跳过离线期间的旧消息（仅ACK）：talker_id={talker_id}, msg_seqno={msg_data.get('msg_seqno')}"
                            )
                        else:
                            # 使用 talker_id 作为会话标识，确保会话隔离
                            abm = self.convert_message(msg_data, talker_id)
                            if abm:
                                await self.handle_msg(abm)
                        max_seqno_in_batch = max(
                            max_seqno_in_batch, msg_data["msg_seqno"]
                        )

                if max_seqno_in_batch > ack_seqno:
                    await self.client.update_ack(
                        talker_id, session_type, max_seqno_in_batch
                    )

        except Exception as e:
            logger.error(
                f"處理 Session {talker_id} 的訊息時發生錯誤: {e}", exc_info=True
            )

    def convert_message(self, data: dict, session_talker_id: int) -> Optional[AstrBotMessage]:
        msg_type = data.get("msg_type")
        sender_uid = data.get("sender_uid")

        abm = AstrBotMessage()

        # 處理私信
        abm.type = MessageType.FRIEND_MESSAGE

        # 消息鏈
        if msg_type == 1:  # 文本消息
            try:
                content_data = json.loads(data.get("content", "{}"))
                text_content = content_data.get("content", "")
                if not text_content:
                    return None
                abm.message = MessageChain([Plain(text_content)])
                abm.message_str = text_content
            except (json.JSONDecodeError, TypeError):
                logger.warning(f"無法解析 Bilibili 文本訊息內容: {data.get('content')}")
                return None
        elif msg_type == 2:  # 圖片消息
            try:
                content_data = json.loads(data.get("content", "{}"))
                image_url = content_data.get("url")
                if not image_url:
                    return None
                abm.message = MessageChain([Image(url=image_url)])
                abm.message_str = "[圖片]"
            except (json.JSONDecodeError, TypeError):
                logger.warning(f"無法解析 Bilibili 圖片訊息內容: {data.get('content')}")
                return None
        else:
            logger.debug(f"忽略不支援的 Bilibili 訊息類型: {msg_type}")
            return None

        # 填充其他必要字段
        # 统一时间戳解析与单位（支持字符串与毫秒级时间戳）
        _ts_raw = data.get("timestamp")
        ts_val = None
        if isinstance(_ts_raw, (int, float)):
            ts_val = int(_ts_raw)
        elif isinstance(_ts_raw, str):
            try:
                ts_val = int(float(_ts_raw))
            except Exception:
                ts_val = None
        if ts_val is None:
            ts_val = int(datetime.now().timestamp())
        if ts_val > 10**12:
            ts_val = int(ts_val // 1000)
        try:
            abm.time = datetime.fromtimestamp(ts_val)
        except Exception:
            abm.time = datetime.now()
        # 使用會話ID + 序號提高唯一性（msg_seqno 通常在會話作用域內唯一）
        abm.id = f"{session_talker_id}-{data.get('msg_seqno')}"
        abm.sender = MessageMember(
            user_id=str(sender_uid), nickname=""
        )  # Bilibili 不提供暱稱獲取
        # 使用 session 的 talker_id 作为 session_id，避免某些消息体下的 sender_uid 与 session 主体不一致
        abm.session_id = str(session_talker_id)
        abm.raw_message = data
        abm.self_id = str(self._self_uid)

        return abm

    async def handle_msg(self, message: Optional[AstrBotMessage]):
        if not message:
            return

        event = BilibiliPlatformEvent(
            message_str=message.message_str,
            message_obj=message,
            platform_meta=self.meta(),
            session_id=message.session_id,
            client=self.client,
        )
        self.commit_event(event)

    async def terminate(self):
        self._running = False
        await self.shutdown()
