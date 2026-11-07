---
type: guide
status: active
---

# 使用指南

[[00 Dashboard/Home|回到首页]]

## 从一个问题开始

创建主题的命令在仓库 README。一个项目可以是一门课程、一本书、一项技能、一个开发项目或一组研究问题。不要先搭建庞大的分类树；先选一个能实际验证的小问题。

打开项目的 Overview 写目标，Roadmap 留下一步；Practice 用三个可改名的阶段组织实践。每阶段写清目的、操作、预期和原理，再把本人实际观察放进“我的记录”。读书可填页码与对照问题，语言可填录音与表达练习，编程可填命令与断点观察。

## 留下轻量记录

每次只记三项：关键证据、一两句自己的解释、可选的疑问。粗略、口语化说明也可以。预期不等于实际，AI 的解释不等于本人解释。

首页“记观察”先选项目，再选择对应的“我的记录”标题。未启用插件时直接写在该标题下。阶段下拉框只改 stage_N；整体 status、个人复选框和 mastery 仍由本人判断。

“记疑问”写到项目 Questions。可以以后补来源与答复。“学习会话”在项目 Learning 目录创建本人主动填写的笔记；由 Agent 执行的工作写 Sessions，两个视图独立。

## 活动结束时归档

实际工作结束，包括失败或卡住的尝试，让 Agent 或自己准备会话 JSON。字段与示例见仓库 `docs/session.example.json`。运行：

```sh
python3 scripts/learning.py record .learning/session.json
python3 scripts/learning.py refresh
python3 scripts/learning.py validate
```

record 按 project 和稳定 id 去重。相同输入重试不新增；相同 ID 的不同内容会拒绝覆盖。date 可显式填写，未填写时采用 workflow.json 的时区。record 不会运行 tests 内的命令，结果必须依据实际发生的检查填写 passed / failed / not_run。阅读等活动可使用空 tests 数组。

有活动才生成 Daily 索引。refresh 只更新 managed markers 内的内容，以及项目菜单与专用模板；普通笔记正文不覆盖。没有每日定时任务，也不自动 Git 提交。

## 知识候选先去 Inbox

从 [[00 Dashboard/Templates/Knowledge|知识模板]] 复制一篇草稿到 [[99 Inbox/Inbox|Inbox]]，填写唯一 ID、topic、target、来源、一个练习和一个具体问题。不要复制没有来源的大段 AI 解释来凑笔记。

target 相对于 vault，例如 `01 Knowledge/统计/抽样误差.md`。本人核对内容、来源与归档位置后，才运行：

```sh
python3 scripts/learning.py review '99 Inbox/抽样误差.md' --approve
```

审核会移动文件，设置 reviewed，并更新指向该草稿完整 vault 路径的 wikilink。现有目标不会覆盖。建议始终使用完整路径 wikilink；简称、普通 Markdown 链接或外部工具内的链接需自行核对。审核不修改 mastery。

## 自评只依据本人证据

| mastery | 含义 |
| --- | --- |
| unassessed | 尚未自评 |
| learning | 本人正在学习 |
| practiced | 本人做过相关练习，并有证据 |
| explained | 本人能用自己的话解释，并留有解释 |
| applied | 本人应用于实际问题，并有证据 |

本人决定何时调整，在正文附上对应解释或实践。Agent 完成任务、测试通过、笔记数量、阶段状态都不能代替这些证据。阶段表也不计算掌握百分比。

## 复习与配置

在 [[04 Flashcards/示例题库|题库]] 查看自测语法，按主题建立自己的题库。Flashcard Studio 为英文界面，四个评分标签配置为中文。复习历史与到期日由插件保存，Bases 不推算到期统计。

Bases 是 Markdown 的视图；模板不进入活动。插件不可用时仍可读写正文。更多插件配置和安装命令见仓库 obsidian/README.md。新增项目后要重新 apply 并重启插件菜单。

使用后的笔记库可能含个人内容。公开自己笔记前，核对正文、附件和 Git 历史；不要提交 .obsidian、.learning、复习历史、API 密钥或原始日志。
