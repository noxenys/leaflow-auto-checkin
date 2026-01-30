# Leaflow 自动签到脚本

这是一个用于在 [Leaflow](https://leaflow.net/) 网站上自动执行每日签到的 Python 脚本。支持 GitHub Actions 自动运行和本地运行。

## ✨ 主要功能

- **多账号支持**：通过环境变量轻松管理多个 Leaflow 账号。
- **自动签到**：模拟浏览器操作，自动完成每日签到，赚取奖励。
- **余额查询**：自动获取并显示每个账号的当前余额。
- **Telegram 通知**：通过 Telegram Bot 发送签到结果通知。
- **GitHub Actions 集成**：支持通过 GitHub Actions 实现每日定时自动签到。
- **防检测机制**：使用新版无头模式和自定义 User-Agent，有效绕过网站检测。
- **稳健运行**：内置重试机制、超时处理和错误恢复，确保签到成功率。

## 🚀 快速开始 (GitHub Actions)

最简单的方式是使用 GitHub Actions 进行每日自动签到，无需本地环境。

### 1. Fork 本仓库

点击本页面右上角的 **Fork** 按钮，将此仓库复制到你自己的 GitHub 账号下。

### 2. 设置 Secrets

在你 Fork 的仓库页面，点击 **Settings** -> **Secrets and variables** -> **Actions**，然后点击 **New repository secret** 添加以下密钥：

| Secret 名称 | 描述 | 格式 |
| :--- | :--- | :--- |
| `LEAFLOW_ACCOUNTS` | **（推荐）** 你的 Leaflow 账号信息（支持多账号） | `邮箱1:密码1,邮箱2:密码2` (多个账号用逗号隔开) |
| `LEAFLOW_EMAIL` | （备选）单个 Leaflow 账号邮箱 | `your_email@example.com` |
| `LEAFLOW_PASSWORD` | （备选）单个 Leaflow 账号密码 | `your_password` |
| `TELEGRAM_BOT_TOKEN` | （可选）你的 Telegram Bot Token | 详情见下文 |
| `TELEGRAM_CHAT_ID` | （可选）你的 Telegram Chat ID | 详情见下文 |

**Telegram 通知配置说明：**
1.  **创建机器人**：在 Telegram 中搜索 `@BotFather`，发送 `/newbot` 命令创建机器人，获取 Token。
2.  **获取 Chat ID**：在 Telegram 中搜索 `@userinfobot`，获取你的 ID。

### 3. 启用 GitHub Actions

在你 Fork 的仓库页面，点击 **Actions** 选项卡，然后点击 **I understand my workflows, go ahead and enable them** 启用工作流。

### 4. 运行测试

1.  在 **Actions** 页面，点击左侧的 **Leaflow Auto Checkin** 工作流。
2.  点击右侧的 **Run workflow** 下拉菜单，点击绿色的 **Run workflow** 按钮。
3.  等待运行完成，查看日志确认是否签到成功。

此后，脚本将在每天 UTC 时间 01:15（北京时间 09:15）自动运行。

## � 本地运行指南

如果你想在本地计算机上运行或调试脚本：

### 前置要求
- Python 3.8+
- Chrome 浏览器

### 步骤

1.  **克隆仓库**
    ```bash
    git clone https://github.com/your-username/leaflow-auto-checkin.git
    cd leaflow-auto-checkin
    ```

2.  **安装依赖**
    ```bash
    pip install -r requirements.txt
    ```

3.  **设置环境变量并运行**

    **Windows (PowerShell):**
    ```powershell
    $env:LEAFLOW_ACCOUNTS="email@example.com:password"
    python leaflow_checkin.py
    ```

    **Linux / macOS:**
    ```bash
    export LEAFLOW_ACCOUNTS="email@example.com:password"
    python leaflow_checkin.py
    ```

## 🔧 技术架构

- **核心**：基于 Selenium WebDriver 模拟真实用户行为。
- **环境适配**：
  - 自动识别 GitHub Actions 环境，使用 `headless=new` 模式。
  - 本地运行时可见浏览器窗口，方便调试。
  - 使用 `webdriver-manager` 自动管理 ChromeDriver 版本。
- **稳定性**：
  - 显式等待（Explicit Waits）确保元素加载。
  - 智能重试机制处理网络波动。
  - 详细的日志输出。

## ⚠️ 免责声明

- 本脚本仅用于学习和技术交流，请勿用于非法用途。
- 使用本脚本所造成的任何后果由使用者自行承担。
- 请勿滥用此脚本，以免对目标网站造成不必要的负担。
