"""签到前随机延迟测试。"""

from unittest.mock import MagicMock, patch

from fafu_auto_sign.main import wait_random_sign_delay


def test_wait_random_sign_delay_uses_configured_range():
    """随机延迟应在配置范围内抽取，并传给可中断等待。"""
    shutdown = MagicMock()
    shutdown.wait.return_value = False
    logger = MagicMock()

    with patch("fafu_auto_sign.main.random.randint", return_value=1234) as randint:
        result = wait_random_sign_delay(shutdown, 900, 2700, logger)

    assert result is False
    randint.assert_called_once_with(900, 2700)
    shutdown.wait.assert_called_once_with(1234)
    logger.info.assert_called_once()


def test_wait_random_sign_delay_propagates_shutdown():
    """等待期间收到退出信号时应返回 True。"""
    shutdown = MagicMock()
    shutdown.wait.return_value = True
    logger = MagicMock()

    with patch("fafu_auto_sign.main.random.randint", return_value=900):
        result = wait_random_sign_delay(shutdown, 900, 2700, logger)

    assert result is True
