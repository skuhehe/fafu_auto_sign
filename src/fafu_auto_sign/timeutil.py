"""业务时区工具。

FAFU 服务端按**北京时间（UTC+8，中国全年无夏令时）**判定签到窗口，
并对请求签名中的时间戳做新鲜度校验（偏移过大时返回 408）。

因此本项目**不依赖系统本地时区**：即使部署在时区为 UTC 的云服务器上，
线上报时间和窗口判断仍按配置的 ``timezone_offset``（默认 +8）计算。
"""

import datetime
import time
from typing import Optional

#: 北京时间固定偏移（小时），中国不使用夏令时
CN_TZ_OFFSET = 8


def get_timezone(offset_hours: int = CN_TZ_OFFSET) -> datetime.timezone:
    """构造带指定小时偏移的时区对象。

    参数:
        offset_hours: 相对 UTC 的小时偏移，默认 +8（北京时间）。

    返回:
        对应的 ``datetime.timezone`` 实例。
    """
    return datetime.timezone(datetime.timedelta(hours=offset_hours), f"UTC{offset_hours:+d}")


def now(offset_hours: int = CN_TZ_OFFSET) -> datetime.datetime:
    """返回业务时区的当前时间（带时区信息）。"""
    return datetime.datetime.now(get_timezone(offset_hours))


def now_ms() -> int:
    """返回当前 Unix 毫秒时间戳。

    时间戳本身与时区无关，这里单独提供以便统一调用点。
    """
    return int(time.time() * 1000)


def format_timestamp(timestamp_s: int, offset_hours: int = CN_TZ_OFFSET) -> str:
    """把 Unix 秒级时间戳格式化为业务时区的 ``YYYY-MM-DD HH:MM:SS``。

    用于日志展示，避免部署机时区不同造成阅读歧义。

    参数:
        timestamp_s: Unix 秒级时间戳。
        offset_hours: 相对 UTC 的小时偏移。

    返回:
        格式化后的本地时间字符串；时间戳非法时返回原始值的字符串形式。
    """
    try:
        dt = datetime.datetime.fromtimestamp(timestamp_s, get_timezone(offset_hours))
    except (OverflowError, OSError, ValueError):
        return str(timestamp_s)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def local_timezone_offset() -> Optional[float]:
    """返回宿主机本地时区相对 UTC 的小时偏移，取不到时返回 None。

    用于启动时提示部署者「系统时区与业务时区不一致」。
    实现注意::

        time.timezone 的语义是「UTC 以西的秒数」，因此取负号才得到
        「本地时间 − UTC」的常识偏移（东八区 = -(-28800) / 3600 = +8）。
        夏令时生效时改用 time.altzone。
    """
    try:
        in_dst = time.daylight and time.localtime().tm_isdst > 0
        offset_s = -(time.altzone if in_dst else time.timezone)
    except (AttributeError, OSError, ValueError):
        return None
    return offset_s / 3600
