---
type: dashboard
status: active
cssclasses: [learning-workbench]
---

# Learning, with evidence.

## 学习工作台

**做一个小步骤，留下一条真实观察。**

> [!tip] 第一次使用
> 从 [[02 Projects/getting-started/Overview|体验项目]] 开始，或按 [[00 Dashboard/Workflow|使用指南]] 创建自己的项目。每个项目都有实践、疑问、路线图和活动记录。

`BUTTON[observe,question,session,cards]`

[[00 Dashboard/Workflow|怎么用]] · [[01 Knowledge/知识地图|知识地图]] · [[99 Inbox/Inbox|审核草稿]] · [[03 Daily/Daily|活动日期]] · [[04 Flashcards/示例题库|题库]]

## 项目与实践

![[00 Dashboard/学习工作台.base#项目与实践]]

## 最近学习会话

![[00 Dashboard/学习工作台.base#最近学习会话]]

> [!abstract]- 查看执行档案
> ![[00 Dashboard/学习工作台.base#执行档案]]

## 我的项目入口

<!-- learning:auto:start -->
- [[02 Projects/getting-started/Overview|getting-started]] · [[02 Projects/getting-started/Progress|活动]] · [[02 Projects/getting-started/Roadmap|路线图]]
<!-- learning:auto:end -->

```meta-bind-button
label: 记观察
style: default
id: observe
hidden: true
action:
  type: command
  command: "quickadd:choice:082b41bb-8355-5f0c-ac93-f6a982e4e84d"
```

```meta-bind-button
label: 记疑问
style: default
id: question
hidden: true
action:
  type: command
  command: "quickadd:choice:09e2a939-d095-5062-a5b2-9ecb175b4775"
```

```meta-bind-button
label: 学习会话
style: default
id: session
hidden: true
action:
  type: command
  command: "quickadd:choice:a7b619b4-3fd3-5ba6-83e0-90acf3906c3c"
```

```meta-bind-button
label: 闪卡复习
style: default
id: cards
hidden: true
action:
  type: command
  command: "flashcard-studio:review-flashcards"
```
