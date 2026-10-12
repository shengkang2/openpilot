#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检查某品牌的 CAN 指纹是否存在「多候选并列」——这是 FPv1 移植最常见的坑。

为什么需要它
------------
opendbc/car/car_helpers.py::can_fingerprint 的判定不是「能不能匹配上」，而是
**「能不能淘汰到只剩一个」**（注意与 fingerprints.py::is_valid_for_fingerprint
的单条匹配语义不同）：

    candidate_cars = 该品牌全部有指纹的车型
    for 每条总线报文:
        candidate_cars = eliminate_incompatible_cars(can, candidate_cars)
    识别成功 <=> 某条总线上剩下「恰好 1 个」候选

    # 源码里就是这一句：
    if len(candidate_cars[b]) == 1 and frame > FRAME_FINGERPRINT:
        car_fingerprint = candidate_cars[b][0]

因此，只要 A 车型的指纹是 B 车型指纹的**超集**（复制粘贴、或「取同平台并集」来补
半成品车型时极易发生），真实 B 车上的报文会同时保留 A 和 B：

    剩 2 个候选 -> 永远等不到 len == 1 -> car_fingerprint = None
    -> carlog "car doesn't match any fingerprints" -> candidate = "MOCK"

这就是「补了个指纹，反而把原本好好的车型弄坏」的机理。**超集 = 有害**，
和大多数人「多写几条更安全」的直觉正好相反（多写对于 *淘汰* 是安全的，
但对于 *收敛到唯一解* 是有害的）。

用法
----
    python3 tools/car_porting/check_fingerprint_ambiguity.py                # 查全部品牌
    python3 tools/car_porting/check_fingerprint_ambiguity.py --brand byd    # 只查 byd
    python3 tools/car_porting/check_fingerprint_ambiguity.py --brand byd --verbose
    python3 tools/car_porting/check_fingerprint_ambiguity.py --brand byd \
        --extra path/to/fingerprints_supplement.py:FINGERPRINTS_SUPPLEMENT
        # ^ 合并前先体检：会列出「新增车型是否可识别」+「原有车型是否被带坏」

退出码
------
  0 = 全部车型都能唯一识别
  1 = 存在并列候选 / 无候选车型（需要修）
  2 = 用法错误
"""

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CAR_ROOT = REPO_ROOT / "opendbc_repo" / "opendbc" / "car"
DEBUG_ADDRESS = {1880: 8}


class _CarProxy:
  """把源码里的 CAR.BYD_XXX 变成字符串 'BYD_XXX'（这样就无需 import opendbc）。"""

  def __getattr__(self, name):
    return name


class _AnyProxy:
  """兜住 Ecu = CarParams.Ecu / Ecu.eps 之类的语句。"""

  def __getattr__(self, name):
    return _AnyProxy()


def load_fingerprints(path: Path, varname: str = "FINGERPRINTS") -> dict:
  """把 *fingerprints.py 里的 FINGERPRINTS 字典取出来（不需要 opendbc 依赖）。"""
  text = path.read_text(encoding="utf-8")
  text = re.sub(r"^\s*(from|import)\s+.*$", "", text, flags=re.M)
  env = {"CAR": _CarProxy(), "CarParams": _AnyProxy(), "Ecu": _AnyProxy()}
  exec(compile(text, str(path), "exec"), env)  # noqa: S102
  if varname not in env:
    raise KeyError(f"{path} 里找不到 {varname}")
  raw = env[varname]
  return {str(k): (v if isinstance(v, list) else [v]) for k, v in raw.items()}


def _valid(addr: int, dlc: int, fp: dict) -> bool:
  """复刻 fingerprints.py::is_valid_for_fingerprint。"""
  return (addr in fp and fp[addr] == dlc) or addr >= 0x800


def eliminate(addr: int, dlc: int, candidates: list, db: dict) -> list:
  """复刻 fingerprints.py::eliminate_incompatible_cars（单条报文）。"""
  out = []
  for car in candidates:
    for fp in db[car]:
      fp = dict(fp)
      fp.update(DEBUG_ADDRESS)
      if _valid(addr, dlc, fp):
        out.append(car)
        break
  return out


def simulate(observed: dict, db: dict) -> tuple:
  """返回 (识别到的车型 or None, 剩余候选数)。

  observed 用「该车型自己的指纹」代替实车报文集合：这是对真实情况最接近、
  也最保守的近似（作者记录的指纹通常就是该车实发报文）。
  """
  candidates = list(db)
  for addr, dlc in sorted(observed.items()):
    if addr >= 0x800 or addr in (0x7DF, 0x7E0, 0x7E8):
      continue
    candidates = eliminate(addr, dlc, candidates, db)
    if len(candidates) == 1:
      return candidates[0], 1
  return (candidates[0] if len(candidates) == 1 else None), len(candidates)


def brand_files(brand: str | None) -> list:
  if brand:
    p = CAR_ROOT / brand / "fingerprints.py"
    return [p] if p.is_file() else []
  return sorted(CAR_ROOT.glob("*/fingerprints.py"))


def main() -> int:
  ap = argparse.ArgumentParser(description="检查 CAN 指纹是否存在多候选并列（FPv1）",
                               formatter_class=argparse.RawDescriptionHelpFormatter)
  ap.add_argument("--brand", help="只检查某个品牌，例如 byd")
  ap.add_argument("--extra", help="额外合并的候选指纹文件，格式 path/to/file.py:变量名")
  ap.add_argument("--verbose", action="store_true", help="打印每个车型的候选收敛过程")
  a = ap.parse_args()

  files = brand_files(a.brand)
  if not files:
    print(f"找不到品牌 {a.brand!r} 的 fingerprints.py（看下 {CAR_ROOT}）")
    return 2

  extra = {}
  if a.extra:
    if ":" not in a.extra:
      print("--extra 需要写成 path/to/file.py:变量名")
      return 2
    fpath, varname = a.extra.rsplit(":", 1)
    extra = load_fingerprints(Path(fpath), varname)
    print(f"额外候选: {len(extra)} 款 -> {', '.join(sorted(extra))}")

  bad = 0
  for f in files:
    brand = f.parent.name
    base = load_fingerprints(f)
    if not base:
      continue
    merged = dict(base)
    merged.update(extra)

    print(f"\n=== {brand}：{len(base)} 款有指纹", end="")
    print(f"（合并额外候选后 {len(merged)} 款）===" if extra else " ===")

    # 原有车型是否被新增候选带坏
    regressed = []
    for car in sorted(base):
      if car in extra:
        continue
      before = simulate(base[car][0], base)[0]
      after, n = simulate(base[car][0], merged)
      if before == car and after != car:
        regressed.append((car, n))
        if a.verbose:
          print(f"  [回归] {car:<28} 原本唯一 -> 现在剩 {n} 个候选")
      elif before != car and a.verbose:
        print(f"  [原有问题] {car:<28} 本来就不唯一（剩 {n} 个候选）")

    dim = {}
    for car in sorted(merged):
      got, n = simulate(merged[car][0], merged)
      if got == car:
        if a.verbose:
          print(f"  OK        {car}")
      else:
        dim[car] = n

    for car, n in sorted(dim.items()):
      mark = "  [被新增候选带坏]" if car in {r[0] for r in regressed} else ""
      print(f"  ✗ 无法唯一识别 {car:<28} 剩 {n} 个候选{mark}")

    # 跨车型完全同指纹（最严重的形态）
    seen = {}
    for car in sorted(merged):
      key = tuple(sorted(merged[car][0].items()))
      seen.setdefault(key, []).append(car)
    for key, cars in seen.items():
      if len(cars) > 1:
        print(f"  !! 指纹完全相同（{len(key)} 条报文）: {', '.join(cars)}")
        print("     这些车型在任何情况下都无法互相区分，必须用真实 CAN 日志补差异报文")

    bad += len(dim)

  print("\n" + "=" * 64)
  if bad == 0:
    print("结论：全部车型都能唯一识别 ✅")
    return 0
  print(f"结论：{bad} 处车型无法唯一识别，需要修正 ❌")
  print("修法：抓一次真实 CAN 日志，用 tools/car_porting/collect_live_fingerprints.py")
  print("      对比出「缺哪些地址 / 哪些 DLC 不符」，把差异补进去。")
  return 1


if __name__ == "__main__":
  sys.exit(main())
