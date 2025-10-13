from astrbot.api.star import Context, Star


class BilibiliPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        # 強制預清理：在導入適配器前，無條件刪除既有 bilibili 註冊，確保乾淨狀態
        try:
            from astrbot.api import logger
            modules = []
            try:
                import astrbot.api.platform.register as _api_reg
                modules.append(_api_reg)
            except Exception:
                pass
            try:
                import astrbot.core.platform.register as _core_reg
                modules.append(_core_reg)
            except Exception:
                pass
            for _m in modules:
                _map = getattr(_m, "platform_cls_map", None)
                try:
                    if _map is not None and ("bilibili" in _map):
                        del _map["bilibili"]
                        try:
                            logger.debug("強制預清理：已移除 bilibili 既有註冊。")
                        except Exception:
                            pass
                except Exception:
                    pass
        except Exception:
            pass

        try:
            from .bilibili_adapter import _inject_astrbot_field_metadata
            _inject_astrbot_field_metadata()
            from .bilibili_adapter import BilibiliAdapter  # noqa
            from .bilibili_event import BilibiliPlatformEvent  # noqa
        except ImportError as e:
            from astrbot.api import logger
            logger.error(f"匯入 Bilibili Adapter 失敗，請檢查依賴是否安裝: {e}")
            # 抛出异常，避免處於“已加載但不可用”的不一致狀態
            raise