# Quick Translator · 本地即时翻译器

在任意软件中选中英文，按下全局快捷键，即可在屏幕右上角看到中文翻译。

## 功能

- 全局快捷键触发（默认 `Ctrl+Shift+T`，可在配置中修改）
- 自动复制选中文本 → 调用智谱 GLM 翻译 → 右上角弹出结果
- 弹窗 6 秒自动关闭，也可按 `ESC` 手动关闭
- 翻译后自动恢复原剪贴板内容，不污染用户剪贴板

## 环境要求

- Windows
- Python 3.13

## 安装

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

## 配置

1. 复制配置模板：

   ```bash
   copy config.example.yaml config.yaml
   ```

2. 编辑 `config.yaml`，填入你的智谱 API Key（`api_key`）。

> `config.yaml` 已在 `.gitignore` 中，不会被提交。

## 运行

```bash
python main.py
```

## 项目结构

```
main.py              # 主程序入口（配置加载、热键注册、线程调度）
translator.py        # 调用智谱 API 翻译
clipboard_util.py    # 剪贴板读取、保存、恢复（含模拟 Ctrl+C）
popup.py             # 无边框置顶弹窗
config.example.yaml  # 配置模板（提交到 Git）
config.yaml          # 真实配置（含 API Key，不提交）
requirements.txt     # 依赖清单
.gitignore           # 忽略 config.yaml、venv/、__pycache__ 等
README.md            # 项目说明
venv/                # 虚拟环境（不提交）
```

## 已知限制

- 若剪贴板原内容是图片或文件，翻译后无法还原（pyperclip 限制）。
- ESC 全局关闭依赖 `keyboard` 的全局键盘钩子，仅在弹窗显示期间临时注册，弹窗消失后立即移除。

## 常见问题

- **快捷键没反应**：确认程序正在运行；某些软件（如以管理员权限运行的窗口）可能无法接收到模拟按键。
- **快捷键与浏览器冲突**：在 `config.yaml` 中把 `hotkey` 改成其他组合，例如 `ctrl+alt+t`。
- **某些软件里复制不到内容（权限问题）**：如果目标软件以**管理员权限**运行（部分 IDE、游戏、系统工具），而本程序是普通权限，Windows 会拦截模拟按键。解决办法是用**管理员身份的终端**重新运行 `python main.py`。
- **慢软件里翻的是"上一次"的内容（调大 COPY_WAIT）**：在 `clipboard_util.py` 顶部把 `COPY_WAIT` 调大（例如 `0.15` → `0.3`）。它控制"按下 Ctrl+C 后等多久才去读剪贴板"，大型 PDF 阅读器等响应较慢的软件需要更长的等待时间。
- **连续按快捷键没有叠加多个弹窗**：这是正常的防抖行为，处理中会打印 `[提示] 正在处理上一次翻译，已忽略本次按键。`
- **怎么退出程序**：在运行 `main.py` 的终端按 `Ctrl+C`。
