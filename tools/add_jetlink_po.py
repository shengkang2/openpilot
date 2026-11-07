#!/usr/bin/env python3
"""补 po / pot 词条（Jetlink 面板 + bluepilot 首页组件）。

规则：
  - po 里已有该 msgid 且译文非空 → 跳过，不覆盖
  - 已有但译文为空 → 填充
  - 没有 → 追加到文件末尾
  - pot 只补 msgid（msgstr 留空）

占位符统一用 {}，与项目现有惯例一致（如 '{} 分钟前'）。

用法（在 openpilot 源码树根目录）：
  python3 tools/add_jetlink_po.py
"""
import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PO = os.path.join(REPO, 'selfdrive', 'ui', 'translations', 'app_zh-CHS.po')
POT = os.path.join(REPO, 'selfdrive', 'ui', 'translations', 'app.pot')

# (msgid, msgstr)
ENTRIES = [
  # ---- jetlink.py 静态标签（走 ListItem / ButtonAction 的 tr）----
  ("Link state", "链路状态"),
  ("Transport", "传输方式"),
  ("Device online", "设备在线"),
  ("USB-C port", "USB-C 接口"),
  ("Will drive", "将使用模型"),
  ("Engine built on the device", "设备上已构建引擎"),
  ("Progress", "进度"),
  ("Unavailable", "不可用"),
  ("Big model", "大模型"),
  ("Select", "选择"),
  ("Device's model", "设备模型"),
  ("Update model list", "更新模型列表"),
  ("Update", "更新"),
  ("Updating...", "更新中..."),
  ("Off (held by Jetlink)", "关闭（被 Jetlink 占用）"),
  ("Nothing", "无"),

  # ---- STATE_TEXT ----
  ("No device", "未连接设备"),
  ("Not built", "未构建"),
  ("Ready", "就绪"),
  ("Loading", "加载中"),
  ("Failed", "失败"),
  ("Re-engage", "重新激活"),

  # ---- PROGRESS_STAGES ----
  ("Connecting", "连接中"),
  ("Downloading", "下载中"),
  ("Uploading", "上传中"),
  ("Building", "构建中"),

  # ---- 面板顶部长说明 ----
  ("Runs the large driving model on a computer attached to the comma's USB-C port "
   "(a Jetson, a Linux PC or a Mac over USB; an iPhone over the cable). It turns ADB off, "
   "and the mode can only change while parked. If the link drops or falls behind, the comma "
   "goes straight back to its own small model.",
   "把大驾驶模型跑在接到 comma USB-C 口的一台电脑上"
   "（Jetson、Linux PC，或通过 USB 连接 Mac；iPhone 用数据线直连）。"
   "开启后会关闭 ADB，且只能在停车时切换模式。"
   "链路断开或跟不上时，comma 会立刻回退到自带的小模型。"),

  # ---- jetlink.py 动态文案 ----
  ("Not reported", "未上报"),
  ("Built on the device: ", "设备上已构建："),
  ("The device has not reported a built model yet (shown once it connects).",
   "设备尚未上报已构建的模型（连接后显示）。"),
  ("Follows the device: the model picked in the phone (or Jetson / Mac) app is the one that drives; the comma downloads nothing.",
   "跟随设备：用手机（或 Jetson / Mac）App 里选的模型来驱动，comma 不下载任何东西。"),
  ("Picked on the comma: {}. If the device does not have it, the comma downloads it while parked and uploads it to be built.",
   "在 comma 上选择：{}。若设备没有该模型，comma 会在停车时下载并上传构建。"),
  ("Follow the device (now: {})", "跟随设备（当前：{}）"),
  ("unknown", "未知"),
  ("loaded", "已加载"),
  ("built on device", "设备已构建"),
  ("downloaded on comma", "comma 已下载"),
  ("Updated: {} big model(s).", "已更新：{} 个大模型。"),
  ("Update failed: {}", "更新失败：{}"),
  (" (jetlink is not in this build)", "（此版本不含 jetlink）"),

  # ---- jetlink_ui.py ----
  ("check the cable", "检查线缆"),
  ("check the cable or the app", "检查线缆或 App"),
  ("{}, {} ({} drops)", "{}，{}（掉线 {} 次）"),
  ("Jetlink connected: {}.", "Jetlink 已连接：{}。"),
  ("Nothing on the USB-C port.", "USB-C 接口上没有设备。"),
  ("A device is on the USB-C port (not answering Jetlink yet).",
   "USB-C 接口上有设备（尚未响应 Jetlink）。"),
  ("the big model", "大模型"),
  ("Big model unavailable: {}. The small model drives.", "大模型不可用：{}。由小模型驱动。"),
  ("Big model unavailable. The small model drives.", "大模型不可用。由小模型驱动。"),
  ("{} is ready. It swaps in as soon as nothing is in control: cancel cruise, then re-engage.",
   "{} 已就绪。只要没有控制接管就会切换：取消定速巡航，然后重新激活。"),
  ("The small model drives until the big one is ready.", "大模型就绪前由小模型驱动。"),
  ("{} drives until {} is ready.", "{} 驱动，直到 {} 就绪。"),
  ("{} will drive once Jetlink is ready.", "Jetlink 就绪后由 {} 驱动。"),
  ("{} will drive; a lost link falls back to the small model and returns when it is back.",
   "由 {} 驱动；链路丢失时回退到小模型，恢复后再切回。"),

  # ---- bluepilot 首页组件（裸英文字符串绕过了 tr()，需显式补词条）----
  ("CPU", "CPU"),                    # 缩写，保留
  ("GPU", "GPU"),
  ("MEMORY", "内存"),
  ("NETWORK", "网络"),
  ("WiFi", "WiFi"),
  ("Ethernet", "以太网"),
  ("Unknown", "未知"),
  ("REGISTERING", "注册中"),
  ("PROGRESS", "进行中"),
  ("ALL TIME", "全部"),
  ("PAST WEEK", "近一周"),
  ("Drives", "行程"),
  ("Hours", "时长"),
  ("KM", "公里"),
  ("Miles", "英里"),
]


def esc(s: str) -> str:
  return s.replace('\\', '\\\\').replace('"', '\\"')


def parse_msgids(path):
  """返回 {msgid: msgstr}。

  gettext 复数形式的条目写的是 `msgstr[0]` / `msgstr[1]`，
  单数 msgid 对应的译文其实是 msgstr[0]。只认单数 msgstr 会把
  「{} 分钟前」这类条目当成空译，从而误判「已存在跳过」。
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


existed = parse_msgids(PO)
added, filled, skipped = [], [], []

po_chunks = []
pot_chunks = []

for msgid, msgstr in ENTRIES:
  if msgid in existed:
    if existed[msgid].strip():
      skipped.append(msgid)
      continue
    # 已有条目但空译：在 po 里就地填充
    src = open(PO, encoding='utf-8').read()
    pat = re.compile(r'(msgid "' + re.escape(esc(msgid)) + r'"\nmsgstr )""\n')
    new_src, n = pat.subn(lambda m: m.group(1) + '"' + esc(msgstr) + '"\n', src, count=1)
    if n:
      open(PO, 'w', encoding='utf-8').write(new_src)
      filled.append(msgid)
    else:
      skipped.append(msgid + ' (空译但格式未匹配)')
    continue

  po_chunks.append('msgid "%s"\nmsgstr "%s"\n' % (esc(msgid), esc(msgstr)))
  pot_chunks.append('msgid "%s"\nmsgstr ""\n' % esc(msgid))
  added.append(msgid)

if po_chunks:
  with open(PO, 'a', encoding='utf-8') as f:
    f.write('\n' + '\n'.join(po_chunks))

if pot_chunks:
  with open(POT, 'a', encoding='utf-8') as f:
    f.write('\n' + '\n'.join(pot_chunks))

print('新增 po 条目 :', len(added))
print('填充空译     :', len(filled))
print('已存在跳过   :', len(skipped))
if skipped:
  print('  跳过清单:', skipped)
print()
print('po 条目总数  :', len(parse_msgids(PO)))
