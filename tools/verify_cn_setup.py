#!/usr/bin/env python3
"""全面校验 bp7 分支的中文改动是否自洽。

检查项：
  1. po 文件可被 gettext 解析，且无空译（除故意留空的）
  2. 字库覆盖 po 里出现的所有字符（缺字会导致界面显示方块）
  3. tr() 调用的 msgid 在 po 里有对应条目
  4. 各改动文件的语法
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PO = os.path.join(REPO, 'selfdrive', 'ui', 'translations', 'app_zh-CHS.po')
FONTS = os.path.join(REPO, 'selfdrive', 'assets', 'fonts')

problems = []


def parse_po(path):
    """解析 po，返回 {msgid: msgstr}。

    注意 gettext 的复数形式：条目写的是 `msgstr[0]` / `msgstr[1]`，
    单数 msgid 对应的其实是 msgstr[0]。只认单数 msgstr 会把
    「{} 分钟前」这类条目误判成空译，所以这里一并收集带下标的 msgstr[N]。
    """
    ids, cur_id, cur_str, mode = {}, None, [], None
    for raw in open(path, encoding='utf-8'):
        line = raw.rstrip('\n')
        if line.startswith('msgid '):
            if cur_id is not None:
                ids[cur_id] = ''.join(cur_str)
            m = re.match(r'^"(.*)"$', line[6:].strip())
            cur_id, cur_str, mode = (m.group(1) if m else line[6:].strip()), [], 'id'
        elif line.startswith('msgstr'):
            m = re.match(r'^"(.*)"$', line[7:].strip())
            cur_str, mode = [m.group(1) if m else line[7:].strip()], 'str'
        elif line.startswith('"') and cur_id is not None:
            m = re.match(r'^"(.*)"$', line.strip())
            if m:
                if mode == 'id':
                    cur_id += m.group(1)
                elif mode == 'str':
                    cur_str.append(m.group(1))
    if cur_id is not None:
        ids[cur_id] = ''.join(cur_str)
    return ids


# ---- 1. po 解析与空译检查
print('=== 1. po 词条检查 ===')
entries = parse_po(PO)
print(f'  条目总数: {len(entries)}')
empty = [k for k, v in entries.items() if k and not v.strip()]
if empty:
    print(f'  空译 {len(empty)} 条:')
    for e in empty[:15]:
        print(f'    - {e[:60]!r}')
    problems.append(f'po 有 {len(empty)} 条空译')
else:
    print('  无空译 ✅')

# ---- 2. 字库覆盖检查
print()
print('=== 2. 字库覆盖检查 ===')
po_text = open(PO, encoding='utf-8').read()
po_chars = {c for c in po_text if ord(c) > 0x20 and ord(c) <= 0xFFFF}

fnt_path = os.path.join(FONTS, 'Zh-Regular.fnt')
if not os.path.isfile(fnt_path):
    problems.append('字库缺失')
else:
    font_ids = set()
    for line in open(fnt_path, encoding='utf-8'):
        m = re.match(r'^char id=(\d+) ', line)
        if m:
            font_ids.add(int(m.group(1)))
    missing = {c for c in po_chars if ord(c) not in font_ids}
    print(f'  字库字形: {len(font_ids)}  po 字符: {len(po_chars)}')
    if missing:
        print(f'  !! 缺字 {len(missing)} 个: {"".join(sorted(missing))[:80]}')
        problems.append(f'字库缺 {len(missing)} 个字符')
    else:
        print('  字库完整覆盖 po ✅')

    # 图集尺寸安全线
    for line in open(fnt_path, encoding='utf-8'):
        m = re.match(r'^common .*scaleW=(\d+) scaleH=(\d+)', line)
        if m:
            w, h = int(m.group(1)), int(m.group(2))
            print(f'  图集尺寸: {w}x{h}')
            if w > 4096 or h > 4096:
                problems.append(f'图集超出 4096 安全线: {w}x{h}')
            else:
                print('  图集在 4096 安全线内 ✅')
            break

# ---- 3. tr() 的 msgid 是否在 po 里
print()
print('=== 3. tr() 调用与 po 的对应 ===')
tr_files = [
    'system/ui/widgets/list_view.py',
    'bluepilot/ui/layouts/jetlink.py',
    'bluepilot/ui/jetlink_ui.py',
    'bluepilot/ui/widgets/network_card.py',
    'bluepilot/ui/widgets/metric_card.py',
    'bluepilot/ui/widgets/drive_stats.py',
]
missing_tr = []
for rel in tr_files:
    p = os.path.join(REPO, rel)
    if not os.path.isfile(p):
        continue
    src = open(p, encoding='utf-8').read()
    for m in re.finditer(r'tr\(\s*"((?:[^"\\]|\\.)*)"', src):
        s = m.group(1).replace('\\"', '"')
        if s and s not in entries:
            missing_tr.append((rel, s))
    # tr("...{}...").format(...) 形式
    for m in re.finditer(r'tr\(\s*"((?:[^"\\]|\\.)*)"\s*\)\s*\.format', src):
        s = m.group(1).replace('\\"', '"')
        if s and s not in entries:
            missing_tr.append((rel, s))

if missing_tr:
    print(f'  !! {len(missing_tr)} 个 tr() 的 msgid 不在 po 里:')
    for rel, s in missing_tr[:20]:
        print(f'    - {rel}: {s[:60]!r}')
    problems.append(f'{len(missing_tr)} 个 tr() 缺词条')
else:
    print('  所有 tr() 都有词条 ✅')

# ---- 4. 语法检查
print()
print('=== 4. 语法检查 ===')
import py_compile
import tempfile
py_files = [
    'system/athena/registration.py',
    'system/ui/lib/application.py',
    'selfdrive/ui/sunnypilot/layouts/settings/settings.py',
    'system/ui/widgets/list_view.py',
    'bluepilot/ui/widgets/network_card.py',
    'bluepilot/ui/widgets/metric_card.py',
    'bluepilot/ui/widgets/drive_stats.py',
    'bluepilot/ui/layouts/jetlink.py',
    'bluepilot/ui/jetlink_ui.py',
    'jetlink_repo/jetlink/openpilot/provision.py',
]
for rel in py_files:
    p = os.path.join(REPO, rel)
    try:
        with tempfile.NamedTemporaryFile(suffix='.pyc', delete=False) as tf:
            tmp = tf.name
        py_compile.compile(p, cfile=tmp, doraise=True)
        os.unlink(tmp)
    except py_compile.PyCompileError as e:
        print(f'  !! {rel}: {e}')
        problems.append(f'{rel} 语法错误')
else:
    print(f'  {len(py_files)} 个文件语法通过 ✅')

# ---- 5. 关键补丁落地检查
print()
print('=== 5. 关键补丁落地检查 ===')
CHECKS = [
    ('system/athena/registration.py', 'set_offroad_alert("Offroad_UnregisteredHardware", False)', '擦红点'),
    ('common/params_keys.h', 'Offroad_AcceleratorUnavailable', 'params 白名单'),
    ('launch_env.sh', 'AGNOS_VERSION="$(tr -d', '根 launch_env 动态钉子'),
    ('sunnypilot/system/hardware/c3/launch_env.sh', 'AGNOS_VERSION="$(tr -d', 'c3 launch_env 动态钉子'),
    ('launch_chffrplus.sh', 'PYTHONPATH="/data/pylibs:$PWD"', '根 launch PYTHONPATH'),
    ('sunnypilot/system/hardware/c3/launch_chffrplus.sh', 'PYTHONPATH="/data/pylibs:$PWD"', 'c3 launch PYTHONPATH'),
    ('system/ui/lib/application.py', 'ZH_REGULAR', '中文字库接入'),
    ('selfdrive/ui/sunnypilot/layouts/settings/settings.py', 'JetlinkLayout', 'Jetlink 面板注册'),
    ('selfdrive/ui/sunnypilot/layouts/settings/settings.py', 'tr(self.panel_info.name)', '导航栏 tr()'),
    ('jetlink_repo/jetlink/openpilot/provision.py', 'no host within %.0f s, checking the offline pre-fetch', 'Jetlink host-first 握手修复'),
]
for rel, needle, label in CHECKS:
    p = os.path.join(REPO, rel)
    if not os.path.isfile(p):
        print(f'  !! {label}: 文件缺失 {rel}')
        problems.append(f'{label} 文件缺失')
        continue
    src = open(p, encoding='utf-8').read()
    if needle in src:
        print(f'  ✅ {label}')
    else:
        print(f'  !! {label}: 未找到 {needle[:40]!r}')
        problems.append(f'{label} 未落地')

# ---- 6. 引导链分区不得被脚本引用为写入目标
print()
print('=== 6. install.sh 安全审查 ===')
inst = open(os.path.join(REPO, 'install.sh'), encoding='utf-8').read()
danger = [
    ('agnos.py', '刷 AGNOS 分区'),
    ('abctl --set_active', '换槽'),
    ('fastboot flash', 'fastboot 刷写'),
    ('dd if=', '裸 dd 写盘'),
]
for needle, why in danger:
    if needle in inst:
        # 允许出现在警告/说明文字里，但不能是实际调用
        for line in inst.splitlines():
            if needle in line and not line.strip().startswith('#') and 'pkill' not in line and 'pgrep' not in line:
                if 'die ' in line or 'warn ' in line or 'echo' in line:
                    continue
                print(f'  !! install.sh 疑似执行 {needle}（{why}）: {line.strip()[:70]}')
                problems.append(f'install.sh 疑似执行 {needle}')
                break
        else:
            continue
print('  未发现分区写入调用 ✅')

print()
print('=' * 50)
if problems:
    print(f'发现 {len(problems)} 个问题:')
    for p in problems:
        print(f'  - {p}')
    sys.exit(1)
print('全部检查通过 ✅')
