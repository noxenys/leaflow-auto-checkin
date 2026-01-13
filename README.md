# Leaflow 自动签到脚本

这是一个用于在 [Leaflow](https://leaflow.net/) 网站上自动执行每日签到的 Python 脚本。

## ✨ 主要功能

- **多账号支持**：通过环境变量轻松管理多个 Leaflow 账号。
- **自动签到**：模拟浏览器操作，自动完成每日签到，赚取奖励。
- **余额查询**：自动获取并显示每个账号的当前余额。
- **Telegram 通知**：通过 Telegram Bot 发送签到结果通知（支持HTML转义，防止特殊字符报错）。
- **GitHub Actions 集成**：支持通过 GitHub Actions 实现每日定时自动签到。
- **防检测机制**：使用新版无头模式（headless=new）和自定义User-Agent，有效绕过网站检测。
- **网络优化**：所有网络请求均设置超时时间，防止无限挂起。
- **错误处理和重试**：增加了更稳健的错误处理和重试机制，确保在网络波动或页面加载缓慢时也能成功签到。

## 🚀 如何使用

### 1. Fork 本仓库

点击本页面右上角的 **Fork** 按钮，将此仓库复制到你自己的 GitHub 账号下。

### 2. 设置 Secrets

在你 Fork 的仓库页面，点击 **Settings** -> **Secrets and variables** -> **Actions**，然后点击 **New repository secret** 添加以下密钥：

| Secret 名称 | 描述 | 格式 |
| :--- | :--- | :--- |
| `LEAFLOW_ACCOUNTS` | **（推荐）** 你的 Leaflow 账号信息（支持多账号） | `邮箱1:密码1,邮箱2:密码2` (多个账号用逗号隔开) |
| `LEAFLOW_EMAIL` | （备选）单个 Leaflow 账号邮箱 | `your_email@example.com` |
| `LEAFLOW_PASSWORD` | （备选）单个 Leaflow 账号密码 | `your_password` |
| `TELEGRAM_BOT_TOKEN` | （可选）你的 Telegram Bot Token | `1234567890:ABC-DEF1234ghIkl-zyx57W2v1u123ew11` |
| `TELEGRAM_CHAT_ID` | （可选）你的 Telegram Chat ID | `123456789` |

**账号配置说明：**
- **推荐使用 `LEAFLOW_ACCOUNTS`**：支持多账号管理，格式为 `邮箱:密码,邮箱:密码`
- **备选方案**：如果只使用单个账号，可以设置 `LEAFLOW_EMAIL` 和 `LEAFLOW_PASSWORD`

**如何获取 Telegram Token 和 Chat ID？**

1.  **创建机器人**：在 Telegram 中搜索 `BotFather`，发送 `/newbot` 命令创建你自己的机器人，你将获得一个 Token。
2.  **获取 Chat ID**：在 Telegram 中搜索 `userinfobot`，启动它，你将看到你的 Chat ID。

### 3. 启用 GitHub Actions

在你 Fork 的仓库页面，点击 **Actions** 选项卡，然后点击 **I understand my workflows, go ahead and enable them** 按钮启用工作流。

### 4. 手动触发一次工作流

1.  在 **Actions** 页面，点击左侧的 **Leaflow Checkin** 工作流。
2.  点击右侧的 **Run workflow** 下拉菜单。
3.  点击绿色的 **Run workflow** 按钮。

工作流将立即执行一次，你可以点击运行记录查看签到结果。之后，工作流将根据预设的时间（每天 UTC 时间 01:15，北京时间 09:15）自动运行，采用错峰策略避免高峰期排队。

## 🔧 Bug 修复说明

### 报错原因

原始脚本在执行过程中，部分账号会出现 `name 'TimeoutException' is not defined` 的错误，导致签到失败。这是因为代码中捕获了 `TimeoutException` 异常，却没有从 Selenium 库中导入它。

### 修复方案

1.  **添加异常导入**：在 `leaflow_checkin.py` 文件中添加了正确的导入语句：

    ```python
    from selenium.common.exceptions import TimeoutException, NoSuchElementException
    ```

2.  **优化代码逻辑**：对代码进行了微调，增加了部分等待时间和更详细的日志输出，提高了脚本的健壮性。

## 🚀 技术特性优化

### 1. 防检测机制升级
- **新版无头模式**：使用 `--headless=new` 参数，有效绕过网站的反爬虫检测
- **自定义 User-Agent**：设置真实浏览器 User-Agent，避免被识别为自动化工具
- **环境自适应**：自动检测 GitHub Actions 环境，使用 webdriver-manager 管理 ChromeDriver

### 2. 通知系统增强
- **HTML 转义处理**：使用 `html.escape()` 对通知内容进行转义，彻底解决 Telegram API 遇到特殊字符报错的问题
- **网络请求优化**：所有 `requests.post` 调用均设置 `timeout=10` 参数，防止请求无限挂起
- **隐私保护**：通知中自动隐藏邮箱敏感信息，保护用户隐私

### 3. 依赖管理优化
- **版本兼容性**：所有依赖版本锁定符从 `==` 改为 `>=`，提高与 GitHub Actions 环境的兼容性
- **自动更新支持**：支持依赖包的自动更新，确保长期稳定运行

### 4. 调度策略优化
- **错峰执行**：Cron 表达式调整为 `15 1 * * *`（UTC 01:15），避开整点高峰期
- **手动触发**：支持通过 GitHub Actions 界面手动触发签到任务

### 5. 登录稳定性增强
- **重试机制**：登录失败时自动重试（最多3次），提高首次账号登录成功率
- **页面加载优化**：显式等待 `<body>` 标签加载完成，避免在白屏阶段开始操作
- **超时延长**：登录等待时间延长至40秒，为Cloudflare防护提供更多响应时间
- **错误恢复**：失败时自动刷新页面并重试，增强应对网络波动的能力

## 📦 项目文件说明

- **`leaflow_checkin.py`**: 主签到脚本，包含完整的自动签到逻辑、多账号管理、Telegram通知等功能。
- **`.github/workflows/checkin.yml`**: GitHub Actions 配置文件，定义了每日自动执行的任务，包含错峰执行策略。
- **`requirements.txt`**: Python 依赖包列表，使用 `>=` 版本约束确保兼容性。
- **`README.md`**: 本说明文档。

## 🔧 技术架构

### 核心组件
- **Selenium WebDriver**: 自动化浏览器操作，模拟真实用户行为
- **WebDriver Manager**: 自动管理 ChromeDriver 版本，确保环境兼容性
- **Requests**: 发送 Telegram 通知，支持超时设置
- **HTML**: 对通知内容进行转义处理，防止特殊字符报错

### 环境适配
- **GitHub Actions**: 自动检测环境，使用 `browser-actions/setup-chrome` 安装 Chrome
- **本地环境**: 支持在本地运行，便于调试和测试
- **多平台兼容**: 支持 Windows、Linux、macOS 系统

## ⚠️ 免责声明

- 本脚本仅用于学习和技术交流，请勿用于非法用途。
- 使用本脚本所造成的任何后果由使用者自行承担。
- 请勿滥用此脚本，以免对 Leaflow 网站造成不必要的负担。

---