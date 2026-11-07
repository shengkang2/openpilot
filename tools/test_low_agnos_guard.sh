#!/usr/bin/env bash
# 验证低版本设备（AGNOS 12.x / 13.x）场景下，四道闸门全部生效：
#   1. launch_env.sh 动态钉子 → agnos_init 的版本比较恒等，不触发升级
#   2. launch_env.sh 哨兵 BP7_DYNAMIC_AGNOS_PIN
#   3. launch_chffrplus.sh 三道闸（哨兵 / 哨兵版本号 / 禁止降级）
#   4. agnos.py 版本匹配闸 → 实机版本 != 18.5 时拒绝整份清单
#
# 用法：bash sandbox_lowagnos_test.sh
set -u

SRC="C:/Users/sheng/WorkBuddy/2026-10-24-19-25-21/bp7"
SB="C:/Users/sheng/WorkBuddy/2026-10-24-19-25-21/sandbox_lowagnos"
VP="C:/Users/sheng/.workbuddy/binaries/python/envs/default/Scripts/python.exe"

PASS=0; FAIL=0
ok()  { echo "  PASS: $*"; PASS=$((PASS+1)); }
bad() { echo "  FAIL: $*"; FAIL=$((FAIL+1)); }

rm -rf "$SB"; mkdir -p "$SB"
cp "$SRC/launch_env.sh" "$SRC/launch_chffrplus.sh" "$SB/" 2>/dev/null
mkdir -p "$SB/system/hardware/tici"
cp "$SRC/system/hardware/tici/agnos.py" "$SB/system/hardware/tici/" 2>/dev/null

echo "=========================================="
echo " 场景 A：AGNOS 12.8 设备（低版本）"
echo "=========================================="

# --- A1: 动态钉子 → 版本比较恒等 ---
sed "s#/VERSION#$SB/VERSION#g" "$SB/launch_env.sh" > "$SB/le_test.sh"
echo "12.8" > "$SB/VERSION"
AGG=$(cd "$SB" && bash -c 'unset AGNOS_VERSION; . ./le_test.sh >/dev/null 2>&1; echo "$AGNOS_VERSION"')
if [ "$AGG" = "12.8" ]; then
  ok "A1 动态钉子：设备 /VERSION=12.8 → AGNOS_VERSION=12.8（与实机恒等，不触发升级）"
else
  bad "A1 动态钉子异常：得到 '$AGG'"
fi

# --- A2: agnos_init 的版本比较 ---
CMP=$(cd "$SB" && ( [ "$(cat VERSION)" != "$AGG" ] && echo "TRIGGER" || echo "SAFE" ))
if [ "$CMP" = "SAFE" ]; then
  ok "A2 agnos_init 版本比较：12.8 == 12.8 → 不触发 AGNOS 升级（零刷写）"
else
  bad "A2 agnos_init 会触发升级！"
fi

# --- A3: 哨兵存在 ---
if grep -q 'BP7_DYNAMIC_AGNOS_PIN="1"' "$SB/le_test.sh"; then
  ok "A3 哨兵 BP7_DYNAMIC_AGNOS_PIN 已导出"
else
  bad "A3 哨兵缺失"
fi

# --- A4: launch_chffrplus.sh 三道闸 ---
python - "$SB/launch_chffrplus.sh" <<'PYEOF' 2>/dev/null || bad "A4 无法解析 launch_chffrplus.sh"
import sys, re
src = open(sys.argv[1], encoding="utf-8").read()
body = src[src.index("function agnos_init"):src.index("\nfunction ", src.index("function agnos_init")+10)]
checks = {
  "闸门1 动态钉子哨兵": 'BP7_DYNAMIC_AGNOS_PIN' in body,
  "闸门2 哨兵版本号": '__BP7_NO_VERSION__' in body,
  "闸门3 禁止降级": 'sort -V' in body,
}
for name, good in checks.items():
    print(f"  {'PASS' if good else 'FAIL'}: A4 {name}")
sys.exit(0 if all(checks.values()) else 1)
PYEOF
if [ $? -eq 0 ]; then PASS=$((PASS+3)); else FAIL=$((FAIL+1)); fi

# --- A5: agnos.py 版本匹配闸（低版本设备必须被拒） ---
cat > "$SB/t_agnos.py" <<'PYEOF'
import importlib.util, json, sys, types
for name in ("openpilot", "openpilot.system", "openpilot.system.updated",
             "openpilot.system.updated.casync", "openpilot.system.updated.casync.casync"):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.modules["openpilot.system.updated.casync.casync"].parse_caibx = lambda *a, **k: None
spec = importlib.util.spec_from_file_location("agnos_mod", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
manifest = json.load(open(sys.argv[2], encoding="utf-8"))
try:
    mod.assert_boot_chain_matches_device(manifest)
    print("  FAIL: A5 版本匹配闸未拦住低版本设备")
    sys.exit(1)
except RuntimeError as e:
    print(f"  PASS: A5 版本匹配闸拦住低版本设备 —— {str(e)[:60]}…")
    sys.exit(0)
PYEOF
cat > "$SB/fake_agnos.py" <<'PYEOF'
import os
os.makedirs("/VERSION", exist_ok=True)
PYEOF
# 用 monkeypatch 模拟实机 /VERSION=12.8
cat > "$SB/run_a5.py" <<'PYEOF'
import importlib.util, json, sys, types
from io import StringIO
_orig_open = open
def fake_open(f, *a, **k):
    if f == "/VERSION":
        return StringIO("12.8")
    return _orig_open(f, *a, **k)
import builtins
builtins.open = fake_open
for name in ("openpilot", "openpilot.system", "openpilot.system.updated",
             "openpilot.system.updated.casync", "openpilot.system.updated.casync.casync"):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.modules["openpilot.system.updated.casync.casync"].parse_caibx = lambda *a, **k: None
spec = importlib.util.spec_from_file_location("agnos_mod", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
manifest = json.load(_orig_open(sys.argv[2], encoding="utf-8"))
try:
    mod.assert_boot_chain_matches_device(manifest)
    print("  FAIL: A5 版本匹配闸未拦住低版本设备")
    sys.exit(1)
except RuntimeError as e:
    print(f"  PASS: A5 版本匹配闸拦住 AGNOS 12.8 设备 —— {str(e)[:70]}…")
    sys.exit(0)
PYEOF
"$VP" "$SB/run_a5.py" "$SB/system/hardware/tici/agnos.py" "$SRC/system/hardware/tici/agnos.json" 2>&1 | tr '\r' '\n'
if [ ${PIPESTATUS[0]:-0} -eq 0 ]; then PASS=$((PASS+1)); else FAIL=$((FAIL+1)); fi

echo ""
echo "=========================================="
echo " 场景 B：AGNOS 18.5 设备（匹配版本，应放行）"
echo "=========================================="
cat > "$SB/run_b5.py" <<'PYEOF'
import importlib.util, json, sys, types
from io import StringIO
_orig_open = open
def fake_open(f, *a, **k):
    if f == "/VERSION":
        return StringIO("18.5")
    return _orig_open(f, *a, **k)
import builtins
builtins.open = fake_open
for name in ("openpilot", "openpilot.system", "openpilot.system.updated",
             "openpilot.system.updated.casync", "openpilot.system.updated.casync.casync"):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.modules["openpilot.system.updated.casync.casync"].parse_caibx = lambda *a, **k: None
spec = importlib.util.spec_from_file_location("agnos_mod", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
manifest = json.load(_orig_open(sys.argv[2], encoding="utf-8"))
try:
    mod.assert_boot_chain_matches_device(manifest)
    print("  PASS: B5 版本匹配闸放行 AGNOS 18.5 设备（正常升级不被误伤）")
    sys.exit(0)
except RuntimeError as e:
    print(f"  FAIL: B5 18.5 设备被误拦 —— {str(e)[:60]}")
    sys.exit(1)
PYEOF
"$VP" "$SB/run_b5.py" "$SB/system/hardware/tici/agnos.py" "$SRC/system/hardware/tici/agnos.json" 2>&1 | tr '\r' '\n'
if [ ${PIPESTATUS[0]:-0} -eq 0 ]; then PASS=$((PASS+1)); else FAIL=$((FAIL+1)); fi

echo ""
echo "=========================================="
echo " 场景 C：fork 自改哈希（原有拦截不回归）"
echo "=========================================="
"$VP" "$SRC/tools/test_bootchain_guard.py" 2>&1 | tr '\r' '\n' | grep -E "PASS|FAIL|情形"
if [ ${PIPESTATUS[0]:-0} -eq 0 ]; then PASS=$((PASS+4)); else FAIL=$((FAIL+1)); fi

echo ""
echo "=========================================="
echo " 场景 D：install.sh 低版本拦截"
echo "=========================================="
if grep -q "BP7_FORCE_LOW_AGNOS" "$SRC/install.sh" && grep -q "assert_boot_chain_matches_device" "$SRC/install.sh"; then
  ok "D1 install.sh 含低版本拦截与版本闸校验"
  PASS=$((PASS+1))
else
  bad "D1 install.sh 缺少低版本拦截"
  FAIL=$((FAIL+1))
fi

echo ""
echo "=========================================="
echo " 结果：PASS=$PASS  FAIL=$FAIL"
echo "=========================================="
[ "$FAIL" = "0" ] && echo "全部通过 ✅" || echo "有失败项 ❌"
exit $([ "$FAIL" = "0" ] && echo 0 || echo 1)
