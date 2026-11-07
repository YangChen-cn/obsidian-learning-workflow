#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Archive explicit activity evidence and maintain a subject-independent learning vault.

This program never runs a reported test, calls an AI service, or infers mastery.
Run ``python3 scripts/learning.py --help`` for commands.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import date, datetime
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
MASTERY = {"unassessed": "待自评", "learning": "学习中", "practiced": "已练习", "explained": "能解释", "applied": "能应用"}
ACTORS = {"agent": "AI Agent", "human": "本人", "pair": "人机协作", "unknown": "未确认"}
STATUSES = {"active", "planned", "proposed", "template", "draft", "recorded", "reviewed", "accepted", "done", "archived", "in-progress"}
START = "<!-- learning:auto:start -->"
END = "<!-- learning:auto:end -->"


class LearningError(Exception):
    pass


def inside(base: Path, relative: str | Path) -> Path:
    """Reject absolute paths, traversal, and symlinks in vault-controlled paths."""
    raw = str(relative)
    p = Path(raw)
    if not raw or "\\" in raw or p.is_absolute() or any(x in ("..", ".") for x in p.parts):
        raise LearningError(f"不允许的库内路径：{raw}")
    current = base
    for part in p.parts:
        current = current / part
        if current.is_symlink():
            raise LearningError(f"路径不能包含符号链接：{raw}")
    if not current.resolve().is_relative_to(base.resolve()):
        raise LearningError(f"路径超出笔记库：{raw}")
    return current


def scan_visible_files(vault: Path):
    """Exclude hidden configuration (especially API credentials) and symlinks."""
    for dirname, dirs, files in os.walk(vault, followlinks=False):
        d = Path(dirname)
        dirs[:] = sorted(x for x in dirs if not x.startswith(".") and not (d / x).is_symlink())
        for name in sorted(files):
            p = d / name
            if not name.startswith(".") and not p.is_symlink() and p.resolve().is_relative_to(vault):
                yield p


def scan_notes(vault: Path):
    yield from (p for p in scan_visible_files(vault) if p.suffix.lower() == ".md")


def scalar(value: str):
    value = value.strip()
    if value.startswith('"'):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            raise LearningError("YAML 双引号内容无效") from None
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'")
    if value.startswith("[") and value.endswith("]"):
        try:
            return json.loads(value)
        except ValueError:
            return [scalar(x) for x in value[1:-1].split(",") if x.strip()]
    return re.sub(r"\s+#.*$", "", value).strip()


def frontmatter(text: str):
    """Read the simple YAML scalars and scalar lists used by these notes.

    Nested YAML is ignored; the original text is always preserved on review.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        return None
    result = {}
    active = None
    for line in lines[1:end]:
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*):(?:\s*(.*))?$", line)
        if match:
            key, value = match.group(1), match.group(2) or ""
            if key in result:
                raise LearningError(f"YAML 重复字段：{key}")
            result[key] = scalar(value) if value.strip() else []
            active = key
        elif active and isinstance(result[active], list):
            item = re.match(r"^\s+-\s+(.*)$", line)
            if item:
                result[active].append(scalar(item.group(1)))
    return result


def get_records(vault: Path):
    records = []
    for path in scan_notes(vault):
        relative = path.relative_to(vault)
        if relative.parts[:2] == ("00 Dashboard", "Templates") or path.name == "Learning Template.md":
            continue
        text = path.read_text(encoding="utf-8")
        meta = frontmatter(text)
        if meta is not None:
            records.append((path, meta, text))
    return records


def q(value):
    # JSON scalars are valid YAML and keep special characters on one line.
    return json.dumps(value, ensure_ascii=False)


def line(value: str) -> str:
    """Escape untrusted commit/session text so it cannot create wiki links."""
    text = " ".join(str(value).split())
    return re.sub(r"([\\`*_{}\[\]<>#|])", r"\\\1", text)


def wiki(vault: Path, path: Path, label: str | None = None, *, alias: bool = True) -> str:
    target = path.relative_to(vault).with_suffix("").as_posix()
    if any(c in target for c in "[]|#\n\r"):
        return line(label or path.stem)
    # Unescaped alias pipes split Markdown table cells; alias-free links work in both views.
    return f"[[{target}|{line(label or path.stem)}]]" if alias else f"[[{target}]]"


def heading(text: str, fallback: str) -> str:
    found = re.search(r"^#\s+(.+)$", text, re.M)
    return found.group(1).strip() if found else fallback


def read_unchanged(path: Path):
    # Preserve CRLF/LF when editing a note owned by the user.
    with path.open("r", encoding="utf-8", newline="") as stream:
        return stream.read()


def write_if_changed(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and read_unchanged(path) == text:
        return False
    # Replace only a generated file's content; a temp file avoids truncated notes.
    fd, temp = tempfile.mkstemp(prefix=".learning-", dir=path.parent)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(fd, path.stat().st_mode & 0o777 if path.exists() else 0o644)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return True


def write_new(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".learning-", dir=path.parent)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o644)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        # A hard link creates the destination exclusively and atomically; an
        # interrupted write never leaves a partially-created record at path.
        os.link(temp, path)
    except FileExistsError:
        raise LearningError(f"目标文件已存在，不会覆盖：{path}") from None
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def update_managed(vault: Path, relative: Path, title: str, kind: str, content: str):
    path = inside(vault, relative)
    block = START + "\n" + content.rstrip() + "\n" + END
    if path.exists():
        original = read_unchanged(path)
        if original.count(START) != original.count(END) or original.count(START) > 1:
            raise LearningError(f"自动区块标记不匹配，未修改：{relative}")
        if START in original:
            start, end = original.index(START), original.index(END)
            if end < start:
                raise LearningError(f"自动区块标记次序错误，未修改：{relative}")
            output = original[:start] + block + original[end + len(END):]
        else:
            output = original.rstrip() + "\n\n" + block + "\n"
    else:
        output = f"---\ntype: {kind}\nstatus: active\n---\n\n# {title}\n\n{block}\n"
    return write_if_changed(path, output)



def load_config(root):
    config = json.loads((root / 'workflow.json').read_text(encoding='utf-8'))
    if config.get('schema') != 1:
        raise LearningError('workflow.json schema 必须是 1')
    inside(root, config['vault'])
    ZoneInfo(config.get('timezone', 'UTC'))
    return config


def vault_for(root):
    return inside(root, load_config(root)['vault'])


def day_for(root):
    return datetime.now(ZoneInfo(load_config(root).get('timezone', 'UTC'))).date().isoformat()


def meta_text(meta, body):
    return '---\n' + ''.join(f'{k}: {q(v)}\n' for k, v in meta.items()) + '---\n\n' + body.rstrip() + '\n'


@contextmanager
def locked(root):
    # A directory lock works on macOS, Linux and Windows without third-party packages.
    local = inside(root, '.learning')
    local.mkdir(exist_ok=True)
    lock = inside(root, '.learning/write.lock')
    try:
        lock.mkdir()
    except FileExistsError:
        raise LearningError('另一写入正在执行；若上次进程已退出，手动移除 .learning/write.lock 后重试') from None
    try:
        yield
    finally:
        lock.rmdir()


def text_field(data, key, required=False):
    value = data.get(key, '')
    if not isinstance(value, str) or len(value) > 16000 or (required and not value.strip()):
        raise LearningError(f'{key} 必须是字符串；必填字段不能为空')
    return value.strip()


def texts(data, key):
    values = data.get(key, [])
    if not isinstance(values, list) or len(values) > 200 or any(not isinstance(x, str) or not x.strip() or len(x) > 4000 for x in values):
        raise LearningError(f'{key} 必须是字符串数组')
    return values


def slug(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}', value):
        raise LearningError('标识使用 1–64 位小写字母、数字、下划线或短横线')
    return value


def project_path(vault, project):
    path = inside(vault, Path('02 Projects') / slug(project))
    if not (path / 'Overview.md').is_file():
        raise LearningError(f'项目不存在：{project}，先运行 project 命令')
    return path


def bullets(values):
    return '\n'.join('- ' + line(x) for x in values) if values else '- 暂无'


def project_create(root, project, title):
    vault = vault_for(root)
    base = inside(vault, Path('02 Projects') / slug(project))
    title = title.strip()
    if not title or '\n' in title or len(title) > 120:
        raise LearningError('项目名称不能为空、换行或超过 120 字符')
    if base.exists():
        raise LearningError('项目目录已存在，保留现有内容')
    base.mkdir(parents=True)
    prefix = f'02 Projects/{project}'
    def note(name, kind, body, **extra):
        write_new(base / name, meta_text({'type': kind, 'project': project, 'status': 'planned', **extra}, body))
    note('Overview.md', 'project', f'# {line(title)}\n\n## 目标\n\n填写想解决的问题和可验证的结果。\n\n'
         f'[[{prefix}/Practice|分阶段实践]] · [[{prefix}/Questions|疑问]] · [[{prefix}/Roadmap|路线图]] · [[{prefix}/Progress|执行档案]]')
    note('Roadmap.md', 'roadmap', '# 路线图\n\n- [ ] 选一个小问题\n- [ ] 做一次验证\n- [ ] 用自己的话解释结果\n\n根据实际需要调整，不从 Agent 工作推断个人完成度。')
    note('Questions.md', 'questions', '# 学习疑问\n\n## 待解决\n\n## 已澄清')
    body = '# 分阶段实践\n\n## 学习控制台\n\n'
    for n, label in enumerate(['提出问题', '动手验证', '解释与迁移'], 1):
        body += f'阶段 {n}：`INPUT[inlineSelect(option(planned, 待开始), option(in-progress, 进行中), option(done, 已完成)):stage_{n}]` → [[#阶段 {n}：{label}]]\n\n'
    body += '> 阶段由本人更新；实践可以是代码实验、阅读对照、解题、口语录音或资料分析。\n\n'
    for n, label in enumerate(['提出问题', '动手验证', '解释与迁移'], 1):
        body += f'## 阶段 {n}：{label}\n\n### 目的\n\n填写这一阶段要回答的具体问题。\n\n### 操作\n\n填写命令、阅读范围或可重复的步骤。\n\n### 预期与原理\n\n写出预期和依据。预期与实际观察分别保留。\n\n### 我的记录\n\n- 关键证据：\n- 我的解释：\n- 还不确定（可选）：\n\n'
    note('Practice.md', 'experiment', body, stage_1='planned', stage_2='planned', stage_3='planned', mastery='unassessed', cssclasses=['learning-practice'])
    (base / 'Sessions').mkdir()
    (base / 'Learning').mkdir()
    refresh(root)
    print(f'已创建项目：{prefix}')


def record(root, source):
    data = json.loads(source.read_text(encoding='utf-8'))
    identity = slug(text_field(data, 'id', True))
    project = slug(text_field(data, 'project', True))
    vault = vault_for(root)
    base = project_path(vault, project)
    actor = data.get('actor', 'agent')
    if actor not in ACTORS:
        raise LearningError('actor 必须是 agent、human、pair 或 unknown')
    title = text_field(data, 'title', True)
    summary = text_field(data, 'summary', True)
    existing = [(p, m) for p, m, _ in get_records(vault) if m.get('type') == 'session' and m.get('project') == project and m.get('id') == identity]
    day = data.get('date', existing[0][1]['date'] if existing else day_for(root))
    if not isinstance(day, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', day):
        raise LearningError('date 必须是 YYYY-MM-DD')
    date.fromisoformat(day)
    lists = {k: texts(data, k) for k in ['sources', 'topics', 'learned', 'questions', 'next_steps']}
    tests = data.get('tests', [])
    if not isinstance(tests, list):
        raise LearningError('tests 必须是数组')
    test_body = ''
    for item in tests:
        if not isinstance(item, dict) or item.get('result') not in ('passed', 'failed', 'not_run'):
            raise LearningError('检查结果只能是 passed / failed / not_run')
        command = text_field(item, 'command', True)
        evidence = text_field(item, 'evidence', True)
        test_body += f'- **{item["result"]}** · {line(command)}\n  - {line(evidence)}\n'
    meta = {'id': identity, 'type': 'session', 'project': project, 'status': 'recorded', 'actor': actor, 'date': day, 'topics': lists['topics']}
    body = f'# {line(title)}\n\n## 实际工作\n\n{line(summary)}\n\n## 实际检查\n\n{test_body or "- 未提供检查结果；不能视为通过。"}\n\n'
    for key, label in [('sources', '来源'), ('learned', '技术或方法发现（不代表本人已掌握）'), ('questions', '未解问题'), ('next_steps', '下一步')]:
        body += f'## {label}\n\n{bullets(lists[key])}\n\n'
    output = meta_text(meta, body)
    # Stable IDs are unique per project. An unchanged retry is a no-op; changed input is refused.
    matches = [p for p, _ in existing]
    dest = inside(vault, base.relative_to(vault) / 'Sessions' / f'{day}-{identity}.md')
    if matches:
        if len(matches) != 1 or read_unchanged(matches[0]) != output:
            raise LearningError('此 ID 已记录了不同内容，请核对原记录；不会覆盖')
        dest = matches[0]
    else:
        write_new(dest, output)
    refresh(root)
    print(dest.relative_to(root))


def review(root, relative, approve):
    if not approve:
        raise LearningError('仅在本人明确审核后使用 --approve；审核不改变 mastery')
    vault = vault_for(root)
    source = inside(vault, relative)
    if not source.is_relative_to(vault / '99 Inbox') or source.suffix != '.md':
        raise LearningError('只能审核 99 Inbox 中的 Markdown 草稿')
    original = read_unchanged(source)
    meta = frontmatter(original)
    if not meta or meta.get('type') != 'knowledge' or meta.get('status') != 'draft':
        raise LearningError('需要 type: knowledge / status: draft')
    target = inside(vault, meta.get('target', ''))
    if not target.is_relative_to(vault / '01 Knowledge') or target.suffix != '.md':
        raise LearningError('target 必须在 01 Knowledge 下且为 .md')
    approved = re.sub(r'^status:.*$', 'status: reviewed', original, count=1, flags=re.M)
    approved = approved.replace('\n---\n', f'\nreviewed: {q(day_for(root))}\n---\n', 1)
    old = source.relative_to(vault).with_suffix('').as_posix()
    new = target.relative_to(vault).with_suffix('').as_posix()
    # Full vault paths are the canonical link form; no ambiguous basename rewrites.
    updates = []
    for p in scan_notes(vault):
        text = read_unchanged(p)
        changed = re.sub(r'\[\[' + re.escape(old) + r'(\.md)?(?=[|#\]])', '[[' + new, text)
        if text != changed and p != source:
            updates.append((p, text, changed))
    write_new(target, approved)
    for p, before, after in updates:
        if read_unchanged(p) != before:
            raise LearningError('笔记同时被编辑；草稿和归档副本均保留，请核对')
        write_if_changed(p, after)
    if read_unchanged(source) != original:
        raise LearningError('草稿同时被编辑，两个副本均保留，请核对')
    source.unlink()
    refresh(root)
    print(f'已审核：{target.relative_to(vault)}；mastery 保持原值')


def uid(value):
    import uuid
    return str(uuid.uuid5(uuid.NAMESPACE_URL, 'obsidian-learning-workflow/' + value))


def quickadd(root, projects):
    # Build per-project commands from the generic kit. No subject names in code.
    template = json.loads((root / 'obsidian/quickadd.template.json').read_text(encoding='utf-8'))
    observations, questions, sessions = [], [], []
    for project in projects:
        prefix = f'02 Projects/{project}'
        for group, key, name, target, heading in [
            (observations, 'observe', '记观察', f'{prefix}/Practice.md', '### 我的记录'),
            (questions, 'question', '记疑问', f'{prefix}/Questions.md', '## 待解决')]:
            choice = json.loads(json.dumps(template['capture']))
            choice.update(id=uid(project + '/' + key), name=f'{project} · {name}', captureTo=target)
            choice['insertAfter'].update(after=heading, promptHeading=(key == 'observe'))
            if key == 'question':
                choice['format']['format'] = '\n**{{DATE:YYYY-MM-DD}}**\n\n{{VALUE:疑问|type:multiline|label:哪里还没想明白？}}\n\n'
            group.append(choice)
        choice = json.loads(json.dumps(template['session']))
        choice.update(id=uid(project + '/session'), name=f'{project} · 学习会话', templatePath=f'{prefix}/Learning Template.md')
        choice['folder']['folders'] = [f'{prefix}/Learning']
        sessions.append(choice)
    choices = [{'id': uid(key), 'name': name, 'type': 'Multi', 'command': True, 'choices': children}
               for key, name, children in [('observe', '记录实践观察', observations), ('question', '记录学习疑问', questions), ('session', '新增学习会话', sessions)]]
    write_if_changed(inside(root, 'obsidian/quickadd.choices.json'), json.dumps({'choices': choices}, ensure_ascii=False, indent=2) + '\n')


def refresh(root):
    vault = vault_for(root)
    records = get_records(vault)
    projects = sorted(m['project'] for _, m, _ in records if m.get('type') == 'project')
    for project in projects:
        base = project_path(vault, project)
        own = [(p, m, t) for p, m, t in records if m.get('project') == project and m.get('type') in ('session', 'learning-session')]
        entries = '\n'.join('- ' + wiki(vault, p, heading(t, p.stem)) for p, m, t in sorted(own, key=lambda r: str(r[1].get('date', '')), reverse=True)) or '- 暂无活动'
        update_managed(vault, base.relative_to(vault) / 'Progress.md', '项目活动', 'progress', entries)
        template = (vault / '00 Dashboard/Templates/Learning.md').read_text(encoding='utf-8').replace('__PROJECT__', project)
        write_if_changed(inside(vault, base.relative_to(vault) / 'Learning Template.md'), template)
    by_day = {}
    for p, m, t in records:
        if m.get('type') in ('session', 'learning-session') and m.get('date'):
            day = str(m['date'])
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', day):
                continue
            by_day.setdefault(day, []).append('- ' + wiki(vault, p, heading(t, p.stem)))
    for day, entries in by_day.items():
        update_managed(vault, Path('03 Daily') / f'{day}.md', day, 'daily', '\n'.join(entries))
    navigation = '\n'.join(f'- [[02 Projects/{p}/Overview|{p}]] · [[02 Projects/{p}/Progress|活动]] · [[02 Projects/{p}/Roadmap|路线图]]' for p in projects) or '- 先创建一个项目'
    update_managed(vault, Path('00 Dashboard/Home.md'), '学习工作台', 'dashboard', navigation)
    quickadd(root, projects)


def validate(root):
    vault = vault_for(root)
    errors = []
    seen = set()
    visible = list(scan_visible_files(vault))
    paths = {p.relative_to(vault).with_suffix('').as_posix() for p in visible}
    for p, m, text in get_records(vault):
        name = p.relative_to(vault).as_posix()
        if m.get('status') == 'template':
            continue
        if 'mastery' in m and m['mastery'] not in MASTERY:
            errors.append(name + ': unknown mastery')
        if m.get('actor') is not None and m['actor'] not in ACTORS:
            errors.append(name + ': unknown actor')
        for key, value in m.items():
            if re.fullmatch(r'stage_\d+', key) and value not in ('planned', 'in-progress', 'done'):
                errors.append(name + ': invalid stage')
        if m.get('type') in ('session', 'knowledge'):
            identity = (m.get('project', ''), m.get('id'))
            if not m.get('id') or identity in seen:
                errors.append(name + ': missing or duplicate id')
            seen.add(identity)
        for link in re.findall(r'\[\[([^\]]+)\]\]', re.sub(r'(?ms)^```.*?^```\s*$', '', text)):
            target = link.split('|')[0].split('#')[0]
            if not target or '{{' in target:
                continue
            resolved = target[:-3] if target.endswith('.md') else target
            if resolved.endswith('.base'):
                resolved = resolved[:-5]
            if resolved not in paths and not any(x.rsplit('/', 1)[-1] == resolved for x in paths):
                errors.append(name + ': broken link ' + target)
    if errors:
        raise LearningError('\n'.join(errors))
    print(f'Vault OK: {len(list(scan_notes(vault)))} Markdown notes; no mastery inferred')


def main(argv=None):
    parser = argparse.ArgumentParser(description='通用 Obsidian 学习工作流；不调用模型，不推断掌握程度。')
    parser.add_argument('--root', type=Path, default=ROOT, help='工作流目录（含 workflow.json）')
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('project', help='创建任意主题的新项目')
    p.add_argument('id'); p.add_argument('--title', required=True)
    p = sub.add_parser('record', help='从明确提供的 JSON 归档实际活动')
    p.add_argument('file', type=Path)
    p = sub.add_parser('review', help='本人明确审核后归档知识草稿')
    p.add_argument('note'); p.add_argument('--approve', action='store_true')
    sub.add_parser('refresh'); sub.add_parser('validate')
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        with locked(root):
            if args.command == 'project': project_create(root, args.id, args.title)
            elif args.command == 'record': record(root, args.file)
            elif args.command == 'review': review(root, args.note, args.approve)
            elif args.command == 'refresh': refresh(root)
            else: validate(root)
        return 0
    except (LearningError, ValueError, OSError, KeyError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
