"""运行期状态持久化模块测试。

覆盖 ``StateStore``（原子写 / 跨进程锁 / 增量合并 / 权限）与
``BackoffState``（失败退避阶梯）两组公开 API。

设计注意::

    所有用例都用 ``tmp_path`` 传入路径，**绝不**写到项目根目录的真实
    ``state.json``——否则会污染本机运行数据，也会让用例之间互相影响。
"""

import json
import os
import time

import pytest

from fafu_auto_sign import state as state_module
from fafu_auto_sign.state import BACKOFF_SCHEDULE, BackoffState, StateStore


@pytest.fixture
def store(tmp_path):
    """指向临时目录的状态仓库。"""
    return StateStore(tmp_path / "state.json")


class TestStateStoreLoad:
    """读取行为：任何异常情况都必须降级为「空状态」而非抛异常。"""

    def test_load_missing_file_returns_empty_dict(self, store):
        """文件不存在时返回空字典。"""
        assert store.load() == {}

    def test_load_corrupt_json_returns_empty_dict(self, store):
        """内容是损坏 JSON 时返回空字典。"""
        store.path.write_text("{not valid json", encoding="utf-8")

        assert store.load() == {}

    def test_load_non_dict_json_returns_empty_dict(self, store):
        """内容是数组（非对象）时返回空字典。"""
        store.path.write_text("[1, 2, 3]", encoding="utf-8")

        assert store.load() == {}

    def test_load_reads_existing_values(self, store):
        """正常文件应被解析。"""
        store.path.write_text('{"a": 1}', encoding="utf-8")

        assert store.load() == {"a": 1}

    def test_get_returns_value_and_default(self, store):
        """get() 读取单键，缺失时返回默认值。"""
        store.path.write_text('{"a": 1}', encoding="utf-8")

        assert store.get("a") == 1
        assert store.get("missing") is None
        assert store.get("missing", "fallback") == "fallback"


class TestStateStoreUpdate:
    """写入行为：增量合并是本模块最关键的正确性保证。"""

    def test_update_merges_with_existing_disk_content(self, store):
        """update() 必须以磁盘最新内容为基准增量合并。

        这是最关键的一条：长驻进程内存中的快照可能已过期，
        若按内存全量覆盖，会抹掉其他进程刚写入的键。
        """
        store.path.write_text('{"a": 1}', encoding="utf-8")

        merged = store.update(b=2)

        assert merged == {"a": 1, "b": 2}
        assert store.load() == {"a": 1, "b": 2}

    def test_update_with_none_removes_key(self, store):
        """值为 None 表示删除该键。"""
        store.path.write_text('{"a": 1, "b": 2}', encoding="utf-8")

        merged = store.update(a=None)

        assert "a" not in merged
        assert merged == {"b": 2}
        assert store.load() == {"b": 2}

    def test_update_removing_absent_key_is_noop(self, store):
        """删除不存在的键不应报错，也不应影响其他键。"""
        store.path.write_text('{"a": 1}', encoding="utf-8")

        merged = store.update(missing=None)

        assert merged == {"a": 1}

    def test_update_creates_parent_directory(self, tmp_path):
        """目标目录不存在时应自动创建。"""
        nested = StateStore(tmp_path / "nested" / "deeper" / "state.json")

        merged = nested.update(a=1)

        assert merged == {"a": 1}
        assert nested.load() == {"a": 1}

    def test_update_leaves_no_tmp_file(self, store):
        """原子写完成后不得在目录里残留临时文件。"""
        store.update(a=1)

        leftovers = [p.name for p in store.path.parent.iterdir() if p.name.endswith(".tmp")]
        assert leftovers == []

    def test_update_does_not_leave_lock_file(self, store):
        """正常释放后不应留下锁文件。"""
        store.update(a=1)

        assert not store._lock_path.exists()

    @pytest.mark.skipif(os.name != "posix", reason="Windows 不支持 POSIX 权限位")
    def test_update_restricts_permissions_to_0600(self, store):
        """状态文件含会话相关信息，落盘后权限应收紧到 0600。"""
        store.update(a=1)

        assert store.path.stat().st_mode & 0o777 == 0o600

    def test_restrict_permissions_ignores_oserror(self, store, monkeypatch):
        """chmod 失败不应让写入整体失败（Windows 上无此语义）。"""
        store.update(a=1)

        def _raise_oserror(*args, **kwargs):
            raise OSError("chmod not supported")

        monkeypatch.setattr(state_module.os, "chmod", _raise_oserror)

        store._restrict_permissions()  # 不应抛异常


class TestStateStoreLock:
    """跨进程锁：O_CREAT|O_EXCL 锁文件 + 残留锁按 mtime 判过期。"""

    def test_lock_is_exclusive(self, store, monkeypatch):
        """已被持有的锁会让第二个获取者等待超时。

        锁是文件级的，因此同一进程内的第二个实例同样会被挡住。
        """
        monkeypatch.setattr(state_module, "LOCK_TIMEOUT", 0.01)
        other = StateStore(store.path)

        with store._lock():
            with pytest.raises(TimeoutError):
                with other._lock():
                    pass

    def test_lock_is_released_after_context_exit(self, store):
        """退出上下文后可被再次获取。"""
        with store._lock():
            pass

        with store._lock():
            pass

    def test_stale_lock_is_reclaimed(self, store, monkeypatch):
        """残留锁（mtime 远早于 LOCK_STALE）应被清除并成功获取。"""
        store.path.parent.mkdir(parents=True, exist_ok=True)
        store._lock_path.write_text("", encoding="utf-8")
        stale_age = state_module.LOCK_STALE + 120
        old = time.time() - stale_age
        os.utime(store._lock_path, (old, old))

        with store._lock():
            pass

        assert not store._lock_path.exists()

    def test_lock_is_stale_returns_false_when_file_missing(self, store):
        """锁文件不存在时按「未过期」处理（getmtime 抛 OSError 的兜底）。"""
        assert store._lock_is_stale() is False

    def test_lock_is_stale_returns_false_for_fresh_lock(self, store):
        """刚创建的锁不算残留。"""
        store.path.parent.mkdir(parents=True, exist_ok=True)
        store._lock_path.write_text("", encoding="utf-8")

        assert store._lock_is_stale() is False


class TestBackoffState:
    """失败退避阶梯。"""

    @pytest.fixture
    def backoff(self, store):
        return BackoffState(store)

    def test_starts_unblocked(self, backoff):
        """初始状态可以立即尝试。"""
        assert backoff.is_blocked() is False
        assert backoff.remaining_wait() <= 0

    def test_first_failure_returns_first_schedule_step(self, backoff, store):
        """首次失败退避 60 秒并进入阻塞状态。"""
        assert backoff.record_failure() == 60.0
        assert backoff.is_blocked() is True
        assert store.get(BackoffState.KEY_FAILURES) == 1

    def test_successive_failures_walk_the_schedule(self, backoff):
        """连续失败按阶梯 60 → 300 → 1800 → 7200 推进。"""
        assert [backoff.record_failure() for _ in range(len(BACKOFF_SCHEDULE))] == [
            60.0,
            300.0,
            1800.0,
            7200.0,
        ]

    def test_failures_beyond_schedule_stay_at_last_step(self, backoff, store):
        """超过阶梯长度后应停在最后一档，而不是索引越界。"""
        for _ in range(len(BACKOFF_SCHEDULE)):
            backoff.record_failure()

        assert backoff.record_failure() == 7200.0
        assert backoff.record_failure() == 7200.0
        assert store.get(BackoffState.KEY_FAILURES) == len(BACKOFF_SCHEDULE)

    def test_remaining_wait_is_positive_during_backoff(self, backoff):
        """退避期内剩余等待为正且不超过本档秒数。"""
        backoff.record_failure()

        remaining = backoff.remaining_wait()
        assert 0 < remaining <= 60.0

    def test_record_success_clears_failures_and_backoff(self, backoff, store):
        """成功后失败计数归零且不再阻塞。"""
        backoff.record_failure()
        backoff.record_failure()

        backoff.record_success()

        assert store.get(BackoffState.KEY_FAILURES) == 0
        assert backoff.remaining_wait() <= 0
        assert backoff.is_blocked() is False
        assert store.get(BackoffState.KEY_LAST_SUCCESS) is not None

    def test_record_failure_records_last_failure_timestamp(self, backoff, store):
        """失败时应记录时间戳，便于排查。"""
        backoff.record_failure()

        assert store.get(BackoffState.KEY_LAST_FAILURE) is not None

    def test_remaining_wait_with_non_numeric_state_returns_zero(self, backoff, store):
        """状态被外部写脏（非数字）时应返回 0.0 而不是抛异常。"""
        store.update(**{BackoffState.KEY_NEXT_ATTEMPT: "not-a-number"})

        assert backoff.remaining_wait() == 0.0

    def test_record_failure_with_non_numeric_counter_resets_to_zero(self, backoff, store):
        """失败计数被写脏时按 0 起算，避免抛出异常。"""
        store.update(**{BackoffState.KEY_FAILURES: "abc"})

        assert backoff.record_failure() == 60.0

    def test_reset_clears_counter_and_backoff(self, backoff, store):
        """reset() 清空计数与退避时间。"""
        backoff.record_failure()

        backoff.reset()

        assert store.get(BackoffState.KEY_FAILURES) == 0
        assert backoff.remaining_wait() <= 0

    def test_state_is_shared_between_instances(self, store):
        """两个实例读同一文件时应看到同一退避状态（跨进程共享语义）。"""
        BackoffState(store).record_failure()

        assert BackoffState(StateStore(store.path)).is_blocked() is True

    def test_failure_state_is_written_to_disk_as_json(self, backoff, store):
        """退避状态必须以可解析 JSON 落盘。"""
        backoff.record_failure()

        payload = json.loads(store.path.read_text(encoding="utf-8"))
        assert payload[BackoffState.KEY_FAILURES] == 1
