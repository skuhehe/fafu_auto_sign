"""运行期状态持久化。

用途
----
1. **失败退避**：连续失败后把「下次允许尝试的时间」落盘。否则常驻进程会在
   服务端限流期间仍按固定周期重试，把限流窗口越拖越长（甚至正好覆盖签到窗口）。
2. **跨进程共享**：``--once`` 手动运行与常驻守护进程之间共享退避状态，
   避免手动运行绕过退避、反复触发服务端风控。
3. **可观测性**：记录最近一次成功/失败时间，便于排查。

设计要点
--------
- **原子写入**：先写同目录临时文件再 ``os.replace``，避免写到一半被中断留下半截 JSON。
- **跨进程互斥**：用 ``O_CREAT|O_EXCL`` 锁文件，Windows 与 POSIX 通用，
  不依赖 ``fcntl``/``msvcrt``；持有者被强杀留下的残留锁按 mtime 判过期。
- **增量合并**：写入时以**磁盘最新内容**为基准只应用本次的键。长驻进程内存中的
  快照可能已过期，若按内存全量覆盖会抹掉其他进程刚写入的键。
- **权限最小化**：状态文件含会话相关信息，落盘后 ``chmod 600``（失败不致命，
  因为 Windows 上不支持该语义）。
"""

import contextlib
import json
import logging
import os
import random
import time
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

logger = logging.getLogger(__name__)

#: 获取锁的最长等待时间（秒）
LOCK_TIMEOUT = 5.0

#: 锁文件超过此时长视为残留（持有者已异常退出）
LOCK_STALE = 30.0

#: 默认状态文件路径（相对启动目录）
DEFAULT_STATE_FILENAME = "state.json"

#: 失败退避阶梯（秒）：1 分钟 → 5 分钟 → 30 分钟 → 2 小时
BACKOFF_SCHEDULE = (60, 300, 1800, 7200)


class StateStore:
    """基于 JSON 文件的轻量状态仓库（原子写 + 跨进程锁 + 增量合并）。"""

    def __init__(self, path: str | Path = DEFAULT_STATE_FILENAME) -> None:
        """初始化状态仓库。

        参数:
            path: 状态文件路径；文件缺失或损坏时按空状态处理。
        """
        self.path = Path(path)
        self._lock_path = self.path.with_name(self.path.name + ".lock")

    # ------------------------------------------------------------------ 读取

    def load(self) -> Dict[str, Any]:
        """读取状态；文件缺失、损坏或非对象时返回空字典（不抛异常）。"""
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def get(self, key: str, default: Any = None) -> Any:
        """读取单个键。"""
        return self.load().get(key, default)

    # ------------------------------------------------------------------ 写入

    @contextlib.contextmanager
    def _lock(self) -> Iterator[None]:
        """跨进程互斥锁（``O_CREAT|O_EXCL`` 锁文件实现）。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.time() + LOCK_TIMEOUT
        fd: Optional[int] = None
        while fd is None:
            try:
                fd = os.open(self._lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                if self._lock_is_stale():
                    self._remove(self._lock_path)  # 残留锁：持有者已异常退出
                    continue
                if time.time() >= deadline:
                    raise TimeoutError(f"等待状态锁超时：{self._lock_path}")
                time.sleep(0.05)
        try:
            yield
        finally:
            os.close(fd)
            self._remove(self._lock_path)

    def _lock_is_stale(self) -> bool:
        """锁文件是否已过期。"""
        try:
            return time.time() - os.path.getmtime(self._lock_path) > LOCK_STALE
        except OSError:
            return False

    @staticmethod
    def _remove(path: Path) -> None:
        """删除文件，忽略不存在等错误。"""
        try:
            os.remove(path)
        except OSError:
            pass

    def update(self, **values: Any) -> Dict[str, Any]:
        """以磁盘最新内容为基准，增量合并本次键值并原子落盘。

        参数:
            **values: 要写入的键值对（值为 ``None`` 表示删除该键）。

        返回:
            合并后的完整状态字典。
        """
        with self._lock():
            merged = self.load()
            for key, value in values.items():
                if value is None:
                    merged.pop(key, None)
                else:
                    merged[key] = value
            self._write_atomic(merged)
        return merged

    def _write_atomic(self, data: Dict[str, Any]) -> None:
        """原子写入状态文件并收紧权限。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # 临时文件名含 PID + 随机数，避免多进程并发时互相覆盖
        tmp = self.path.with_name(
            f"{self.path.name}.{os.getpid()}.{random.randrange(1 << 30)}.tmp"
        )
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
            os.replace(tmp, self.path)  # 同目录 rename 在主流平台上原子
            self._restrict_permissions()
        finally:
            self._remove(tmp)

    def _restrict_permissions(self) -> None:
        """把状态文件权限收紧到 0600；平台不支持时忽略。"""
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass


class BackoffState:
    """失败退避状态的读写封装。

    退避语义：连续失败 ``n`` 次后，需等待 ``BACKOFF_SCHEDULE[n-1]`` 秒才允许再次尝试；
    任意一次成功都会把计数清零。**失败同样会写入下次可尝试时间**——这是关键，
    否则调用方会在每次循环里重打整条请求链，把自己打进服务端限流。
    """

    #: 状态文件中使用的键名
    KEY_FAILURES = "delay_failures"
    KEY_NEXT_ATTEMPT = "delay_next_attempt_at"
    KEY_LAST_SUCCESS = "delay_last_success_at"
    KEY_LAST_FAILURE = "delay_last_failure_at"

    def __init__(self, store: StateStore) -> None:
        """绑定一个状态仓库。"""
        self.store = store

    def remaining_wait(self) -> float:
        """返回距下次允许尝试的剩余秒数；``<= 0`` 表示当前可以尝试。"""
        try:
            next_at = float(self.store.get(self.KEY_NEXT_ATTEMPT, 0) or 0)
        except (TypeError, ValueError):
            return 0.0
        return next_at - time.time()

    def is_blocked(self) -> bool:
        """当前是否处于退避期。"""
        return self.remaining_wait() > 0

    def record_success(self) -> None:
        """记录一次成功：清零失败计数与退避时间。"""
        self.store.update(
            **{
                self.KEY_FAILURES: 0,
                self.KEY_NEXT_ATTEMPT: 0,
                self.KEY_LAST_SUCCESS: time.time(),
            }
        )

    def record_failure(self) -> float:
        """记录一次失败并按阶梯推进退避。

        返回:
            本次写入的退避秒数。
        """
        try:
            failures = int(self.store.get(self.KEY_FAILURES, 0) or 0)
        except (TypeError, ValueError):
            failures = 0
        failures = min(failures + 1, len(BACKOFF_SCHEDULE))
        delay = BACKOFF_SCHEDULE[failures - 1]
        self.store.update(
            **{
                self.KEY_FAILURES: failures,
                self.KEY_NEXT_ATTEMPT: time.time() + delay,
                self.KEY_LAST_FAILURE: time.time(),
            }
        )
        logger.warning(f"连续失败 {failures} 次，退避 {delay} 秒后重试")
        return float(delay)

    def reset(self) -> None:
        """清空退避状态（用于人工重置）。"""
        self.store.update(
            **{
                self.KEY_FAILURES: 0,
                self.KEY_NEXT_ATTEMPT: 0,
            }
        )
