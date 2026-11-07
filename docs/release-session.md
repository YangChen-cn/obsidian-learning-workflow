---
id: "general-learning-workflow-public-extraction"
type: "session"
status: "recorded"
actor: "agent"
date: "2026-11-07"
created: "2026-11-07"
topics: []
---

# 提取并验证通用 Obsidian 学习工作流开源版

- 执行者：AI Agent
- 会话陈述来自记录者；本记录不自动判断本人的知识掌握程度。

## 工作摘要

在独立目录创建 LearnVault 通用工作流，支持任意领域与多个项目、实际执行归档、本人学习会话、知识审核、活动索引和可选插件工作台。重写 README 与 GPL-3.0-only 许可，从空白模板构建，不携带原项目个人记录或 Git 历史。

## 会话中的观察

- 通用工作流需要把项目、领域和本地时区从单一工程中解耦，Agent 执行证据与本人掌握状态继续独立。
- 模板和项目专用模板必须同时从活动索引及 Bases 学习视图排除。
- 当前官方 Release 的插件资产摘要与旧锁定值不同；按官方 SHA-256 核对后更新并实际验证安装。

## 待解问题

- 跨平台 CI 已配置，平台结果需以实际运行结果为准。

## 下一步

- 在公开仓库中维护通用模板，个人学习活动继续保存在自己的 vault。

## 相关领域

未记录

## 验证（记录者提供）

- make check：passed；证据：在独立通用工作流仓库执行：26 项单元测试通过，16 篇 Markdown 校验通过。
- python3 scripts/obsidian\_setup.py install：passed；证据：首次因旧哈希拒绝安装；核对官方 GitHub Release 摘要并更新开源版锁定文件后，三个插件下载校验通过。
- python3 scripts/obsidian\_setup.py --skip-app-check check --require-content：passed；证据：独立 vault 的插件版本、托管设置、工作台内容与 CSS 检查通过。
- Obsidian 原生 UI 与 QuickAdd 实测：passed；证据：四个按钮显示；多行观察和代码围栏写入指定阶段，mastery/stage 保持原值；临时 QA 内容已恢复，运行时无错误。

## 公开导出说明

此文件由本次 Agent 执行档案导出，仅保留开源版构建与验证事实。源工作区的私有基线和自动关联记录未随文件发布。
