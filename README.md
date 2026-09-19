## 🏫 数字 FAFU 自动签到助手 (FAFU Auto Sign)

![Python 3.10+](https://img.shields.io/badge/Python-3.10+-blue.svg) ![License MIT](https://img.shields.io/badge/License-MIT-green.svg) ![Status Stable](https://img.shields.io/badge/Status-Stable-brightgreen.svg)

本项目是针对福建农林大学与华为 WeLink 合作推出的"数字FAFU" APP 所编写的**自动签到程序**。通过逆向分析其前端加密逻辑，本项目实现了完全脱离 APP 的纯接口级自动化签到。

### ✨ 核心特性

✅ **完美逆向签名算法**：内置已被破解的 `Authorization` 请求头动态加密生成规则（MD5+Base64），无缝伪装官方 APP 请求。

✅ **心跳保活机制 (Keep-Alive)**：通过定时发送轻量级请求，保持后端 Session 存活，**彻底解决 Token 短期过期问题，实现一次抓包，一劳永逸！**

✅ **智能任务识别**：自动遍历任务列表，根据时间戳与自定义关键词精准识别当前有效的签到任务，过滤历史过期任务。

✅ **动态位置获取**：通过任务详情接口自动获取签到位置坐标，**无需手动配置经纬度**，适应不同签到地点。

✅ **防封控策略 (Anti-Ban)**：提交签到时自动为经纬度添加安全范围内的随机偏移量（Float微调），模拟真实人类定位的 GPS 漂移现象。

✅ **可选自动图片上传**：开启配置后自动读取图片文件，对接七牛云接口实现上传与签到绑定，默认关闭。

✅ **多图片随机选择**：支持从指定目录随机选择图片上传，避免长期使用同一张照片被识别，支持 `.jpg`, `.jpeg`, `.png`, `.gif`, `.webp` 格式。

✅ **优雅关闭**：支持 SIGINT (Ctrl+C) 和 SIGTERM 信号优雅退出，确保资源正确释放。

✅ **健壮的重试机制**：客户端内置指数退避重试策略，自动处理网络抖动和临时服务不可用。

✅ **微信推送通知**：集成 Server酱，支持签到成功/失败实时推送到微信，5分钟内同类型消息自动去重。

✅ **请求节流与 429 长退避**：同一会话的连续请求保持最小间隔，收到 429（服务端限流）时改用 30/60/120 秒阶梯退避，而不是 1/2/4 秒的短退避。

✅ **持久化失败退避**：请求级失败会写入 `state.json`，常驻进程与 `--once` 手动运行共享同一退避状态；退避期内不再发起请求，避免持续加压把限流窗口拖长。

✅ **跳过已签到任务**：读取任务列表中的 `signInStudent.signState`，本人已签到的任务不再重复提交，减少无谓请求与风控风险。

✅ **固定业务时区**：签到窗口判断与日志时间统一按业务时区（默认 UTC+8）计算，部署在时区为 UTC 的云服务器上也不会错判窗口。

✅ **成功判定看响应体**：不只看 HTTP 状态码——服务端可能返回 200 而业务失败（被风控拦截、任务已失效），因此以「状态码正常且响应体含成功标志字段」为准。

### 🚨 免责声明 (Disclaimer)

1. 本项目开源仅为 Python 网络爬虫、JS 逆向工程及自动化测试技术的**学习与学术交流**。
2. 请遵守学校相关管理规定，切勿用于恶意逃避考勤与监管。
3. **使用者因滥用本项目引发的一切后果与责任由使用者本人自行承担，开发者不承担任何直接或间接责任**。

### 🛠️ 快速开始

#### 1. 环境准备

请确保你的电脑或服务器已安装 Python 3.10 或更高版本。

#### 2. 安装

```bash
# 克隆项目
git clone https://github.com/yourusername/fafu_auto_sign.git
cd fafu_auto_sign

# 以可编辑模式安装（推荐开发使用）
pip install -e .

# 或安装生产依赖
pip install .

# 安装开发依赖（如需运行测试）
pip install -e ".[dev]"
```

#### 3. 获取你的专属 USER_TOKEN (需抓包)

由于涉及华为 WeLink 企业级授权，首次使用需手动抓取属于你的 Token：

1. 在手机上安装抓包工具（如 iOS 的 Stream，Android 的 ProxyPin/HttpCanary 或电脑端的 Fiddler/Charles）。
2. 开启抓包，打开"数字FAFU" APP，进入"签到"页面刷新一下。
3. 在抓包记录中找到域名为 `stuhtapi.fafu.edu.cn` 的请求。
4. 查看请求头（Headers）中的 `Authorization` 字段，你会看到一长串字符（如：`MTc3M...`）。
5. 找一个在线 Base64 解码网站，将这串字符解码。解码后长这样：`1773238142:lnccKsR2ovQ4rbQk:c0a6d234c538193226291c5be73c3461:2_6120909285C95C2DA0CA32C6A2AC76CD`
6. **提取以 2_ 开头的最后一段**（即 `2_6120909285C95C2DA0CA32C6A2AC76CD`），这就是你的 USER_TOKEN！

#### 4. 配置

本项目支持多种配置方式，优先级从高到低：

1. **环境变量** (推荐用于生产/容器部署)
2. **`.env` 文件**
3. **JSON 配置文件**
4. **默认值**

##### 方式一：JSON 配置文件

复制配置文件模板并编辑：

```bash
cp config.json.example config.json
```

然后在 `config.json` 的 `"user_token"` 配置项填入你的 USER_TOKEN。

##### 方式二：环境变量

设置以下环境变量（适用于 Docker、CI/CD 等场景）：

```bash
export FAFU_USER_TOKEN="2_YOUR_TOKEN_HERE"
export FAFU_JITTER="0.00005"
export FAFU_IMAGE_PATH="dorm.jpg"
export FAFU_BASE_URL="http://stuhtapi.fafu.edu.cn"
export FAFU_IMAGE_UPLOAD_ENABLED="false"  # 是否上传签到图片
export FAFU_HEARTBEAT_INTERVAL="900"
export FAFU_NOTIFICATION_ENABLED="false"
export FAFU_SERVERCHAN_KEY=""
export FAFU_IMAGE_DIR="./photos/"  # 图片目录路径（启用随机选择）
export FAFU_TASK_KEYWORDS='["晚归"]'  # 任务关键词列表（JSON格式）
export FAFU_LATEST_IMAGE_DIR=""  # 最新图片目录路径
export FAFU_SIGN_DELAY_MIN="900"  # 签到前最小随机等待时间（秒）
export FAFU_SIGN_DELAY_MAX="2700"  # 签到前最大随机等待时间（秒）
export FAFU_MIN_REQUEST_INTERVAL="2.0"  # 同一会话两次请求的最小间隔（秒）
export FAFU_TIMEZONE_OFFSET="8"  # 业务时区相对 UTC 的小时偏移
export FAFU_STATE_PATH="./state.json"  # 运行期状态文件路径（失败退避）
export FAFU_SIGN_SUCCESS_FIELD="timestamp"  # 判定签到成功的响应体字段名
```

**Windows PowerShell:**
```powershell
$env:FAFU_USER_TOKEN="2_YOUR_TOKEN_HERE"
```

#### 5. 配置项说明

| 配置项 | 必需 | 默认值 | 说明 |
|--------|------|--------|------|
| `user_token` | ✅ | - | 用户令牌（必须以 `2_` 开头） |
| `jitter` | ❌ | `0.00005` | GPS 抖动量（0 到 0.001 之间） |
| `image_path` | ❌ | `dorm.jpg` | 签到照片文件路径（当未配置 `image_dir` 或 `latest_image_dir` 时使用） |
| `image_dir` | ❌ | - | 图片目录路径，设置后将从目录中随机选择图片上传（优先级高于 `image_path`） |
| `image_upload_enabled` | ❌ | `false` | 是否上传签到图片；关闭时不上传且不提交 `signImg` |
| `base_url` | ❌ | `http://stuhtapi.fafu.edu.cn` | API 基础 URL |
| `heartbeat_interval` | ❌ | `900` | 心跳间隔秒数（默认 15 分钟） |
| `sign_delay_min` | ❌ | `900` | 签到前随机等待的最小秒数 |
| `sign_delay_max` | ❌ | `2700` | 签到前随机等待的最大秒数 |
| `min_request_interval` | ❌ | `2.0` | 同一会话两次请求之间的最小间隔（秒），非负且不超过 `60`，用于规避 WAF 限流 |
| `timezone_offset` | ❌ | `8` | 业务时区相对 UTC 的小时偏移（`-12` 到 `14`）；服务端按北京时间 UTC+8 判定签到窗口 |
| `state_path` | ❌ | `state.json` | 运行期状态文件路径，用于持久化失败退避（跨进程共享）；也可用 `--state` 覆盖 |
| `sign_success_field` | ❌ | `timestamp` | 判定签到成功的响应体字段名 ⚠️ 见下方说明 |
| `log_level` | ❌ | `INFO` | 日志级别（DEBUG/INFO/WARNING/ERROR/CRITICAL） |
| `notification_enabled` | ❌ | `false` | 是否启用微信推送通知 |
| `serverchan_key` | ❌ | - | Server酱 SendKey（启用通知时必需）|
| `task_keywords` | ❌ | `["晚归"]` | 任务关键词列表，用于识别需要签到的任务（JSON 数组格式） |
| `latest_image_dir` | ❌ | - | 最新图片目录路径，设置后将使用目录中最新修改的图片,图片使用后自动删除 |
💡 **配置示例**：

如果你想使用多图片随机选择功能，可以在 `config.json` 中配置：

```json
{
  "user_token": "2_YOUR_TOKEN_HERE",
  "jitter": 0.00005,
  "image_dir": "./photos/",
  "image_path": "dorm.jpg",
  "image_upload_enabled": false,
  "base_url": "http://stuhtapi.fafu.edu.cn",
  "heartbeat_interval": 900,
  "sign_delay_min": 900,
  "sign_delay_max": 2700,
  "min_request_interval": 2.0,
  "timezone_offset": 8,
  "state_path": "state.json",
  "sign_success_field": "timestamp",
  "log_level": "INFO",
  "task_keywords": ["晚归", "查寝"],
  "latest_image_dir": "./camera/"
}
```

在 `./photos/` 目录中放入多张图片（支持 `.jpg`, `.jpeg`, `.png`, `.gif`, `.webp` 格式），程序每次签到时会随机选择一张上传。

**图片选择优先级**（从高到低）：
1. `latest_image_dir` - 使用目录中最新修改的图片
2. `image_dir` - 从目录中随机选择图片
3. `image_path` - 使用指定的单张图片

图片上传默认关闭。将 `image_upload_enabled` 设置为 `true` 后，程序才会上传图片并将返回的 URL 放入签到请求的 `signImg` 字段。

**任务关键词说明**：
- 默认只识别包含"晚归"的签到任务
- 可自定义多个关键词，如 `["晚归", "查寝", "点名"]`
- 只要任务名称包含任意一个关键词，就会被识别为待签到任务

**签到前随机延迟说明**：
- 默认每个匹配任务在获取任务详情后随机等待 15–45 分钟，再上传图片并提交签到。
- 等待期间收到 Ctrl+C 或 SIGTERM 时会立即退出。
- 将 `sign_delay_min` 和 `sign_delay_max` 都设为 `0` 可关闭延迟。

#### 运行期行为说明

##### 请求节流与 429 长退避

- 同一进程内的所有请求共享一个节流窗口：两次外发请求之间至少间隔 `min_request_interval` 秒（默认 2 秒），**每次重试尝试也计入**。
- 收到 `429`（服务端限流）时按 `30 → 60 → 120` 秒阶梯退避；其余可重试状态码（`500/502/503/504`）仍走 `1 → 2 → 4` 秒的指数退避。
- 服务端存在 WAF，短时间连续请求容易触发限流，而限流窗口有可能正好覆盖签到时段导致漏签，因此默认开启节流。

##### 失败退避（`state.json`）

- 请求级失败（网络错误、`ConnectionError`/`RequestException`，以及处理任务时的异常）会按 `60 → 300 → 1800 → 7200` 秒阶梯退避，并把「下次允许尝试的时间」写入 `state.json`。
- 退避状态是**持久化且跨进程共享**的：常驻进程与 `python -m fafu_auto_sign --once` 手动运行读同一个文件，避免手动运行绕过退避反复触发风控。
- **「没有待办任务」不算失败**，不会推进退避——否则安静时段会把进程锁进长退避，直接漏掉后续的签到窗口。
- 退避期内程序只记日志、不发请求；需要立即排查时可加 `--ignore-backoff` 绕过。
- 状态文件默认路径为 `state.json`，可用配置项 `state_path` 或命令行 `--state` 指定；已加入 `.gitignore`。

##### 业务时区（UTC+8）

- 签到窗口判断与日志中的时间均按 `timezone_offset`（默认 `8`，即北京时间）计算，**不依赖宿主机时区**。部署在时区为 UTC 的服务器上也能正确工作。
- 启动时若检测到系统时区与业务时区不一致，会打一条 warning 提示（可用 `TZ=Asia/Shanghai` 让本地时间一致）。
- 收到 `408` 说明签名中的时间戳与标准时间偏差过大，请校准系统时间。

##### 跳过已签到任务

- 任务列表中的 `signInStudent.signState` 表示本人是否已签到（`0` 为未签到，非 `0` 为已签到）。
- 已签到的活跃任务会被跳过并记录 `[=]` 日志，不再重复提交签到。
- 该字段缺失或格式异常时按「未知」处理，**照常尝试签到**，避免因字段变更造成漏签。

##### 签到成功判定（⚠️ 判据未经真实响应验证）

- 判定规则为：HTTP 状态码在 2xx **且** 响应体中含有 `sign_success_field` 指定的字段（默认 `timestamp`）。
- 只看状态码是不够的：服务端可能返回 200 而业务上失败（被风控拦截、任务已失效等），此时响应体是错误信息或 WAF 的 HTML 拦截页。这类情况会被判为失败并记录「签到未被服务端确认」。
- **⚠️ 重要说明**：`timestamp` 这一判据来自**跨项目逆向记录**，**未在本项目用真实响应验证**。如果服务端返回结构不同（例如成功标志是 `code`、`success` 或 `resultCode`），签到会被误判为失败。此时请修改配置项 `sign_success_field` 或环境变量 `FAFU_SIGN_SUCCESS_FIELD`，**无需改动代码**。

#### 微信推送通知配置（可选）

本项目支持通过 [Server酱](https://sct.ftqq.com/) 将签到状态实时推送到微信。

**功能特点：**
- 📱 签到成功/失败实时微信通知
- 🔔 Token过期、系统时间错误等紧急情况即时告警
- 🛡️ 5分钟内同类型消息自动去重，防止骚扰
- ⚙️ 配置开关控制，随时启用/禁用

**配置步骤：**

1. **获取 SendKey**
   - 访问 https://sct.ftqq.com/
   - 微信扫码登录
   - 复制 SendKey（格式如 `SCTxxxxx` 或 `SC3xxxxx`）

2. **修改配置文件**
   ```json
   {
     "user_token": "2_YOUR_TOKEN_HERE",
     "notification_enabled": true,
     "serverchan_key": "SCT1234567890abcdef"
   }
   ```

3. **或使用环境变量**
   ```bash
   export FAFU_NOTIFICATION_ENABLED="true"
   export FAFU_SERVERCHAN_KEY="SCT1234567890abcdef"
   ```

#### 6. 运行

```bash
# 使用默认配置文件 (config.json)
python -m fafu_auto_sign

# 只扫描一次并最多处理一个匹配任务，然后退出（跳过签到前延迟）
python -m fafu_auto_sign --once

# 指定配置文件路径
python -m fafu_auto_sign --config /path/to/config.json
# 指定配置文件并单次运行
python -m fafu_auto_sign --once --config /path/to/config.json
# 或简写
python -m fafu_auto_sign -c /path/to/config.json

# 指定运行期状态文件路径（覆盖配置项 state_path）
python -m fafu_auto_sign --state /var/lib/fafu/state.json

# 忽略持久化的失败退避并立即尝试（排查问题时使用）
python -m fafu_auto_sign --once --ignore-backoff

# 使用环境变量（不指定配置文件）
python -m fafu_auto_sign

# 使用控制台脚本（安装后）
fafu-auto-sign
```

`--once` 模式只执行一次任务扫描，最多处理第一个匹配任务，然后退出，并跳过 `sign_delay_min` 和 `sign_delay_max` 配置的延迟。

`--state` 不传时使用配置项 `state_path`（默认 `state.json`）。`--ignore-backoff` 会让程序忽略 `state.json` 中记录的退避时间，适合在确认服务端已恢复后立即重试。

💡 **建议**：由于本程序自带"心跳保活"机制（默认每 15 分钟运行一次），建议将其部署在 24 小时开机的云服务器、树莓派或软路由上。在 Linux 下可使用 `nohup` 命令使其在后台持续运行：

```bash
nohup python -m fafu_auto_sign > sign.log 2>&1 &
```

或使用 systemd 服务（推荐用于生产环境）。

### 🔬 技术内幕 (How it works)

对于爱好技术的同学，本脚本的核心难点在于攻破系统的接口安全校验。

API 使用的 Authorization 并非简单的 JWT，而是一种基于时间的动态签名，其逆向还原逻辑如下：

1. 取 URL 的路径部分（剔除 Query 参数）。
2. 生成当前**精确到秒的 Unix 时间戳** (`Timestamp`)。
3. 生成 16位 随机字符串 (`Nonce`)。
4. 通过 ADB 使电脑连接到手机，安装 LSPosed 模块 Layout Inspect（**需要手机已 ROOT**）启用调试浏览器，运用谷歌或 Edge 浏览器的 chrome://inspect 功能提取前端 JavaScript 代码中硬编码的密钥盐值。
5. 将上述参数拼接：`Secret + URL + Timestamp + Nonce`，计算 **MD5** 哈希值作为签名 (Sign)。
6. 最后将 `Timestamp:Nonce:Sign:UserToken` 通过 Base64 编码，生成最终合法的 Header 头部。

此逻辑已在 `generate_auth_header()` 函数中完美用 Python 复现。

### 🧪 运行测试

本项目包含完整的单元测试和集成测试套件：

```bash
# 运行所有测试
pytest

# 运行测试并生成覆盖率报告
pytest --cov=fafu_auto_sign --cov-report=html

# 运行特定测试文件
pytest tests/test_crypto.py
pytest tests/test_task_service.py
```

### 📁 项目结构

```
fafu_auto_sign/
├── src/
│   └── fafu_auto_sign/
│       ├── __init__.py          # 包初始化
│       ├── __main__.py          # 模块入口点
│       ├── main.py              # 主应用程序逻辑
│       ├── config.py            # 配置管理（Pydantic）
│       ├── client.py            # HTTP 客户端（带重试与请求节流）
│       ├── crypto.py            # 签名算法实现
│       ├── state.py             # 运行期状态持久化（失败退避，原子写+跨进程锁）
│       ├── timeutil.py          # 业务时区工具（固定 UTC+8）
│       ├── graceful_shutdown.py # 优雅关闭处理器
│       ├── logging_config.py    # 日志配置
│       └── services/
│           ├── __init__.py
│           ├── task_service.py  # 任务管理（含 signState 跳过已签）
│           ├── sign_service.py  # 签到提交
│           ├── upload_service.py # 图片上传
│           └── notification_service.py  # 微信推送通知
├── tests/                       # 测试套件
├── config.json.example          # 配置文件模板
├── state.json                   # 运行期状态（失败退避，已 gitignore）
├── pyproject.toml               # 项目元数据和依赖
└── README.md                    # 本文档
```

### 🤝 参与贡献

欢迎提交 Issue 和 Pull Request！如果你发现了接口变更或开发了新增功能，非常欢迎一起完善本项目。

1. Fork 本仓库
2. 创建你的特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交你的更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启一个 Pull Request

### 📄 开源协议 (License)

本项目采用 **MIT License** 开源协议。

---

***If you find this project helpful, please give it a ⭐️!***
