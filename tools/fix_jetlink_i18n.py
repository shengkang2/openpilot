#!/usr/bin/env python3
"""Jetlink 面板汉化补丁（幂等，可重复执行）。

思路分两层：
  A. list_view.py —— 设置列表的通用组件。ListItem.title / description、
     ButtonAction.text、TextAction.text、MultipleButtonAction 的按钮文字，
     统一在取值处包 tr()。这一层改完，整机所有设置项（不只 Jetlink）的
     静态标签都能翻译，且调用方不必逐个包 tr。
  B. jetlink.py / jetlink_ui.py —— 动态拼接的句子（f-string），必须显式
     tr("模板 {}").format(值)，否则永远输出英文。

用法（在 openpilot 源码树根目录）：
  python3 tools/fix_jetlink_i18n.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MARK = '  # __JETLINK_I18N__'

LIST_VIEW = os.path.join(REPO, 'system', 'ui', 'widgets', 'list_view.py')
JETLINK = os.path.join(REPO, 'bluepilot', 'ui', 'layouts', 'jetlink.py')
JETLINK_UI = os.path.join(REPO, 'bluepilot', 'ui', 'jetlink_ui.py')


def patch(path, pairs, label):
  src = open(path, encoding='utf-8').read()
  if MARK in src:
    print(f'  {label}: 已打过，跳过')
    return
  missed = []
  for old, new in pairs:
    if old not in src:
      missed.append(old[:60])
      continue
    src = src.replace(old, new, 1)
  if missed:
    print(f'!! {label}: {len(missed)} 处未匹配')
    for m in missed:
      print('   -', m)
    sys.exit(1)
  open(path, 'w', encoding='utf-8').write(src)
  print(f'  {label}: {len(pairs)} 处替换完成')


# ============================================================ A. list_view.py
pairs_list_view = [
  # ListItem.title —— 所有设置项标题
  ('  @property\n  def title(self):\n    return _resolve_value(self._title, "")',
   '  @property\n  def title(self):\n    return tr(_resolve_value(self._title, ""))' + MARK),

  # ListItem.description —— 说明文字（会走 HtmlRenderer，渲染前翻译）
  ('  @property\n  def description(self):\n    return _resolve_value(self._description, "")',
   '  @property\n  def description(self):\n    return tr(_resolve_value(self._description, ""))'),

  # ButtonAction.text / TextAction.text —— "Select" / "Update" 这类按钮与右侧数值
  ('  @property\n  def text(self):\n    return _resolve_value(self._text_source, tr("Error"))',
   '  @property\n  def text(self):\n    return tr(_resolve_value(self._text_source, tr("Error")))'),

  # MultipleButtonAction 的按钮文字
  ('      text = _resolve_value(_text, "")',
   '      text = tr(_resolve_value(_text, ""))'),
]

# ============================================================ B. jetlink.py
pairs_jetlink = [
  # 导入 tr
  ('from openpilot.system.ui.lib.application import gui_app\n',
   'from openpilot.system.ui.lib.application import gui_app\n'
   'from openpilot.system.ui.lib.multilang import tr' + MARK + '\n'),

  # 进度阶段词
  ('    label = PROGRESS_STAGES.get(stage, stage)',
   '    label = tr(PROGRESS_STAGES.get(stage, stage))'),

  # 远端上报状态
  ("""    self._far = {'loaded': name(loaded) or "Not reported",
                 'built': ("Built on the device: " + ", ".join(name(b) for b in built)) if built
                          else "The device has not reported a built model yet (shown once it connects).",""",
   """    self._far = {'loaded': name(loaded) or tr("Not reported"),
                 'built': (tr("Built on the device: ") + ", ".join(name(b) for b in built)) if built
                          else tr("The device has not reported a built model yet (shown once it connects)."),"""),

  # 大模型来源说明（两段长句）
  ('''    if self._far['following']:
      return "Follows the device: the model picked in the phone (or Jetson / Mac) app is the one that drives; the comma downloads nothing."
    slot = ui_state.params.get(jetlink_adapter.KEYS.big_model) or {}
    return (f"Picked on the comma: {slot.get('displayName') or slot.get('ref', '')[:10]}. If the device does not have it, "
            "the comma downloads it while parked and uploads it to be built.")''',
   '''    if self._far['following']:
      return tr("Follows the device: the model picked in the phone (or Jetson / Mac) app is the one that drives; the comma downloads nothing.")
    slot = ui_state.params.get(jetlink_adapter.KEYS.big_model) or {}
    return tr("Picked on the comma: {}. If the device does not have it, the comma downloads it while parked and uploads it to be built.").format(
      slot.get('displayName') or slot.get('ref', '')[:10])'''),

  # 选择大模型对话框
  ('    follow_label = f"Follow the device (now: {jetlink_adapter.model_name(loaded, ui_state.params) or \'unknown\'})"',
   '    follow_label = tr("Follow the device (now: {})").format(jetlink_adapter.model_name(loaded, ui_state.params) or tr("unknown"))'),

  ("""      notes = [n for n, on in (("loaded", row['loaded']), ("built on device", row['built']),
                               ("downloaded on comma", row['downloaded'])) if on]""",
   """      notes = [tr(n) for n, on in (("loaded", row['loaded']), ("built on device", row['built']),
                                   ("downloaded on comma", row['downloaded'])) if on]"""),

  ('    dialog = MultiOptionDialog("Big model", list(self._menu_labels.keys()), current,',
   '    dialog = MultiOptionDialog(tr("Big model"), list(self._menu_labels.keys()), current,'),

  # 刷新模型列表的结果
  ('    self._refresh_result = "Updating..."',
   '    self._refresh_result = tr("Updating...")'),
  ('        self._refresh_result = f"Updated: {n} big model(s)."',
   '        self._refresh_result = tr("Updated: {} big model(s).").format(n)'),
  ('        self._refresh_result = f"Update failed: {e}"',
   '        self._refresh_result = tr("Update failed: {}").format(e)'),

  # 面板描述（顶部长说明）+ 缺 jetlink 提示
  ('    description = f"{DESCRIPTION} {status}".strip()',
   '    description = f"{tr(DESCRIPTION)} {status}".strip()'),
  ('      description += " (jetlink is not in this build)"',
   '      description += tr(" (jetlink is not in this build)")'),
]

# ============================================================ C. jetlink_ui.py
pairs_jetlink_ui = [
  ('from openpilot.system.ui.lib.application import gui_app\n',
   'from openpilot.system.ui.lib.application import gui_app\n'
   'from openpilot.system.ui.lib.multilang import tr' + MARK + '\n'),

  # 连接状态那一行
  ('    return f"Jetlink connected: {jetlink.transport}."',
   '    return tr("Jetlink connected: {}.").format(jetlink.transport)'),
  ('  return "Nothing on the USB-C port." if jetlink.port == "empty" else "A device is on the USB-C port (not answering Jetlink yet)."',
   '  return tr("Nothing on the USB-C port.") if jetlink.port == "empty" else tr("A device is on the USB-C port (not answering Jetlink yet).")'),

  # 进度 + 掉线提示
  ('''    hint = "check the cable or the app" if jetlink.mode == 'ios' else "check the cable"
    msg = f"{msg}, {hint} ({drops} drops)"''',
   '''    hint = tr("check the cable or the app") if jetlink.mode == 'ios' else tr("check the cable")
    msg = tr("{}, {} ({} drops)").format(msg, hint, drops)'''),

  # 状态说明（failover 逻辑）
  ('  big_name = (model_name if model_name and model_name != NONE_TEXT else None) or view.model or "the big model"',
   '  big_name = (model_name if model_name and model_name != NONE_TEXT else None) or view.model or tr("the big model")'),

  ('''    if view.reason:
      return f"Big model unavailable: {view.reason}. The small model drives."
    return "Big model unavailable. The small model drives."
  if state == JetlinkState.WAITING:
    return f"{big_name} is ready. It swaps in as soon as nothing is in control: cancel cruise, then re-engage."
  if state == JetlinkState.LOADING:
    return "The small model drives until the big one is ready."
  if not view.ready:
    if view.standin:
      return f"{view.standin} drives until {big_name} is ready."
    return f"{big_name} will drive once Jetlink is ready."
  return f"{big_name} will drive; a lost link falls back to the small model and returns when it is back."''',
   '''    if view.reason:
      return tr("Big model unavailable: {}. The small model drives.").format(view.reason)
    return tr("Big model unavailable. The small model drives.")
  if state == JetlinkState.WAITING:
    return tr("{} is ready. It swaps in as soon as nothing is in control: cancel cruise, then re-engage.").format(big_name)
  if state == JetlinkState.LOADING:
    return tr("The small model drives until the big one is ready.")
  if not view.ready:
    if view.standin:
      return tr("{} drives until {} is ready.").format(view.standin, big_name)
    return tr("{} will drive once Jetlink is ready.").format(big_name)
  return tr("{} will drive; a lost link falls back to the small model and returns when it is back.").format(big_name)'''),
]

print('=== 1/3 list_view.py（框架层，覆盖所有设置项）===')
patch(LIST_VIEW, pairs_list_view, 'list_view.py')

print('=== 2/3 jetlink.py（动态文案）===')
patch(JETLINK, pairs_jetlink, 'jetlink.py')

print('=== 3/3 jetlink_ui.py（状态与说明）===')
patch(JETLINK_UI, pairs_jetlink_ui, 'jetlink_ui.py')

print('完成')
