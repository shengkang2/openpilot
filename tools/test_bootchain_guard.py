#!/usr/bin/env python3
"""验证引导链硬拦截逻辑。

模拟四种情形：
  1. bp7 自带清单（abl/boot 是 fork 自改版）→ 必须抛异常
  2. 官方清单 → 必须放行
  3. 只含 system 的清单 → 必须放行
  4. 异常必须在 abctl --set_unbootable 之前抛出（否则会留下刷一半的槽）
"""
import json
import sys
import types
import importlib.util
import pathlib

REPO = pathlib.Path(__file__).resolve().parent.parent
AGNOS_PY = REPO / "system" / "hardware" / "tici" / "agnos.py"


def load_agnos():
    """加载 agnos.py，但把 openpilot.* 依赖换成桩，避免整包 import。"""
    # requests 是真依赖（要装）；openpilot.* 只需要模块存在
    fake_paths = [
        ("openpilot", None),
        ("openpilot.system", None),
        ("openpilot.system.updated", None),
        ("openpilot.system.updated.casync", None),
        ("openpilot.system.updated.casync.casync", None),
    ]
    for name, _ in fake_paths:
        if name not in sys.modules:
            m = types.ModuleType(name)
            m.__path__ = []
            sys.modules[name] = m
    casync_mod = sys.modules["openpilot.system.updated.casync.casync"]
    casync_mod.parse_caibx = lambda *a, **k: None
    sys.modules["openpilot"].system = sys.modules["openpilot.system"]
    sys.modules["openpilot.system"].updated = sys.modules["openpilot.system.updated"]
    sys.modules["openpilot.system.updated"].casync = sys.modules["openpilot.system.updated.casync"]
    sys.modules["openpilot.system.updated.casync"].casync = casync_mod

    spec = importlib.util.spec_from_file_location("agnos_mod", AGNOS_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    mod = load_agnos()
    assert hasattr(mod, "assert_official_boot_chain"), "缺少 assert_official_boot_chain"

    repo_manifest = json.loads((REPO / "system" / "hardware" / "tici" / "agnos.json").read_text(encoding="utf-8"))
    official_manifest = [
        {"name": "abl", "hash_raw": "0" * 64, "url": "x", "size": 1, "sparse": False,
         "full_check": True, "has_ab": True},
        {"name": "boot", "hash_raw": "1" * 64, "url": "x", "size": 1, "sparse": False,
         "full_check": True, "has_ab": True},
        {"name": "system", "hash_raw": "2" * 64, "url": "x", "size": 1, "sparse": True,
         "full_check": False, "has_ab": True},
    ]

    failures = []

    # 情形 1：仓库自带清单必须被拒
    try:
        mod.assert_official_boot_chain(repo_manifest)
        failures.append("情形1 FAIL: bp7 自带清单竟然通过了拦截")
    except RuntimeError as e:
        print(f"  情形1 PASS: 拦截到 fork 自改引导链 -> {str(e)[:70]}...")

    # 情形 2：官方清单必须放行
    try:
        mod.assert_official_boot_chain(official_manifest)
        print("  情形2 PASS: 官方清单放行")
    except RuntimeError as e:
        failures.append(f"情形2 FAIL: 官方清单被误拦 -> {e}")

    # 情形 3：只含 system 必须放行
    try:
        mod.assert_official_boot_chain([official_manifest[2]])
        print("  情形3 PASS: 仅 system 清单放行")
    except RuntimeError as e:
        failures.append(f"情形3 FAIL: 仅 system 被误拦 -> {e}")

    # 情形 4：拦截必须早于 set_unbootable
    src = AGNOS_PY.read_text(encoding="utf-8")
    lines = src.splitlines()
    # 找真正的函数定义行（行首就是 "def flash_agnos_update"）
    fn_start = next(i for i, l in enumerate(lines) if l.startswith("def flash_agnos_update"))
    fn_end = next(i for i, l in enumerate(lines[fn_start + 1:], fn_start + 1)
                  if l.startswith("def ") or l.startswith("if __name__"))
    body = lines[fn_start:fn_end]

    guard_pos = next((i for i, l in enumerate(body)
                       if l.strip().startswith("assert_official_boot_chain(")), -1)
    unboot_pos = next((i for i, l in enumerate(body)
                        if "abctl --set_unbootable" in l and not l.strip().startswith("#")), -1)
    if guard_pos == -1:
        failures.append("情形4 FAIL: flash_agnos_update 里没有调用拦截")
    elif unboot_pos == -1:
        failures.append("情形4 FAIL: 没找到 set_unbootable，无法判断顺序")
    elif guard_pos < unboot_pos:
        print(f"  情形4 PASS: 拦截在函数体第 {guard_pos} 行，早于第 {unboot_pos} 行的 set_unbootable")
    else:
        failures.append(f"情形4 FAIL: 拦截在函数体第 {guard_pos} 行，晚于第 {unboot_pos} 行，会留下刷一半的槽")

    print()
    if failures:
        for f in failures:
            print(f"  !! {f}")
        return 1
    print("引导链硬拦截：全部通过 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
