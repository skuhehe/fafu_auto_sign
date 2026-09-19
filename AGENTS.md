# FAFU Auto Sign - 项目知识库

**项目**: 数字FAFU自动签到助手  
**技术栈**: Python 3.10+ / Pydantic / Requests  
**核心功能**: 福建农林大学数字FAFU APP自动签到（逆向工程实现）

---

## 项目结构

```
fafu_auto_sign/
├── src/fafu_auto_sign/          # 核心源代码
│   ├── __init__.py              # 包初始化
│   ├── __main__.py              # python -m 入口点（--config/--once/--state/--ignore-backoff）
│   ├── main.py                  # 主应用逻辑（守护进程 + 失败退避）
│   ├── config.py                # Pydantic配置管理
│   ├── client.py                # HTTP客户端（带重试 + 请求节流）
│   ├── crypto.py                # 签名算法（MD5+Base64）
│   ├── state.py                 # 运行期状态持久化（原子写/跨进程锁/增量合并）
│   ├── timeutil.py              # 业务时区工具（固定 UTC+8）
│   ├── graceful_shutdown.py     # 信号处理/优雅关闭
│   ├── logging_config.py        # 日志配置（JSON+轮转）
│   └── services/                # 业务服务层
│       ├── task_service.py      # 任务识别与管理（含 signState 跳过已签）
│       ├── sign_service.py      # 签到提交（GPS抖动 + 响应体成功判定）
│       ├── upload_service.py    # 图片上传（七牛云）
│       └── notification_service.py  # 微信推送通知（Server酱）
├── tests/                       # 测试套件
├── pyproject.toml               # 项目元数据与依赖
├── state.json                   # 运行期状态（失败退避，已 gitignore）
├── config.json                  # 用户配置文件（本地）
└── config.json.example          # 配置模板
```

---

## 查找位置指引

| 任务 | 位置 | 关键文件 |
|------|------|----------|
| **添加新配置项** | `config.py` | `AppConfig` 类 |
| **修改签名算法** | `crypto.py` | `generate_auth_header()` |
| **调整重试逻辑** | `client.py` | `FAFUClient.request()` |
| **调整请求节流/429退避** | `client.py` | `FAFUClient._throttle()`, `min_request_interval`, `RATE_LIMIT_BACKOFF` |
| **判断响应体是否含某字段** | `client.py` | `response_contains_field()` |
| **修改签到逻辑** | `services/sign_service.py` | `SignService.submit_sign()`, `probe_sign_response()` |
| **调整成功判定字段** | `config.py` + `services/sign_service.py` | `sign_success_field`, `DEFAULT_SUCCESS_FIELD` |
| **修改任务识别** | `services/task_service.py` | `TaskService.get_pending_tasks()` |
| **调整「跳过已签到」判定** | `services/task_service.py` | `TaskService._extract_sign_state()` |
| **修改失败退避** | `state.py` + `main.py` | `BackoffState`, `BACKOFF_SCHEDULE`, `run()` 中 `record_failure/record_success` |
| **修改状态文件读写** | `state.py` | `StateStore.load()/update()`, `state_path` 配置项 |
| **修改时区处理** | `timeutil.py` + `main.py` | `now()`, `format_timestamp()`, `warn_timezone_mismatch()` |
| 修改图片上传 | `services/upload_service.py` | `UploadService.upload_image()`, `SUPPORTED_EXTENSIONS` |
| 添加多图片支持 | `config.py` + `upload_service.py` | `image_dir` 配置 + 目录扫描 + 随机选择 |
| **修改日志格式** | `logging_config.py` | `setup_logging()` |
| **修改关闭逻辑** | `graceful_shutdown.py` | `GracefulShutdown` 类 |
| **修改主循环** | `main.py` | `run()` 函数 |
| **添加测试** | `tests/` | 使用 `conftest.py` fixtures |
| **添加通知功能** | `services/notification_service.py` | `NotificationService` 类 |
| **修改通知配置** | `config.py` | `notification_enabled`, `serverchan_key` |
| **修改日志通知** | `logging_config.py` | `NotificationHandler` |
| **集成通知流程** | `main.py`, `client.py` | 初始化 `NotificationService`, 致命错误前发送通知 |

---

## 代码约定

### 导入风格
```python
# 1. 标准库
import logging
from pathlib import Path

# 2. 第三方库
import requests
from pydantic import Field

# 3. 项目内部（绝对导入）
from fafu_auto_sign.config import AppConfig
from fafu_auto_sign.client import FAFUClient
```

### 类型注解（强制）
```python
# 所有函数必须有类型注解（mypy严格要求）
def process_task(task_id: str) -> Optional[TaskDetails]:
    ...
```

### 日志使用模式
```python
# 类中使用 self.logger
self.logger = logging.getLogger(self.__class__.__name__)
self.logger.info(f"[*] 操作: {value}")     # 关键步骤
self.logger.debug(f"详情: {value}")         # 调试信息
self.logger.warning(f"[!] 警告: {value}")   # 需要注意
self.logger.error(f"[x] 错误: {value}")     # 错误信息
```

### 错误处理
```python
# 网络错误 - 在 client.py 中统一处理重试
# 业务错误 - 在服务层捕获并记录，返回 None/False 而非抛出
# 致命错误 - Token过期(401)或时间错误(408)直接 sys.exit(1)
```

---

## 反模式（禁止）

| 禁止行为 | 原因 | 正确做法 |
|----------|------|----------|
| 使用裸 `except:` | 会捕获 KeyboardInterrupt | 使用 `except Exception:` 或具体异常 |
| 相对导入 (`from . import`) | 不符合项目约定 | 使用绝对导入 `from fafu_auto_sign...` |
| 手动字符串拼接URL | 易出错 | 使用 f-string 并确保 `/` 处理正确 |
| 硬编码配置值 | 无法灵活部署 | 使用 Pydantic 配置类 |
| 忽略文件句柄关闭 | 资源泄漏 | 使用 `with open()` 上下文管理器 |
| 取消 `as any` 类型断言 | mypy会报错 | 添加正确的类型注解 |
| 修改 `SECRET_KEY` | 会导致签名失效 | 保持逆向获取的原始值 |
| 硬编码成功判定字段 | 服务端结构变化时无法调整 | 用配置项 `sign_success_field` |
| 测试中新建 `FAFUClient` 不关闭节流 | 套件真实 sleep，会超时 | 设 `client.min_request_interval = 0.0` |
| 测试中读写项目根目录的 `state.json` | 用例依赖本机运行数据 | 用 `tmp_path` 传 `state_path` |
| 用裸 `time.time()` 做窗口判断 | 忽略业务时区，部署到 UTC 会错判 | 用 `fafu_auto_sign.timeutil` |

---

## 配置优先级

1. 环境变量 (`FAFU_USER_TOKEN` 等)
2. `.env` 文件
3. JSON 配置文件 (`config.json`)
4. 默认值（代码中定义）

---

## 运行期行为要点（易踩坑）

### 请求节流

- `FAFUClient._last_request_at` 是**类属性**，同一进程内多个客户端共享节流窗口。
- 节流发生在 `request()` 的重试循环里、`session.request()` **之前**，因此每次重试尝试都会节流。
- **写测试时必须关闭节流**：`client.min_request_interval = 0.0`。默认 2 秒会让套件从 20 余秒涨到超时（实测 >60 秒被杀）。conftest 的 autouse fixture 只重置计时器，**不会**改配置。

### 429 长退避

- `RATE_LIMIT_BACKOFF = (30, 60, 120)`，仅对 429 生效；其余 `RETRY_STATUS_CODES` 仍用 `1/2/4` 指数退避。
- 不要写 `mock_sleep.assert_called_once_with(...)` 这类「精确次数」断言：节流与退避都调用 `time.sleep`，会计入同一个 mock。

### 失败退避（`state.py`）

- 语义：**请求级失败**（`ConnectionError`/`RequestException`/处理任务异常）才推进退避；**「没有任务」不算失败**。
- 退避状态持久化在 `state_path`（默认 `state.json`），常驻进程与 `--once` 共享。
- `StateStore.update()` 以**磁盘最新内容**为基准增量合并——长驻进程内存快照可能过期，按内存全量覆盖会抹掉其他进程写入的键。
- 锁用 `O_CREAT|O_EXCL` 锁文件 + mtime 判残留（不依赖 `fcntl`），写盘用 `os.replace` 原子替换。
- 写测试请用 `tmp_path` 传路径，**不要**碰项目根目录的真实 `state.json`：否则用例结果会依赖本机运行数据。

### 成功判定（⚠️ 未经真实响应验证）

- 规则：状态码 2xx **且**响应体含 `sign_success_field`（默认 `timestamp`）。
- **只看状态码会误报**：服务端可能返回 200 而业务失败，响应体是错误信息或 WAF 的 HTML。
- `timestamp` 这一判据来自跨项目逆向记录，未在本项目用真实响应验证；字段名是**配置项**，服务端结构不同时改配置即可，不要改回硬编码。

### 业务时区（UTC+8）

- 窗口判断与日志时间统一走 `timeutil`，按 `timezone_offset`（默认 8）计算，**不依赖宿主机时区**。
- `services/task_service.py` 已改用 `fafu_auto_sign.timeutil.now_ms()`，不要再引入裸 `time.time()` 做时间判断。

### 跳过已签到任务

- `TaskService._extract_sign_state()` 读 `signInStudent.signState`：0 为未签到、非 0 为已签到。
- 字段缺失或不可解析时返回 `None` → 按未知处理并**照常尝试签到**（保守策略，避免漏签）。

### Pydantic v2

- 模型字段**不是类属性**：`monkeypatch.setattr(AppConfig, "min_request_interval", 0.0)` 完全无效（读取会走 `__getattr__` 拿到字段定义并抛 `AttributeError`）。要改默认值请改实例属性或 `model_fields[...].default`。
- 实例赋值与 `object.__setattr__` 都**不经过**校验器，绕过构造会静默丢失边界校验。

---

## 常用命令

```bash
# 开发安装
pip install -e ".[dev]"

# 运行程序
python -m fafu_auto_sign
python -m fafu_auto_sign --config /path/to/config.json

# 或安装后使用脚本
fafu-auto-sign

# 测试
pytest
pytest --cov=fafu_auto_sign --cov-report=html

# 代码格式化
black src/ tests/
isort src/ tests/

# 类型检查
mypy src/
```

---

## 重要注意事项

### Token获取（必须手动）
1. 使用手机抓包工具（Stream/ProxyPin/HttpCanary）
2. 打开数字FAFU APP，进入签到页面
3. 查找 `stuhtapi.fafu.edu.cn` 域名的请求
4. 提取 Header 中的 `Authorization` 字段
5. Base64解码，取 `2_` 开头的最后一段

### 心跳保活机制
- 默认每 15 分钟运行一次循环
- 通过轻量级请求保持 Session 存活
- 处于失败退避期时跳过本轮**请求**，但仍按心跳间隔唤醒（不是 `continue` 整个循环，`--ignore-backoff` 可绕过）
- 支持 SIGINT/SIGTERM 优雅关闭

### GPS抖动（防检测）
- 默认抖动量: `0.00005`（约5米）
- 配置范围: 0 到 0.001
- 每次签到随机生成偏移量

### 关键密钥
```python
# crypto.py 中硬编码，来自逆向工程
SECRET_KEY = "AtPs2O1xEnhwkKDV"  # 切勿修改
```

### 生产部署建议
```bash
# Linux后台运行
nohup python -m fafu_auto_sign > sign.log 2>&1 &

# 或使用 systemd（推荐）
```

---

## 微信推送通知

### 配置说明
- `notification_enabled`: 是否启用微信推送（默认 false）
- `serverchan_key`: Server酱 SendKey（启用时必需）

### 功能特点
- 签到成功/失败实时微信通知
- Token过期、时间错误等紧急情况即时告警
- 5分钟内同类型消息自动去重

### 获取 SendKey
1. 访问 https://sct.ftqq.com/
2. 微信扫码登录
3. 复制 SendKey（格式 SCTxxxxx）

### 使用示例
```json
{
  "notification_enabled": true,
  "serverchan_key": "SCT1234567890"
}
```

---

## 测试策略

| 测试类型 | 文件模式 | 说明 |
|----------|----------|------|
| 单元测试 | `test_*.py` | 单个函数/类测试 |
| 特性测试 | `test_*_characterization.py` | 行为验证（黄金主文件） |
| 集成测试 | `test_integration.py` | 多模块协同测试 |
| Fixtures | `conftest.py` | 共享测试数据 |

新增模块对应的测试文件：

| 模块 | 测试文件 |
|---|---|
| `state.py`（失败退避/状态持久化） | `tests/test_state.py` |
| `timeutil.py`（业务时区） | `tests/test_timeutil.py` |
| `main.py` 失败退避集成 | `tests/test_main_backoff.py` |
| `main.py` 时区提示 | `tests/test_main_timezone.py` |
| `task_service._extract_sign_state` | `tests/test_task_sign_state.py` |

---

## 技术实现要点

### 授权头生成（逆向工程）
```
Sign = MD5(SECRET_KEY + CleanURL + Timestamp + Nonce)
Auth = Base64(Timestamp:Nonce:Sign:UserToken)
```

### 任务识别逻辑
1. 获取任务列表（POST `/health-api/sign_in/student/my/page`）
2. 过滤时间窗口：`beginTime <= now <= endTime`
3. 关键词匹配：任务名称包含"晚归"
4. 读 `signInStudent.signState`：非 0 视为已签到，跳过（字段缺失时保守尝试）
5. 获取任务详情提取位置坐标

### 签到流程
1. 获取待办任务 → 2. 获取任务详情（含位置）→ 3. 上传图片 → 4. 提交签到（含GPS抖动）
→ 5. 按响应体字段判定成功 → 6. 成功清零退避 / 请求级失败推进退避

### 新增配置项一览（P0/P1 改进）
| 配置项 | 环境变量 | 默认值 | 作用 |
|---|---|---|---|
| `min_request_interval` | `FAFU_MIN_REQUEST_INTERVAL` | `2.0` | 请求最小间隔（秒），规避 WAF 限流 |
| `timezone_offset` | `FAFU_TIMEZONE_OFFSET` | `8` | 业务时区偏移（小时） |
| `state_path` | `FAFU_STATE_PATH` | `state.json` | 失败退避状态文件路径 |
| `sign_success_field` | `FAFU_SIGN_SUCCESS_FIELD` | `timestamp` | 成功判定字段名（⚠️ 判据未验证） |

### 通知服务逻辑
- `NotificationService.notify()` - 发送微信推送（非阻塞）
- `_should_notify()` - 5分钟去重检查（task_id + success）
- `NotificationHandler` - 监听日志标记触发通知
- 致命错误前发送通知（401/408状态码）
