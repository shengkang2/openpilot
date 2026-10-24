#!/usr/bin/env bash
# bp7 一键安装脚本（链接安装入口）
#
# 用法（在 comma three 设备上，通过 SSH 或 ADB shell 执行）：
#
#   bash <(curl -fsSL https://raw.githubusercontent.com/shengkang2/openpilot/bp7.020261020/install.sh)
#
# 或者在已经 checkout 到本仓库的目录里：
#
#   bash install.sh
#
# 它做什么：
#   1. 检查环境（是否在设备上、AGNOS 版本、当前槽位）
#   2. 拉取并切到目标分支（默认 bp7.020261020）
#   3. 重建子模块（切分支后子模块目录常是上一分支的残留，会报 No tool module）
#   4. 拉 LFS 资源（模型 onnx）
#   5. 应用源码级适配补丁（AGNOS 版本钉子、params 白名单、中文字库、Jetlink 汉化）
#   6. 重定向 uv 缓存到 /data（/home 只有 100MB overlay，uv sync 必然 No space left）
#   7. 编译（scons -j2 + swapfile，绕开 build.py 的 OOM 重试）
#   8. 重启 comma 服务
#
# 安全设计（血泪教训，全部来自实际变砖）：
#   - **绝不写任何分区**：不刷 boot/system/xbl/abl，不换槽，引导链零改动。
#     历史上所有成功案例都是零分区写入，所有变砖案例都跟刷引导链有关。
#   - **不碰 ABL**：bp7 自带的 agnos.json 里 abl=b6fba807、boot=19ff57b6 都是
#     fork 自改的，刷进去 bootloader 直接拒绝加载 → Unsupported firmware detected。
#   - **AGNOS_VERSION 动态钉实机版本**：写死任何数字都可能在别的 AGNOS 版本设备上
#     触发开机自动升级刷写。两处 launch_env.sh 都改成运行时读 /VERSION。
#   - **失败可回滚**：编译失败不影响系统启动，git checkout 回原分支重编即可。
#
# 环境变量：
#   BP7_BRANCH   要安装的分支（默认 bp7.020261020）
#   BP7_REPO     仓库地址（默认 https://github.com/shengkang2/openpilot.git）
#   BP7_JOBS     编译并发（默认 2；tici 只有 3.6G 内存且无 swap）
#   BP7_SKIP_BUILD=1 只做源码适配不编译

set -euo pipefail

BP7_BRANCH="${BP7_BRANCH:-bp7.020261020}"
BP7_REPO="${BP7_REPO:-https://github.com/shengkang2/openpilot.git}"
BP7_JOBS="${BP7_JOBS:-2}"
OP="${OP:-/data/openpilot}"
LOG="${LOG:-/data/bp7_install.log}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
hr() { echo; echo "===== $* ====="; }
ok() { echo -e "${GREEN}  ✔ $*${NC}"; }
warn() { echo -e "${YELLOW}  ! $*${NC}"; }
die() { echo -e "${RED}  ✗ $*${NC}"; exit 1; }

# 非交互：comma 上没有凭据助手，git 会静默挂起等用户名密码（表现为 fetch 永远不返回）
export GIT_TERMINAL_PROMPT=0
export GIT_ASKPASS=/bin/true
export GCM_INTERACTIVE=never

# uv 缓存必须指到 /data：/home 是 100MB overlay，uv sync 约 100MB 轮子必然撑爆
export UV_CACHE_DIR=/data/uv-cache
export UV_PYTHON_INSTALL_DIR=/data/uv-python
export UV_PYTHON_CACHE_DIR=/data/uv-python
export UV_LINK_MODE=copy
export TMPDIR=/data/tmp
mkdir -p "$UV_CACHE_DIR" "$UV_PYTHON_INSTALL_DIR" "$TMPDIR" 2>/dev/null || true

exec > >(tee -a "$LOG") 2>&1

echo "bp7 安装器  分支=$BP7_BRANCH  日志=$LOG"

# ---------------------------------------------------------------- 环境自检
hr "0. 环境自检"

if [ ! -d /data ]; then
  warn "看起来不在 comma 设备上（没有 /data）。将以当前目录为 openpilot 根继续。"
  OP="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi

[ -d "$OP/.git" ] || die "$OP 不是 git 仓库，请先 clone 或指定 OP 环境变量"
cd "$OP"

AGNOS_VERSION="$(cat /VERSION 2>/dev/null || echo unknown)"
ROOT_PART="$(findmnt -no SOURCE / 2>/dev/null || echo unknown)"
ok "AGNOS 版本 : $AGNOS_VERSION"
ok "根分区     : $ROOT_PART"

if [ "$ROOT_PART" != "/dev/sda6" ] && [ "$ROOT_PART" != "unknown" ]; then
  warn "当前不在 A 槽（$ROOT_PART）。本脚本不刷任何分区，换槽与否由你决定。"
fi

# 记录引导链基线：只读哈希，装完对比，证明零改动
hr "0.5 引导链基线（只读，用于事后证明零改动）"
for p in xbl_a xbl_config_a abl_a aop_a devcfg_a; do
  h=$(sudo -n sha256sum /dev/disk/by-partlabel/$p 2>/dev/null | cut -d' ' -f1 || true)
  [ -n "$h" ] && echo "  $p = $h"
done | tee /data/bp7_chain_before.txt 2>/dev/null || true

# ---------------------------------------------------------------- 拉分支
hr "1. 拉取并切换到 $BP7_BRANCH"

ORIG_BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"
ORIG_SHA="$(git rev-parse HEAD 2>/dev/null || echo unknown)"
echo "  切分支前: $ORIG_BRANCH @ ${ORIG_SHA:0:9}"
echo "$ORIG_BRANCH $ORIG_SHA" > /data/bp7_install_origin.txt

rm -f "$OP/.git/index.lock"
git fetch --depth 1 origin "$BP7_BRANCH" || die "拉取分支失败：$BP7_BRANCH"
git checkout -f -B "$BP7_BRANCH" FETCH_HEAD || die "切换分支失败"
ok "已切到 $(git log --oneline -1)"

# ---------------------------------------------------------------- 子模块
hr "2. 重建子模块"
# git checkout 不会更新子模块。切分支后子模块目录里常是上一分支的半份内容和编译产物，
# 直接 submodule update 会报 "destination path already exists"，必须先清空再拉。
for d in msgq_repo rednose_repo teleoprtc_repo tinygrad_repo sunnypilot/neural_network_data; do
  if [ -e "$d" ] && git submodule status "$d" 2>/dev/null | grep -q '^-'; then
    rm -rf "$d"
    echo "  清理残留: $d"
  fi
done
git submodule update --init --recursive || warn "子模块初始化有告警，继续"
git submodule status | head -10

# ---------------------------------------------------------------- LFS
hr "3. LFS 资源"
# .lfsconfig 指向上游 hwh-kavin/openpilot，推 LFS 会报无权限；拉取不受影响，先挪开
[ -f .lfsconfig ] && mv -f .lfsconfig .lfsconfig.bak
git lfs pull || warn "LFS 拉取失败，模型可能缺失"
ls -la selfdrive/modeld/models/*.onnx 2>/dev/null | head -3 || true

# ---------------------------------------------------------------- 源码适配
hr "4. 源码级适配（幂等）"

# 4.1 AGNOS_VERSION 钉成实机版本 —— 这是防变砖的关键，两处都要
V="$(cat /VERSION 2>/dev/null || echo '')"
if [ -n "$V" ]; then
  for f in launch_env.sh sunnypilot/system/hardware/c3/launch_env.sh; do
    [ -f "$f" ] || continue
    if grep -q 'AGNOS_VERSION="\$(tr' "$f"; then
      echo "  [$f] 已改为动态读取 /VERSION"
    else
      sed -i "s/export AGNOS_VERSION=\"[^\"]*\"/export AGNOS_VERSION=\"\$(tr -d '[:space:]' < \/VERSION)\"/" "$f"
      echo "  [$f] AGNOS_VERSION -> 动态读取 /VERSION"
    fi
  done
fi

# 4.2 params 白名单：bp7 的 hardwared.py 会写 Offroad_AcceleratorUnavailable，
#     但 params_keys.h 白名单漏注册，Params.get() 走 C++ 严格校验直接抛异常，
#     UI 每秒崩一次 UnknownKeyName
H=common/params_keys.h
if [ -f "$H" ] && ! grep -q 'Offroad_AcceleratorUnavailable' "$H"; then
  sed -i 's|    {"Offroad_CarUnrecognized"|    {"Offroad_AcceleratorUnavailable", {CLEAR_ON_MANAGER_START \| CLEAR_ON_ONROAD_TRANSITION, JSON}},\n    {"Offroad_CarUnrecognized"|' "$H"
  echo "  [params_keys.h] 已补 Offroad_AcceleratorUnavailable"
fi

# 4.3 sign.py 执行位：检出时 mode 位可能没还原，panda 固件签名会报 Error 126
chmod +x panda/board/crypto/sign.py 2>/dev/null || true

# 4.4 PYTHONPATH 保留 /data/pylibs（AGNOS 18.x 下 capnproto 半装状态的解药）
for f in launch_chffrplus.sh sunnypilot/system/hardware/c3/launch_chffrplus.sh; do
  [ -f "$f" ] || continue
  if ! grep -q 'PYTHONPATH="/data/pylibs:' "$f"; then
    sed -i 's|export PYTHONPATH="$PWD"|export PYTHONPATH="/data/pylibs:$PWD"|' "$f"
    echo "  [$f] PYTHONPATH 已保留 /data/pylibs"
  fi
done

# 4.5 中文化补丁（脚本已随仓库带上，幂等）
if [ -f tools/fix_jetlink_i18n.py ] && [ -f tools/add_jetlink_po.py ]; then
  PY=/usr/local/venv/bin/python3
  [ -x "$PY" ] || PY=$(command -v python3 || true)
  if [ -n "$PY" ]; then
    "$PY" tools/fix_jetlink_i18n.py || warn "Jetlink 汉化补丁有告警"
    "$PY" tools/add_jetlink_po.py   || warn "po 词条补充有告警"
  else
    warn "找不到 python3，跳过汉化补丁"
  fi
fi

# ---------------------------------------------------------------- 依赖
hr "5. 依赖准备"
export PATH="/usr/local/venv/bin:$PATH"
export PYTHONPATH="/data/pylibs:$OP"

if command -v uv > /dev/null 2>&1; then
  echo "  uv sync（缓存指向 /data）"
  uv sync || warn "uv sync 失败，若已有 .venv 可忽略"
else
  warn "没有 uv，跳过依赖同步（沿用设备上已有的 .venv）"
fi

# 内存：tici 3.6G 无 swap，build.py 默认高并发会被 OOM SIGKILL（EXIT=137）
if ! swapon --show 2>/dev/null | grep -q .; then
  warn "没有 swap，创建 3G swapfile（编译期内存不够会被 OOM 杀掉）"
  sudo -n fallocate -l 3G /data/swapfile 2>/dev/null \
    && sudo -n chmod 600 /data/swapfile \
    && sudo -n mkswap /data/swapfile > /dev/null 2>&1 \
    && sudo -n swapon /data/swapfile && ok "swapfile 已启用" \
    || warn "swapfile 创建失败，继续（编译可能 OOM）"
fi

# ---------------------------------------------------------------- 编译
if [ "${BP7_SKIP_BUILD:-0}" = "1" ]; then
  hr "6. 跳过编译（BP7_SKIP_BUILD=1）"
else
  hr "6. 编译（scons -j$BP7_JOBS）"
  # 停掉 openpilot 释放内存（UI 常年占 2.3G）
  sudo -n systemctl stop comma 2>/dev/null || true
  rm -f "$OP/prebuilt"

  cd "$OP"
  set +e
  scons -j"$BP7_JOBS" 2>&1 | tail -40
  RC=${PIPESTATUS[0]}
  set -e
  echo "  BUILD EXIT=$RC"

  if [ "$RC" -ne 0 ]; then
    die "编译失败。系统本身未受影响（全程零分区写入），可回滚：
  cd $OP && git checkout -f $ORIG_BRANCH && bash install.sh"
  fi
  touch "$OP/prebuilt"
  ok "编译完成"
fi

# ---------------------------------------------------------------- 重启
hr "7. 启动与验证"
sudo -n systemctl start comma 2>/dev/null || systemctl start comma || warn "启动 comma 失败"
sleep 10

if systemctl is-active --quiet comma 2>/dev/null; then
  ok "comma 服务运行中"
else
  warn "comma 服务异常，查看日志：sudo journalctl -u comma -n 50"
fi

# 引导链事后比对：证明全程零改动
hr "8. 引导链事后比对（应与基线完全一致）"
for p in xbl_a xbl_config_a abl_a aop_a devcfg_a; do
  h=$(sudo -n sha256sum /dev/disk/by-partlabel/$p 2>/dev/null | cut -d' ' -f1 || true)
  [ -n "$h" ] && echo "  $p = $h"
done | tee /data/bp7_chain_after.txt 2>/dev/null || true

if [ -f /data/bp7_chain_before.txt ] && [ -f /data/bp7_chain_after.txt ]; then
  if diff -q /data/bp7_chain_before.txt /data/bp7_chain_after.txt > /dev/null; then
    ok "引导链零改动 ✅（本次安装没有碰任何分区）"
  else
    warn "引导链哈希有变化，请立即检查！"
    diff /data/bp7_chain_before.txt /data/bp7_chain_after.txt || true
  fi
fi

# 检查是否误触发自动 AGNOS 升级（那会刷引导链，是变砖入口）
if pgrep -f "hardware/tici/agnos.py" > /dev/null 2>&1; then
  warn "检测到 agnos.py 正在运行！立刻杀掉（它会刷引导链导致变砖）"
  sudo -n pkill -f "hardware/tici/agnos.py" || true
  sleep 2
  if pgrep -f "hardware/tici/agnos.py" > /dev/null 2>&1; then
    die "无法终止 agnos.py，请手动处理"
  fi
  ok "已终止"
else
  ok "无 AGNOS 自动升级进程 ✅"
fi

echo
echo "完成。语言设置需为 main_zh-CHS。"
echo "回滚：cd $OP && git checkout -f $ORIG_BRANCH && bash install.sh"
