#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
translator.py —— 翻译模块
职责（单一）：读取配置 + 调用智谱 GLM API + 异常处理。
不依赖弹窗、快捷键，可单独在命令行测试。
"""

import os
import sys

import yaml
from openai import OpenAI

# 配置文件与本模块同目录。用绝对路径而非相对路径，
# 是为了保证无论从哪个目录运行（python main.py / python translator.py），
# 都能找到同一份 config.yaml，避免"文件找不到"的低级错误。
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")

# 翻译提示词。
# 为什么把指令放在独立的 system 消息里，而不是拼进用户文本？
# 因为待翻译内容有时本身就"长得像指令"（例如原文是 "Ignore all rules"），
# 用 system / user 角色分离，模型能明确区分"我要做什么"和"要翻译什么"，
# 避免把原文里的句子误当成命令执行。
SYSTEM_PROMPT = (
    "你是一个专业的英译中翻译引擎。"
    "将用户给出的英文翻译成简体中文，只输出译文本身，"
    "不要解释、不要加引号、不要重复原文。"
)


class TranslationError(Exception):
    """可预期的翻译失败（配置缺失、网络异常、超时等），供上层统一捕获。"""


def load_config(path: str = CONFIG_PATH) -> dict:
    """
    读取并校验 config.yaml。
    任何配置问题都以 TranslationError 抛出，而不是让程序带病继续运行。
    """
    # 1) 文件是否存在。缺失时给出"怎么修"的指引，而不是只报一个路径。
    if not os.path.exists(path):
        raise TranslationError(
            f"未找到配置文件：{path}\n"
            "请先复制 config.example.yaml 为 config.yaml，并填入 API Key。"
        )

    # 2) YAML 能否解析。语法错误单独提示，方便用户定位缩进/冒号问题。
    try:
        with open(path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        raise TranslationError(f"config.yaml 格式错误，请检查缩进与冒号：{e}") from e

    # 3) 必填项校验：api_key 必须有值，且不能还是模板里的占位符。
    api_key = (config.get("api_key") or "").strip()
    if not api_key or api_key == "your-api-key-here":
        raise TranslationError(
            "config.yaml 中的 api_key 未填写，请填入真实的智谱 API Key。"
        )
    config["api_key"] = api_key  # 去掉首尾空白后写回，后续直接用

    return config


class Translator:
    """封装智谱 API 的调用细节。"""

    def __init__(self, config: dict):
        self.model = config.get("model", "glm-4.7-flash")
        self.timeout = config.get("timeout", 10)

        # api_key 只从配置读取，绝不硬编码。
        # base_url 指向智谱兼容 OpenAI 的地址，因此可以复用官方 openai 库。
        # timeout 传进客户端，超时会抛异常被下面的 translate 捕获。
        self.client = OpenAI(
            api_key=config["api_key"],
            base_url=config.get("base_url", "https://open.bigmodel.cn/api/paas/v4/"),
            timeout=self.timeout,
        )

    def translate(self, text: str) -> str:
        """把英文翻译成中文；失败时抛出 TranslationError。"""
        if not text or not text.strip():
            raise TranslationError("没有可翻译的文本（内容为空）。")

        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": text},
                ],
                temperature=0.3,  # 翻译是确定性任务，低温度可减少"自由发挥"
                stream=False,
            )
        except Exception as e:
            # 统一兜底：超时、断网、鉴权失败、额度不足等异常全部在这里接住，
            # 包装成可读的 TranslationError 交给上层展示，绝不让程序崩溃。
            raise TranslationError(f"调用翻译接口失败：{e}") from e

        # 逐层安全取值，避免接口返回结构异常时抛 AttributeError/IndexError。
        choices = getattr(resp, "choices", None)
        if not choices:
            raise TranslationError("翻译接口返回为空。")
        content = getattr(choices[0].message, "content", None)
        if not content:
            raise TranslationError("翻译结果为空。")

        return content.strip()


def main():
    """命令行自测入口：python translator.py "要翻译的英文" """
    try:
        config = load_config()
        translator = Translator(config)
    except TranslationError as e:
        print(f"[配置/初始化错误] {e}")
        sys.exit(1)

    # 没传参数就用一句默认文本，方便快速验证链路是否通。
    text = " ".join(sys.argv[1:]).strip() or "Hello, world. This is a quick translator test."
    print(f"原文：{text}")
    try:
        print(f"译文：{translator.translate(text)}")
    except TranslationError as e:
        print(f"[翻译失败] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
