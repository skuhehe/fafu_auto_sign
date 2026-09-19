"""业务时区不一致提示测试。

程序按 ``config.timezone_offset``（默认 UTC+8）计算签到窗口与展示时间，
**不依赖宿主机时区**；但宿主机时区不一致时日志时间难以与校方口径对照，
因此启动时提示一次。这里验证提示的三种分支。
"""

import logging
from unittest.mock import MagicMock, patch

from fafu_auto_sign.config import AppConfig
from fafu_auto_sign.main import warn_timezone_mismatch


def _config(timezone_offset: int = 8) -> AppConfig:
    return AppConfig(user_token="2_TEST_TOKEN", timezone_offset=timezone_offset)


def test_warns_when_system_timezone_differs(caplog):
    """宿主机时区与业务时区不一致时应给出 warning。"""
    caplog.set_level(logging.WARNING)

    with patch("fafu_auto_sign.main.local_timezone_offset", return_value=0.0):
        warn_timezone_mismatch(_config(8), logging.getLogger("test.tz"))

    assert "系统时区偏移为 UTC+0" in caplog.text
    assert "业务时区为 UTC+8" in caplog.text
    assert "TZ=Asia/Shanghai" in caplog.text


def test_silent_when_timezones_match(caplog):
    """时区一致时不应产生噪音日志。"""
    caplog.set_level(logging.WARNING)

    with patch("fafu_auto_sign.main.local_timezone_offset", return_value=8.0):
        warn_timezone_mismatch(_config(8), logging.getLogger("test.tz"))

    assert caplog.text == ""


def test_silent_when_local_offset_unknown(caplog):
    """取不到宿主机时区时静默跳过，不应阻断启动。"""
    caplog.set_level(logging.WARNING)

    with patch("fafu_auto_sign.main.local_timezone_offset", return_value=None):
        warn_timezone_mismatch(_config(8), MagicMock())

    assert caplog.text == ""


def test_custom_business_timezone_is_reflected_in_message(caplog):
    """提示文案应反映配置的业务时区，而不是写死 UTC+8。"""
    caplog.set_level(logging.WARNING)

    with patch("fafu_auto_sign.main.local_timezone_offset", return_value=-5.0):
        warn_timezone_mismatch(_config(9), logging.getLogger("test.tz"))

    assert "业务时区为 UTC+9" in caplog.text
