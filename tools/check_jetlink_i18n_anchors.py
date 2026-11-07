#!/usr/bin/env python3
"""校验 Jetlink 汉化补丁的所有锚点在当前源码树里是否仍然存在。

用途：固化前先跑一遍，任何锚点失配都说明上游代码变了，补丁需要重新对齐。
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CHECKS = {
    'system/ui/widgets/list_view.py': [
        '  @property\n  def title(self):\n    return _resolve_value(self._title, "")',
        '  @property\n  def description(self):\n    return _resolve_value(self._description, "")',
        '  @property\n  def text(self):\n    return _resolve_value(self._text_source, tr("Error"))',
        '      text = _resolve_value(_text, "")',
    ],
    'bluepilot/ui/layouts/jetlink.py': [
        'from openpilot.system.ui.lib.application import gui_app\n',
        '    label = PROGRESS_STAGES.get(stage, stage)',
        '    self._refresh_result = "Updating..."',
        '        self._refresh_result = f"Updated: {n} big model(s)."',
        '        self._refresh_result = f"Update failed: {e}"',
        '    description = f"{DESCRIPTION} {status}".strip()',
        '      description += " (jetlink is not in this build)"',
        '    dialog = MultiOptionDialog("Big model", list(self._menu_labels.keys()), current,',
    ],
    'bluepilot/ui/jetlink_ui.py': [
        'from openpilot.system.ui.lib.application import gui_app\n',
        '    return f"Jetlink connected: {jetlink.transport}."',
        '  return "Nothing on the USB-C port." if jetlink.port == "empty" else "A device is on the USB-C port (not answering Jetlink yet)."',
        '  big_name = (model_name if model_name and model_name != NONE_TEXT else None) or view.model or "the big model"',
    ],
}

bad = 0
for rel, anchors in CHECKS.items():
    p = os.path.join(REPO, rel)
    if not os.path.isfile(p):
        print(f'!! 文件不存在: {rel}')
        bad += 1
        continue
    src = open(p, encoding='utf-8').read()
    for a in anchors:
        if a not in src:
            print(f'!! {rel}: 锚点失配 -> {a[:70]!r}')
            bad += 1
    print(f'  {rel}: {len(anchors)} 个锚点检查完毕')

print('全部通过' if bad == 0 else f'有 {bad} 处失配')
sys.exit(1 if bad else 0)
