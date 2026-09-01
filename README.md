# 东方异变录（TouHou）

《东方异变录》是一款以自然语言对话驱动的 Touhou Project 同人互动游戏。玩家可以在幻想乡自由探索，通过行动与台词影响 NPC、任务、异变、关系、战斗结果和长期世界状态。

当前版本：`v0.13.0`
存档结构：`V8`
运行平台：Windows

## 主要特性

- 自由输入行动与台词，由 AI 生成连续剧情反馈。
- 单一幻想乡世界，包含地点、NPC 日程、世界书、事件和异变内容。
- Vue 3 游戏界面，支持流式对话、角色头像、地图、任务、状态与历史记录。
- NPC 长期记忆与本地语义召回，可结合近期对话和既往事件生成回应。
- 确定性的符卡、疲劳、伤势、灵力、成长、物品和声望结算。
- 关系发展、消息重写、回复评分、剧情分支和存档快照。
- 离屏 NPC 活动与延迟后果，让玩家行动持续影响世界。
- LangGraph Functional API 回合恢复，断线或解析中断时避免重复调用和重复结算。
- V1-V7 旧存档可自动、增量、幂等升级到 V8，并保留未知及自定义字段。
- 面向开发者的本地诊断、上下文预算、模型运行与恢复状态工具。

## 技术架构

| 层级 | 技术 |
| --- | --- |
| 前端 | Vue 3、原生 ES Modules、HTML/CSS |
| API | FastAPI、Pydantic、Uvicorn |
| AI | OpenAI 兼容客户端，默认连接 DeepSeek |
| 回合编排 | LangGraph Functional API、SQLite checkpoint |
| 桌面端 | pywebview、PyInstaller |
| 测试 | unittest、Playwright、内容 Schema 校验 |

回合中的规则、成长、关系、记忆、任务和世界后果先在内存中结算，再由 `TurnOrchestrator` 统一提交。角色 JSON 与任务 JSON 始终是正式游戏状态的唯一事实源；LangGraph checkpoint 仅用于恢复未完成回合。

## 快速开始

### 运行发布版

1. 双击 `touhou.exe` 或 `启动touhou.bat`。
2. 首次启动时，在游戏设置窗口填写自己的 DeepSeek API Key。
3. 创建或加载角色后即可开始游戏。

API Key 由当前 Windows 用户加密保存在本机，不会写入角色存档或反馈导出包。AI 对话需要能够访问所配置的模型服务，其余游戏数据均保存在本地。

### 从源码运行

建议使用项目已验证的 Python 3.13 与 Node.js 22 环境。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-runtime.txt
npm install
npm run vendor:vue
python -m backend.api
```

启动后访问 <http://127.0.0.1:8000>。首次使用仍可直接在前端设置 API Key。

## 本地配置

常用环境变量如下：

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | 空 | 模型服务 API Key |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | OpenAI 兼容接口地址 |
| `DEEPSEEK_MODEL` | `deepseek-v4-flash` | 默认模型 |
| `APP_HOST` | `127.0.0.1` | 本地服务监听地址 |
| `APP_PORT` | `8000` | 本地服务端口 |
| `TOUHOU_DATA_DIR` | 自动选择 | 覆盖运行数据目录 |
| `TOUHOU_PORTABLE` | `0` | 设为 `1` 启用便携模式 |
| `TOUHOU_LANGGRAPH` | `1` | 设为 `0` 回退到直接模型调用路径 |

`.env`、本地加密 Key、运行时数据和存档均已列入 `.gitignore`，不得提交真实凭据。

## 存档位置

- Windows 发布版：`%LOCALAPPDATA%\TouHou`
- 便携模式：程序所在目录
- 源码开发模式：项目根目录下的 `worlds/world_touhou/sessions/`

在 EXE 同目录创建 `portable.flag`，或设置 `TOUHOU_PORTABLE=1`，即可启用便携模式。旧存档首次加载时会自动升级，并在迁移目录中保留原始备份与迁移报告。

## 测试

运行完整检查与测试：

```powershell
npm test
```

提交或发布前的完整质量门禁：

```powershell
python -m pip install -r requirements-dev.txt
npm run quality
npm run test:e2e
```

GitHub Actions 会在 Windows 上重复执行以上检查，并构建、隔离冒烟测试和打包无存档发布候选。

也可以分别执行：

```powershell
npm run check
npm run test:python
npm run test:e2e
python scripts/evaluate-turns.py
python scripts/benchmark-turn-workflow.py
```

测试覆盖 Python/API、JavaScript 语法、内容 Schema 与引用、浏览器主流程、旧存档升级、回合幂等、故障恢复和发布版冒烟验证。

## 构建与打包

安装完整构建依赖后，先生成不含玩家存档的世界资源，再构建 EXE：

```powershell
python -m pip install -r requirements.txt
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/sync-release-worlds.ps1
python -m PyInstaller --noconfirm --clean api_release.spec
```

构建产物位于 `dist/touhou.exe`。发布前可执行隔离冒烟测试：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/smoke-exe.ps1 -ExePath .\dist\touhou.exe
```

验证通过并更新根目录 EXE 后，可生成不含 API Key、存档、日志和 checkpoint 的测试压缩包：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/package-test.ps1
```

默认输出为 `release/touhou-test-package.zip`。
压缩包内含逐文件 `release-manifest.json`，旁边会生成 ZIP 自身的
`touhou-test-package.zip.manifest.json`，可用其中的 SHA-256 校验分发文件。

如已安装可信 Windows 代码签名证书，可在冒烟测试通过后执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/sign-release.ps1 `
  -CertificateThumbprint "你的证书指纹" -ExePath .\dist\touhou.exe
```

签名脚本会再次读取 Authenticode 状态，只有验证为 `Valid` 才成功结束。

## 项目结构

```text
backend/          FastAPI 路由、领域服务、存档迁移与回合编排
js/vue/           Vue 应用、游戏界面、设置和开发者工具
js/ghost/         对话、地点、会话与游戏状态模块
css/              东方同人视觉样式与响应式布局
worlds/           幻想乡内容、地点、NPC、事件和世界书
prompts/          模型提示词与响应契约
avatars/          NPC 头像资源
content_schemas/  游戏内容 JSON Schema
scripts/          校验、评测、构建、打包与冒烟测试脚本
e2e/              Playwright 端到端测试
docs/             架构与迁移说明
```

## 隐私与安全

- 本地服务默认只监听 `127.0.0.1`，并使用本地会话令牌保护 API。
- LangSmith/LangChain 云端追踪默认关闭，不上传提示词、回复或角色状态。
- checkpoint 位于本地 `runtime/`，成功提交后会清除对应回合数据。
- 反馈导出与测试包采用白名单，不包含 API Key、角色存档或本地恢复数据。
- 模型请求仍会发送到玩家配置的模型服务，请遵守对应服务的隐私政策。

## 更新记录

- 完整中文更新记录：[updatelog.md](updatelog.md)
- 版本摘要：[CHANGELOG.md](CHANGELOG.md)
- LangGraph 迁移说明：[docs/langgraph-migration.md](docs/langgraph-migration.md)

## 同人说明

本项目是非官方 Touhou Project 同人作品，与原作官方不存在隶属或背书关系。相关原作名称、角色与设定归其各自权利人所有。

仓库当前未附带通用开源许可证；代码、文案与自制素材的使用及再分发权限以项目维护者的明确授权为准。
