#!/usr/bin/env python3
"""校验本次改动涉及的 Python 文件语法（compile 级别，不导入依赖）。"""
import os
import py_compile
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FILES = [
    'system/athena/registration.py',
    'system/ui/lib/application.py',
    'selfdrive/ui/sunnypilot/layouts/settings/settings.py',
    'system/ui/widgets/list_view.py',
    'bluepilot/ui/widgets/network_card.py',
    'bluepilot/ui/widgets/metric_card.py',
    'bluepilot/ui/widgets/drive_stats.py',
    'bluepilot/ui/layouts/jetlink.py',
    'bluepilot/ui/jetlink_ui.py',
    'tools/fix_jetlink_i18n.py',
    'tools/add_jetlink_po.py',
    'tools/gen_cn_font.py',
]

bad = 0
for rel in FILES:
    p = os.path.join(REPO, rel)
    if not os.path.isfile(p):
        print(f'!! 缺失: {rel}')
        bad += 1
        continue
    try:
        with tempfile.NamedTemporaryFile(suffix='.pyc', delete=False) as tf:
            tmp = tf.name
        py_compile.compile(p, cfile=tmp, doraise=True)
        os.unlink(tmp)
        print(f'  OK  {rel}')
    except py_compile.PyCompileError as e:
        print(f'!! 语法错误 {rel}:\n{e}')
        bad += 1

print()
print('全部通过' if bad == 0 else f'{bad} 个文件有问题')
sys.exit(1 if bad else 0)
