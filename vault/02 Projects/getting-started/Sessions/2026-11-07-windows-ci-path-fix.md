---
id: "windows-ci-path-fix"
type: "session"
project: "getting-started"
status: "recorded"
actor: "agent"
date: "2026-11-07"
topics: []
---

# 修复 Windows 路径导致的 CI 失败

## 实际工作

CI Windows Python 3.13 中 7 个工作流测试失败；内部 Path 使用 Windows 原生反斜杠，被安全路径检查误判为非法输入。将内部 PurePath 规范化为正斜杠，继续拒绝用户传入的反斜杠和路径穿越；测试失败时显示具体错误。

## 实际检查

- **passed** · python3 -m unittest discover -s tests
  - macOS 本机 27 项测试通过，包括 Windows 风格路径和不安全路径回归测试。
- **passed** · python3 scripts/learning.py validate
  - 16 篇 Markdown 校验通过。
- **not_run** · GitHub Actions Windows runner
  - 修复后的提交尚未推送，无法声称远端 CI 已通过。


## 来源

- scripts/learning.py
- tests/test\_workflow.py
- GitHub Actions run 42369226410

## 技术或方法发现（不代表本人已掌握）

- 内部平台原生 Path 与用户提供的路径字符串需要区分处理；不能放宽对路径穿越和不安全字符串的拒绝。

## 未解问题

- 本机为 macOS，修复尚未在 GitHub Windows runner 上运行。

## 下一步

- 提交并推送后检查 Windows 及其余 CI 任务的实际结果。
