from astrbot.api.star import Context, Star


class BilibiliPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        # 在插件初始化時，匯入模塊以觸發註冊
        try:
            from .bilibili_adapter import BilibiliAdapter  # noqa
            from .bilibili_event import BilibiliPlatformEvent  # noqa
        except ImportError as e:
            from astrbot.api import logger
            logger.error(f"匯入 Bilibili Adapter 失敗，請檢查依賴是否安裝: {e}")
            # 抛出异常，避免处于“已加载但不可用”的不一致状态
            raise

    def __del__(self):
        """插件被禁用、重载时调用：清理全局平台注册，防止命名冲突。"""
        try:
            from astrbot.api import logger
            from astrbot.core.platform.register import platform_cls_map
            if "bilibili" in platform_cls_map:
                del platform_cls_map["bilibili"]
                logger.debug("已从 platform_cls_map 中移除 bilibili 适配器注册。")
        except Exception:
            # 静默处理，避免影响卸载流程
            pass