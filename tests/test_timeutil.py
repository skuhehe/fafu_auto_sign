"""业务时区工具测试。

服务端按北京时间（UTC+8）判定签到窗口，因此本模块的正确性直接决定
「窗口判断」与「日志时间」是否与校方口径一致，**不能依赖宿主机时区**。
"""

import datetime
import time

from fafu_auto_sign import timeutil


class TestGetTimezone:
    """时区对象构造。"""

    def test_default_offset_is_utc_plus_8(self):
        """默认时区偏移为 +8 小时（北京时间，中国无夏令时）。"""
        assert timeutil.get_timezone().utcoffset(None) == datetime.timedelta(hours=8)

    def test_zero_offset_is_utc(self):
        """偏移为 0 时等价于 UTC。"""
        assert timeutil.get_timezone(0).utcoffset(None) == datetime.timedelta(0)

    def test_negative_offset_supported(self):
        """支持负偏移（西半球部署场景）。"""
        assert timeutil.get_timezone(-5).utcoffset(None) == datetime.timedelta(hours=-5)


class TestNow:
    """当前时间。"""

    def test_now_utcoffset_is_eight_hours(self):
        """now() 返回带 +8 偏移的时区感知时间。"""
        assert timeutil.now().utcoffset() == datetime.timedelta(hours=8)

    def test_now_respects_custom_offset(self):
        """now() 应尊重传入的偏移。"""
        assert timeutil.now(0).utcoffset() == datetime.timedelta(0)

    def test_now_is_timezone_aware(self):
        """返回值必须带 tzinfo，否则无法与窗口时间比较。"""
        assert timeutil.now().tzinfo is not None

    def test_now_ms_is_millisecond_timestamp(self):
        """now_ms() 返回毫秒级 Unix 时间戳。"""
        before = int(time.time() * 1000)
        value = timeutil.now_ms()
        after = int(time.time() * 1000)

        assert isinstance(value, int)
        assert before <= value <= after


class TestFormatTimestamp:
    """时间戳格式化。"""

    def test_epoch_is_rendered_in_utc_plus_8(self):
        """Unix 0 应显示为北京时间 08:00——验证用的是 UTC+8 而非 UTC。"""
        assert timeutil.format_timestamp(0) == "1970-01-01 08:00:00"

    def test_custom_offset_changes_rendering(self):
        """同一时间戳在不同偏移下渲染不同。"""
        assert timeutil.format_timestamp(0, 0) == "1970-01-01 00:00:00"

    def test_invalid_timestamp_is_returned_as_string(self):
        """超出可表示范围的时间戳返回原始值的字符串形式，不抛异常。"""
        assert timeutil.format_timestamp(-(10**30)) == str(-(10**30))

    def test_round_trip_with_now(self):
        """now() 生成的时刻经格式化后应与自身字段一致。"""
        moment = timeutil.now()
        formatted = timeutil.format_timestamp(int(moment.timestamp()))

        assert formatted == moment.strftime("%Y-%m-%d %H:%M:%S")


class TestLocalTimezoneOffset:
    """宿主机时区探测（仅用于启动提示）。"""

    def test_returns_float_or_none(self):
        """不断言具体值——CI 机器时区各不相同，只要求类型正确。"""
        result = timeutil.local_timezone_offset()

        assert result is None or isinstance(result, float)

    def test_returns_none_when_platform_lookup_fails(self, monkeypatch):
        """底层时区查询抛异常时降级为 None，不影响程序启动。

        实现里 ``time.daylight`` 为假时会短路、不调用 ``time.localtime()``，
        因此这里把 daylight 置 1 以强制走到查询分支（模拟夏令时地区）。
        """

        def _raise_oserror(*args, **kwargs):
            raise OSError("localtime unavailable")

        monkeypatch.setattr(timeutil.time, "daylight", 1)
        monkeypatch.setattr(timeutil.time, "localtime", _raise_oserror)

        assert timeutil.local_timezone_offset() is None
