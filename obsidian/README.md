# 可选插件工作台

核心是 `vault` 内的 Markdown。工作台使用 Obsidian 内置 Bases、Meta Bind、QuickAdd 和 Flashcard Studio。固定版本与哈希在 `versions.json`；不捆绑插件代码。

1. 用 Obsidian 打开 `vault` 一次，然后关闭应用。
2. 运行 `python3 scripts/obsidian_setup.py install` 下载并校验插件。
3. 运行 `python3 scripts/obsidian_setup.py apply` 合并托管设置与菜单。
4. 重新打开 vault，信任并启用社区插件。首页切到阅读模式。
5. 运行 `python3 scripts/obsidian_setup.py --skip-app-check check --require-content` 检查本地安装。macOS 可省略 `--skip-app-check` 同时检查应用版本。

`--dry-run` 可用于 install / apply。写入前备份存入 vault 的本地 `.obsidian` 目录。已有主题、非托管命令、复习日志与日程数据保留。安装不会设置 REST API。

新增项目时，`learning.py` 会根据 `quickadd.template.json` 更新 `quickadd.choices.json`。再次关闭应用、apply、重启，新增菜单才会加载。项目 ID 是稳定标识，删除或重命名项目要同时检查旧的本地菜单；合并不会自动删除用户命令。

“记观察”先选项目，再选择记录标题。新建实践页里的多个“我的记录”可用选择器定位；个人完成状态仍由本人维护。多行证据用四反引号围栏保存。记录入口写 Markdown，不使用插件内 JavaScript。

Flashcard Studio 为英文 UI，只有四个评分标签配置为中文。运行 Review flashcards from all notes 开始复习；历史与调度在插件的本地目录中。其 NOTES 模式也可能在题库正文写入卡片元数据，分享题库前请检查。

无插件时直接编辑笔记正文；Base 不可用时可以通过首页的项目链接导航。阶段控件仅提供 stage_N 三态，当前通用版不把任意阶段数转换为百分比。

参考：[Bases 语法](https://help.obsidian.md/bases/syntax)、[QuickAdd Capture](https://quickadd.obsidian.guide/docs/Choices/CaptureChoice/)、[Meta Bind](https://www.moritzjung.dev/obsidian-meta-bind-plugin-docs/)。
