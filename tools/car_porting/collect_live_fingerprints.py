#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""采集实车 CAN 指纹，并生成可直接粘贴进 opendbc_repo/opendbc/car/<品牌>/fingerprints.py 的条目。

为什么需要它
------------
这套 BYD 移植包没有真实的 FW_VERSIONS（fingerprints.py 里只有一条占位
`{(Ecu.eps, 0x700, None): [b'DUMMYDATA']}`），所以车型识别 100% 依赖 CAN 指纹（FPv1）。
而 openpilot 的判定规则（opendbc/car/fingerprints.py::is_valid_for_fingerprint）是：

    return (adr in car_fingerprint and car_fingerprint[adr] == len(msg.dat)) or adr >= 0x800

=> 只要实车发了一条报文，它的「地址」不在该车型指纹表里，或者「DLC 对不上」，
   这台车就会被判定为该车型不匹配（被 eliminate 掉），于是报 "car doesn't match
   any fingerprints"。反过来，表里多写了实车没发的条目完全无害。
=> 结论：**补齐缺项时，宁可多写，不可少写，DLC 绝不可错**。

⚠️ 但这只对「淘汰」成立，不能用来「补半成品车型」——见下。
--------------------------------------------------------------------------
把别的车型指纹**整体并集**过来冒充缺失车型，是错的，而且会把原本正常的车型弄坏：
识别成功条件是「淘汰到只剩一个候选」（详见
tools/car_porting/check_fingerprint_ambiguity.py）。并集是超集 => 真实兄弟车型
的报文会同时保留新旧两个候选 => 永远等不到唯一解 => 整车退回 MOCK。

所以补缺失车型的正道只有一条：在真车上抓一次指纹。本脚本就是干这个的。
补齐后务必跑 check_fingerprint_ambiguity.py 确认没有引入并列候选。

三种用法
--------
A) 从车机日志（swaglog）里抠（零依赖，最容易，推荐先试）
   openpilot 在识别车型时会打一条事件：
     cloudlog.event("fingerprinted", car_fingerprint=..., fingerprints=repr(finger), ...)
   其中 finger 就是「实车观测到的 {总线: {地址: DLC}}」。把 /data/log/swaglog.* 拷到本地后：

     python3 tools/car_porting/collect_live_fingerprints.py --swaglog /path/swaglog.1700000000

   支持传目录、通配符、多个文件；会把所有会话里观测到的报文做**并集**（并集最安全）。

B) 直接读 CAN 日志（需要 openpilot 环境，最权威）
     python3 tools/car_porting/collect_live_fingerprints.py --rlog /data/media/0/realdata/00000xxx/qlog.zst

   需要能 import openpilot.tools.lib.logreader（在车机上跑，或把 openpilot 放进
   PYTHONPATH）。它直接遍历 cereal 的 can 消息，统计每个地址的 DLC。

C) 与已有指纹对比，算出「缺什么」（最实用）
     python3 tools/car_porting/collect_live_fingerprints.py --rlog <日志> \\
         --compare opendbc_repo/opendbc/car/byd/fingerprints.py --car BYD_HAN_DMI_22

   会分别列出：缺失地址（必须补）、多余地址（无害，建议保留）、DLC 冲突（必须查清），
   并输出修正后的完整条目。

输出
----
  * 屏上是「可直接粘贴」的 `CAR.XXX: [{...}],` 代码块
  * 同时写入文件：<输出目录>/<CAR>_fingerprint.txt
"""

import argparse
import ast
import glob
import io
import os
import re
import sys

# is_valid_for_fingerprint 会忽略 >= 0x800 的地址（alien/debug 地址），单独统计一下
IGNORE_ADDR_THRESHOLD = 0x800


# --------------------------------------------------------------------------
# 通用工具
# --------------------------------------------------------------------------

def _balanced_dict(text, start):
  """从 text[start]=='{' 开始，返回匹配的完整字典字面量字符串；失败返回 None。"""
  if start >= len(text) or text[start] != '{':
    return None
  depth = 0
  in_str = False
  quote = ''
  i = start
  while i < len(text):
    c = text[i]
    if in_str:
      if c == '\\':
        i += 2
        continue
      if c == quote:
        in_str = False
    else:
      if c in ('"', "'"):
        in_str = True
        quote = c
      elif c == '{':
        depth += 1
      elif c == '}':
        depth -= 1
        if depth == 0:
          return text[start:i + 1]
    i += 1
  return None


def _try_literal(cand):
  """把日志里的字符串还原成 dict；失败返回 None。"""
  for s in (cand, cand.replace('\\"', '"').replace("\\'", "'"), cand.replace('\\"', '"')):
    try:
      v = ast.literal_eval(s)
      if isinstance(v, dict):
        return v
    except Exception:
      pass
  return None


def _as_per_bus(obj):
  """把解析出来的对象规整成 {bus:int -> {addr:int -> dlc:int}}。

  可能是 {0: {85:8}, 1: {}}（多总线），也可能是 {85:8, ...}（单总线，视为 bus 0）。
  """
  if not obj:
    return {}
  keys = list(obj.keys())
  if all(isinstance(k, int) and isinstance(v, dict) for k, v in obj.items()) and keys:
    # 判断是不是「总线 -> 指纹」
    inner_addrs = [a for v in obj.values() for a in v.keys()]
    if not inner_addrs or all(isinstance(a, int) for a in inner_addrs):
      if all(isinstance(a, int) for v in obj.values() for a in v.keys()):
        return {int(k): {int(a): int(d) for a, d in v.items()} for k, v in obj.items()}
  # 退化成单总线
  try:
    return {0: {int(a): int(d) for a, d in obj.items()}}
  except Exception:
    return {}


# --------------------------------------------------------------------------
# 方式 A：从 swaglog 文本里抠
# --------------------------------------------------------------------------

# 匹配这三种写法：
#   fingerprints={...}            （Python 里 cloudlog.event(...) 的源码形式）
#   'fingerprints': '{...}'       （swaglog 把 ctx 存成 Python dict repr 的形式）
#   "fingerprints": "{...}"       （swaglog 存成 JSON 的形式）
_FP_KEY = re.compile(r'fingerprints["\']?\s*[=:]\s*')


def parse_swaglog_text(text, stats):
  """从一段日志文本里找出所有 'fingerprints=<dict>' 并返回 per_bus 并集。"""
  out = {}
  for m in _FP_KEY.finditer(text):
    pos = m.end()
    # 跳过可能的前引号/空白
    while pos < len(text) and text[pos] in ' \t"\'':
      pos += 1
    if pos >= len(text) or text[pos] != '{':
      continue
    cand = _balanced_dict(text, pos)
    if not cand:
      continue
    obj = _try_literal(cand)
    if obj is None:
      stats['解析失败'] += 1
      continue
    per_bus = _as_per_bus(obj)
    if not per_bus:
      continue
    stats['命中字典'] += 1
    for b, d in per_bus.items():
      out.setdefault(int(b), {})
      for a, dlc in d.items():
        if a in out[int(b)] and out[int(b)][a] != dlc:
          stats['跨会话DLC冲突'].append((int(b), a, out[int(b)][a], dlc))
        out[int(b)][a] = dlc
  return out


def collect_from_swaglog(paths):
  files = []
  for p in paths:
    if os.path.isdir(p):
      files += sorted(glob.glob(os.path.join(p, '*')))
    else:
      g = sorted(glob.glob(p))
      files += g if g else [p]

  stats = {'命中字典': 0, '解析失败': 0, '跨会话DLC冲突': []}
  per_bus = {}
  for f in files:
    if os.path.isdir(f):
      continue
    try:
      raw = io.open(f, 'r', encoding='utf-8', errors='ignore').read()
    except Exception as e:
      print('  跳过 %s: %s' % (f, e))
      continue
    got = parse_swaglog_text(raw, stats)
    if got:
      print('  %s: 命中 %d 个地址条目（分布 %s）'
            % (os.path.basename(f), sum(len(v) for v in got.values()),
               ', '.join('bus%d:%d' % (b, len(d)) for b, d in sorted(got.items()) if d)))
    for b, d in got.items():
      per_bus.setdefault(b, {})
      for a, dlc in d.items():
        if a in per_bus[b] and per_bus[b][a] != dlc:
          stats['跨会话DLC冲突'].append((b, a, per_bus[b][a], dlc))
        per_bus[b][a] = dlc
  print('  swaglog 扫描完成：命中 %d 个指纹字典，解析失败 %d 处，跨会话 DLC 冲突 %d 处'
        % (stats['命中字典'], stats['解析失败'], len(stats['跨会话DLC冲突'])))
  for b, a, d1, d2 in stats['跨会话DLC冲突'][:10]:
    print('    !! 冲突 总线%d 地址%d: DLC %d vs %d' % (b, a, d1, d2))
  return per_bus


# --------------------------------------------------------------------------
# 方式 B：直接读 CAN 日志
# --------------------------------------------------------------------------

def collect_from_rlog(paths):
  try:
    from openpilot.tools.lib.logreader import LogReader
  except Exception as e:
    print('无法 import openpilot.tools.lib.logreader：%s' % e)
    print('请在车机上运行，或把 openpilot 目录加入 PYTHONPATH / 用 --swaglog 方式。')
    return None

  per_bus = {}
  n_can = 0
  for p in paths:
    print('  读取 %s ...' % p)
    try:
      lr = LogReader(p)
    except Exception as e:
      print('    打不开：%s' % e)
      continue
    for msg in lr:
      if msg.which() != 'can':
        continue
      for c in msg.can:
        n_can += 1
        bus = int(getattr(c, 'src', 0))
        addr = int(c.address)
        dlc = len(bytes(c.dat))
        per_bus.setdefault(bus, {})
        if addr in per_bus[bus] and per_bus[bus][addr] != dlc:
          print('    !! 同一总线上同一地址 DLC 变化：bus%d addr%d %d -> %d'
                % (bus, addr, per_bus[bus][addr], dlc))
        per_bus[bus][addr] = dlc
  print('  共读取 %d 条 CAN 报文' % n_can)
  return per_bus


# --------------------------------------------------------------------------
# 合并 / 输出
# --------------------------------------------------------------------------

def union_with_conflicts(per_bus):
  """把多总线指纹合并成一个字典。

  返回 (merged, conflicts)。conflicts 是被丢弃的「同地址不同 DLC」。
  若 conflicts 非空，说明不能压成一个字典，调用方应改用「每总线一个字典」。
  """
  merged = {}
  conflicts = []
  for b in sorted(per_bus):
    for a, dlc in per_bus[b].items():
      if a in merged and merged[a] != dlc:
        conflicts.append((a, merged[a], b, dlc))
      else:
        merged[a] = dlc
  return merged, conflicts


def fmt_dict(fp, indent='    ', width=118):
  items = ['%d: %d' % (a, d) for a, d in sorted(fp.items())]
  out, line = [], indent
  for it in items:
    if len(line) + len(it) + 2 > width:
      out.append(line.rstrip())
      line = indent
    line += it + ', '
  out.append(line.rstrip().rstrip(','))
  return '\n'.join(out)


def fmt_entry(car, dicts, note=None):
  """生成可直接粘贴的条目文本。dicts 为「每个总线一个字典」的列表。"""
  head = ''
  if note:
    head = '  # %s\n' % note
  parts = []
  for d in dicts:
    parts.append('{\n%s\n  }' % fmt_dict(d))
  return '%s  CAR.%s: [%s],\n' % (head, car, ', '.join(parts))


# --------------------------------------------------------------------------
# 与已有指纹对比
# --------------------------------------------------------------------------

def load_existing(path, car):
  s = io.open(path, encoding='utf-8', errors='ignore').read()
  m = re.search(r'CAR\.' + re.escape(car) + r':\s*\[\{(.*?)\}\]', s, re.S)
  if not m:
    return None
  return {int(a): int(d) for a, d in re.findall(r'(\d+):\s*(\d+)', m.group(1))}


def compare(existing, observed):
  have = set(existing)
  obs = set(observed)
  missing = sorted(obs - have)                      # 实车发了、表里没有 -> 必须补
  extra = sorted(have - obs)                        # 表里有、这次没抓到 -> 无害
  dlc_conflict = sorted(a for a in (have & obs) if existing[a] != observed[a])
  return missing, extra, dlc_conflict


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def main():
  ap = argparse.ArgumentParser(
    description='采集实车 CAN 指纹并生成 opendbc_repo/opendbc/car/<品牌>/fingerprints.py 条目',
    formatter_class=argparse.RawDescriptionHelpFormatter)
  ap.add_argument('--swaglog', nargs='+', help='车机日志（swaglog 文件/目录/通配符，可多个）')
  ap.add_argument('--rlog', nargs='+', help='CAN 日志（qlog/rlog，可多个，需要 openpilot 环境）')
  ap.add_argument('--compare', help='已有的 fingerprints.py，用来算出「缺了哪些地址」')
  ap.add_argument('--car', help='车型枚举名，例如 BYD_HAN_DMI_22（--compare 时需要）')
  ap.add_argument('--outdir', default='.', help='输出目录，默认当前目录')
  ap.add_argument('--bus', type=int, default=None, help='只采用某一条总线（默认合并全部）')
  a = ap.parse_args()

  if not a.swaglog and not a.rlog:
    ap.print_help()
    return 1

  per_bus = None
  if a.swaglog:
    print('[1] 从 swaglog 提取')
    per_bus = collect_from_swaglog(a.swaglog)
  if a.rlog:
    print('[1] 从 CAN 日志提取')
    got = collect_from_rlog(a.rlog)
    if got is not None:
      if per_bus:
        for b, d in got.items():
          per_bus.setdefault(b, {})
          per_bus[b].update(d)
      else:
        per_bus = got

  if not per_bus:
    print('\n没有采集到任何指纹。常见原因：')
    print('  * swaglog 里没有 "fingerprinted" 事件（车机没识别过车型）')
    print('  * 传的是别的日志文件')
    return 2

  if a.bus is not None:
    per_bus = {a.bus: per_bus.get(a.bus, {})} if a.bus in per_bus else {}
    if not per_bus:
      print('指定的总线 %d 上没有任何报文' % a.bus)
      return 2

  print('\n[2] 分总线统计')
  for b in sorted(per_bus):
    d = per_bus[b]
    if not d:
      continue
    lo, hi = min(d), max(d)
    big = sum(1 for x in d if x >= IGNORE_ADDR_THRESHOLD)
    print('  bus %-3d : %4d 个地址（%d~%d），其中 %d 个 >= 0x800 会被 openpilot 忽略'
          % (b, len(d), lo, hi, big))

  # 去掉空总线，避免噪声
  per_bus = {b: d for b, d in per_bus.items() if d}
  if not per_bus:
    print('\n所有总线上都没有抓到报文。')
    return 2

  merged, conflicts = union_with_conflicts(per_bus)
  print('\n[3] 合并结果：%d 个唯一地址' % len(merged))
  if conflicts:
    print('  !! 出现同地址不同 DLC 的冲突 %d 处，不能压成单个字典，将输出「每总线一个字典」：' % len(conflicts))
    for addr, d1, b, d2 in conflicts[:10]:
      print('     地址 %d: 先见 DLC %d，bus%d 见 DLC %d' % (addr, d1, b, d2))

  # ---- 输出条目 ----
  car = a.car or 'YOUR_CAR_ENUM'
  if conflicts:
    dicts = [per_bus[b] for b in sorted(per_bus)]
    note = '由采集脚本生成（每总线一个字典，因存在同地址不同 DLC）'
  else:
    dicts = [merged]
    note = '由采集脚本生成（并集，最安全）'
  block = fmt_entry(car, dicts, note)

  print('\n[4] 可直接粘贴的条目：')
  print('=' * 78)
  sys.stdout.write(block)
  print('=' * 78)

  outdir = a.outdir
  if not os.path.isdir(outdir):
    os.makedirs(outdir, exist_ok=True)
  outp = os.path.join(outdir, '%s_fingerprint.txt' % car)
  io.open(outp, 'w', encoding='utf-8', newline='\n').write(block)
  print('\n已写入：%s' % outp)

  # ---- 对比模式 ----
  if a.compare:
    if not a.car:
      print('\n--compare 需要同时给 --car，例如 --car BYD_HAN_DMI_22')
      return 1
    existing = load_existing(a.compare, a.car)
    if existing is None:
      print('\n在 %s 里找不到 CAR.%s 的指纹块' % (a.compare, a.car))
      return 1
    missing, extra, dlc_conflict = compare(existing, merged)
    print('\n[5] 与现有指纹对比（%s / CAR.%s）' % (a.compare, a.car))
    print('  现有 %d 条，实车采集 %d 条' % (len(existing), len(merged)))
    print('  ---- 缺失地址 %d 个（必须补，否则这台车认不出来）----' % len(missing))
    print('    ' + (', '.join(str(x) for x in missing) if missing else '（无，很好）'))
    print('  ---- 多余地址 %d 个（无害，建议原样保留）----' % len(extra))
    print('    ' + (', '.join(str(x) for x in extra) if extra else '（无）'))
    print('  ---- DLC 冲突 %d 个（必须查清，否则同样认不出来）----' % len(dlc_conflict))
    for ad in dlc_conflict:
      print('     地址 %d: 现有 DLC %d，实车 DLC %d' % (ad, existing[ad], merged[ad]))

    fixed = dict(existing)
    for ad in missing:
      fixed[ad] = merged[ad]
    for ad in dlc_conflict:
      fixed[ad] = merged[ad]   # 以实车为准
    print('\n  修正后（并集，DLC 冲突处以实车为准）共 %d 条：' % len(fixed))
    print('=' * 78)
    sys.stdout.write(fmt_entry(a.car, [fixed], '并集修正版：保留原有 + 补上实车采集到的'))
    print('=' * 78)
    outp2 = os.path.join(outdir, '%s_fingerprint_merged.txt' % a.car)
    io.open(outp2, 'w', encoding='utf-8', newline='\n').write(
      fmt_entry(a.car, [fixed], '并集修正版：保留原有 + 补上实车采集到的'))
    print('\n已写入：%s' % outp2)

  print('\n完成。把上面的条目替换掉 fingerprints.py 里对应的 CAR.XXX: [{...}], 即可。')
  return 0


if __name__ == '__main__':
  sys.exit(main())
