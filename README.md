# Quick Translator · 本地即时翻译器

在任意软件中选中英文，按下全局快捷键，即可在屏幕右上角看到中文翻译。

## 功能

- 全局快捷键触发（默认 `Ctrl+Shift+T`，可在配置中修改）
- 自动复制选中文本 → 调用智谱 GLM 翻译 → 右上角弹出结果
- 弹窗 6 秒自动关闭，也可按 `ESC` 手动关闭
- 翻译后自动恢复原剪贴板内容，不污染用户剪贴板
- **系统托盘常驻**：右下角图标常驻后台，右键可"显示状态 / 退出"
- **日志记录**：关键事件与异常写入 `translator.log`，便于排查

今天十月的秋天，早上阴转晴

## 项目结构

```
main.py              # 主程序入口（配置加载、热键注册、线程调度、退出清理）
translator.py        # 调用智谱 API 翻译
clipboard_util.py    # 剪贴板读取、保存、恢复（含模拟 Ctrl+C）
popup.py             # 无边框置顶弹窗
applog.py            # 日志配置与全局异常钩子
tray.py              # 系统托盘图标（pystray）
config.example.yaml  # 配置模板（提交到 Git）
config.yaml          # 真实配置（含 API Key，不提交）
requirements.txt     # 依赖清单
start.bat            # 一键静默启动脚本（pythonw，无控制台）
.gitignore           # 忽略 config.yaml、venv/、__pycache__、*.log 等
README.md            # 项目说明
icon.png             # 托盘图标（可选，缺失时用程序化兜底图标）
translator.log       # 运行日志（自动生成，已被 .gitignore 忽略）
venv/                # 虚拟环境（不提交）
```

## 后台常驻运行

### 一键启动（推荐）

双击 `start.bat` 即可。它会用 `venv\Scripts\pythonw.exe` 启动，**不显示黑色控制台窗口**。

也可以在命令行手动启动：

```powershell
venv\Scripts\pythonw.exe main.py
```

### 桌面快捷方式

右键桌面 → 新建 → 快捷方式，按下表填写：

| 字段 | 内容 |
|------|------|
| 目标 | `"D:\Trae object\quick-translator\venv\Scripts\pythonw.exe" "D:\Trae object\quick-translator\main.py"` |
| 起始位置 | `D:\Trae object\quick-translator` |
| 图标 | 需 `.ico` 格式（Windows 快捷方式不支持直接用 `.png`）；也可留默认图标 |

### 托盘图标

- **显示状态**：弹出信息框，展示当前热键、翻译成功/失败次数、最近一次结果与日志路径；
- **退出**：干净退出程序（移除所有热键钩子、关闭弹窗、停止托盘、结束进程）。

### 退出方式

- 右键托盘图标 → **退出**（推荐，常驻场景）；
- 或在启动它的终端里按 `Ctrl+C`（仅用 `python.exe` 启动时可用）。

两种方式走的是同一套清理逻辑。

## 日志与排错

- 日志文件：项目根目录的 `translator.log`，每条记录带时间戳；
- 自动轮转：单文件超过 1MB 后自动切分，保留 3 个备份（`translator.log.1` ~ `translator.log.3`）；
- **无控制台时的排错**：用 `pythonw.exe` 启动时看不到任何输出；若怀疑启动失败，改用 `python.exe` 启动即可看到完整报错：

  ```powershell
  venv\Scripts\python.exe main.py
  ```

  常见判断：若 `translator.log` 完全没有生成，通常说明程序在 `import` 阶段就出错了（例如依赖未安装），用上面这条命令就能看到原因。

## 已知限制

- **图片/文件剪贴板无法还原**：若剪贴板原内容是图片或文件，翻译后无法还原（pyperclip 限制）；纯文本内容不受影响。
- **托盘图标兜底**：托盘图标优先读取项目根目录的 `icon.png`；若该文件不存在或损坏，程序会用 Pillow 现场生成一个纯色圆点作为兜底图标，保证不崩溃。
