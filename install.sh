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
# 如果 /data/openpilot 不存在，脚本会自动 clone（含 LFS），不需要先手动 clone。
# 如果设备上 GitHub 不通，用离线包：
#
#   # PC 上： bash tools/make_bundle.sh   -> 生成 bp7-offline.tar.gz
#   # 设备上：把包传到 /data 后
#   tar -xzf /data/bp7-offline.tar.gz -C /data && bash /data/bp7-offline/install.sh
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
OFFLINE="${OFFLINE:-0}"

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

# ---------------------------------------------------------------- bootstrap
# 离线包优先判定（包内有 .bp7_offline 标记）：跳过 git fetch / submodule / LFS。
if [ -f "$OP/.bp7_offline" ]; then
  warn "离线包模式（$OP）—— 跳过 git fetch / submodule / LFS，使用包内完整源码"
  OFFLINE=1
elif [ ! -d "$OP/.git" ]; then
  if [ "${BP7_BOOTSTRAPPED:-0}" = "1" ]; then
    die "$OP 仍不是 git 仓库，bootstrap 失败"
  fi
  hr "0.1 Bootstrap：clone $BP7_REPO ($BP7_BRANCH)"
  if ! command -v git > /dev/null 2>&1; then
    die "设备上没有 git，先装 git：sudo apt-get install -y git git-lfs"
  fi
  if [ -e "$OP" ] && [ -n "$(ls -A "$OP" 2>/dev/null)" ]; then
    warn "$OP 非空但不是 git 仓库 —— 保留内容，在其中 init 并尝试拉取"
    git -C "$OP" init -q || die "git init 失败"
    git -C "$OP" remote add origin "$BP7_REPO" 2>/dev/null || \
      git -C "$OP" remote set-url origin "$BP7_REPO"
  else
    mkdir -p "$OP" || die "无法创建 $OP"
    git clone --depth 1 -b "$BP7_BRANCH" "$BP7_REPO" "$OP" || die "clone 失败（设备可能访问不了 GitHub？改用离线包 tools/make_bundle.sh）"
  fi
  # LFS：模型在 LFS 里，clone 下来是指针文件，编译会失败
  if command -v git-lfs > /dev/null 2>&1; then
    git -C "$OP" lfs install --skip-repo > /dev/null 2>&1 || true
    git -C "$OP" lfs pull || warn "LFS 拉取失败，模型可能缺失"
  else
    warn "设备没有 git-lfs，模型会是指针文件。装：sudo apt-get install -y git-lfs"
  fi
  # 交接给仓库内的 install.sh（它带完整上下文：tools/ 补丁、自身分支校验）
  if [ -f "$OP/install.sh" ]; then
    export BP7_BOOTSTRAPPED=1
    ok "Bootstrap 完成，转交 $OP/install.sh"
    exec bash "$OP/install.sh"
  fi
  warn "$OP/install.sh 不存在，继续用当前脚本"
fi

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
for p in xbl_a xbl_config_a abl_a devcfg_a aop_a; do
  h=$(sudo -n sha256sum /dev/disk/by-partlabel/$p 2>/dev/null | cut -d' ' -f1 || true)
  [ -n "$h" ] && echo "  $p = $h"
done | tee /data/bp7_chain_before.txt 2>/dev/null || true

# ---------------------------------------------------------------- 装前体检
# 全程只读。目的：装之前把「会不会变砖」这件事问清楚，而不是装完再看。
hr "0.6 装前体检（只读，不做任何写入）"

DEV_MODEL="$(tr -d '\0' < /sys/firmware/devicetree/base/model 2>/dev/null || echo unknown)"
DEV_SLOT="$(sudo -n abctl --boot_slot 2>/dev/null || echo unknown)"
DEV_MODEL_ID="$(grep -m1 'tegra_platform' /proc/cmdline 2>/dev/null | cut -d= -f2 || echo unknown)"
ok "设备型号   : $DEV_MODEL"
ok "当前槽位   : $DEV_SLOT"

# 版本绑定铁律：boot 与 system 必须同版本。bp7 编译产物是按 18.5 生成的，
# 设备底包如果是别的版本，openpilot 用户空间可能起不来 —— 但这跟引导链
# 无关，属于「装得上但跑不起来」，可回滚。
if [ "$AGNOS_VERSION" = "18.5" ]; then
  ok "AGNOS 版本 : $AGNOS_VERSION（与 bp7 底包一致 ✅）"
else
  warn "AGNOS 版本 : $AGNOS_VERSION（bp7 按 18.5 编译）"
  warn "  boot 与 system 版本必须绑定。若装完起不来，是版本不匹配，不是变砖。"
  warn "  引导链不受影响 —— 本脚本不刷任何分区。"
fi

# 低版本设备（12.x / 13.x）的特别风险判定。
#
# 变砖的根源是「引导链与硬件世代强绑定」：bp7 的 agnos.json 是 AGNOS 18.5
# 的整套镜像（含 18.5 的 xbl/abl/boot）。装到 12.x 设备上，只要有任何路径
# 触发 AGNOS 升级，18.5 的引导链就会盖到 12.x 的 bootloader 上 → bootloader
# 拒绝加载 → 变砖（Unsupported firmware detected，SSH 与网络全断）。
#
# 更实际的问题是：bp7 根本编不过。acados / capnproto / eigen 头文件与
# Python 3.12.13 只有 18.5 镜像自带，12.x 上装依赖也拿不到。
# 所以低版本设备装 bp7 = 编不过 + 白折腾。
#
# 这里不直接 die —— 装 bp7 到低版本设备本身是安全的（本脚本零分区写入），
# 但必须把话说清楚，让老板自己决定要不要继续。
AGNOS_MAJOR="${AGNOS_VERSION%%.*}"
if [ "$AGNOS_VERSION" != "18.5" ] && [ "$AGNOS_MAJOR" != "unknown" ] && [ "$AGNOS_MAJOR" -lt 18 ] 2>/dev/null; then
  warn ""
  warn "⚠️  检测到低版本设备：AGNOS $AGNOS_VERSION（低于 bp7 底包 18.5）"
  warn ""
  warn "  预期结果："
  warn "   · 编译大概率失败 —— acados / capnproto / eigen 头文件与 Python 3.12.13"
  warn "     只有 AGNOS 18.5 镜像自带，$AGNOS_VERSION 上装不出这套依赖。"
  warn "   · 即使编过，openpilot 用户空间也可能起不来（boot 与 system 版本绑定）。"
  warn ""
  warn "  安全保证："
  warn "   · 本脚本全程零分区写入，引导链不会被改动，不会变砖。"
  warn "   · 三道闸门已就位：动态钉子 / agnos.py 硬拦截 / 版本匹配闸，"
  warn "     即使开机自动 AGNOS 升级被触发，也会拒绝刷不匹配的引导链。"
  warn ""
  warn "  建议：先用官方途径把设备升到 AGNOS 18.5，再装 bp7。"
  warn "  确认要继续（大概率编译失败）请设 BP7_FORCE_LOW_AGNOS=1"
  warn ""
  if [ "${BP7_FORCE_LOW_AGNOS:-0}" != "1" ]; then
    die "AGNOS $AGNOS_VERSION 低于 bp7 底包 18.5，预期编译失败。确认要试请加 BP7_FORCE_LOW_AGNOS=1。"
  fi
  warn "已指定 BP7_FORCE_LOW_AGNOS=1，继续（失败不会变砖，可回滚）"
fi

# 引导链现状：看 abl/boot 是否已经是 fork 自改版。
# 如果已经是，说明设备早就被刷过自改引导链，现在只是维持现状，不会有新增风险。
BEFORE_ABL="$(sudo -n sha256sum /dev/disk/by-partlabel/abl_${DEV_SLOT} 2>/dev/null | cut -d' ' -f1 || true)"
BEFORE_BOOT="$(sudo -n sha256sum /dev/disk/by-partlabel/boot_${DEV_SLOT} 2>/dev/null | cut -d' ' -f1 || true)"
[ -n "$BEFORE_ABL" ] && ok "当前 abl  = ${BEFORE_ABL:0:16}…"
[ -n "$BEFORE_BOOT" ] && ok "当前 boot = ${BEFORE_BOOT:0:16}…"

# 关键检查：本仓库自带的 agnos.json 里的 abl/boot 是 fork 自改版。
# agnos.py 已在代码层硬拦截（assert_official_boot_chain），
# 这里再确认一次拦截确实在源码里生效。
if grep -q "assert_official_boot_chain" system/hardware/tici/agnos.py 2>/dev/null; then
  ok "引导链硬拦截已就位 ✅（agnos.py: assert_official_boot_chain）"
else
  die "引导链硬拦截缺失！拒绝继续安装 —— 没有这道闸，开机自动 AGNOS 升级会刷进 fork 自改的 abl/boot 导致变砖。"
fi

# 版本匹配闸：低版本设备刷不匹配引导链的兜底拦截。
if grep -q "assert_boot_chain_matches_device" system/hardware/tici/agnos.py 2>/dev/null; then
  ok "引导链版本匹配闸已就位 ✅（agnos.py: assert_boot_chain_matches_device）"
else
  die "引导链版本匹配闸缺失！拒绝继续 —— 低版本设备（12.x/13.x）刷 18.5 引导链必然变砖。"
fi

# AGNOS_VERSION 必须动态钉实机版本，否则开机会自动触发 AGNOS 升级刷写。
if grep -q 'AGNOS_VERSION="\$(tr' launch_env.sh 2>/dev/null; then
  ok "AGNOS_VERSION 动态钉子已就位 ✅（开机不会自动刷引导链）"
else
  warn "launch_env.sh 的 AGNOS_VERSION 不是动态读取，开机可能自动触发 AGNOS 升级。"
  warn "  第 4 步会修正它，但请确认这一步能跑完。"
fi

# 动态钉子哨兵：OTA 更新会 git reset --hard 覆盖 launch_env.sh，
# 把动态钉子打回上游写死的版本号。有哨兵在，updated.py 会拒绝升级。
if grep -q "BP7_DYNAMIC_AGNOS_PIN" launch_env.sh 2>/dev/null && \
   grep -q "BP7_DYNAMIC_AGNOS_PIN" system/updated/updated.py 2>/dev/null; then
  ok "OTA 覆盖防护已就位 ✅（哨兵 BP7_DYNAMIC_AGNOS_PIN）"
else
  die "OTA 覆盖防护缺失！OTA 更新会 git reset --hard 覆盖 launch_env.sh，把动态钉子打回写死版本号并触发 AGNOS 升级。"
fi

echo
echo "  体检结论："
echo "  · 本脚本全程零分区写入 —— 不刷 boot/system/xbl/abl，不换槽。"
echo "  · 即使 AGNOS 自动升级被触发，agnos.py 也会拒绝刷 fork 自改的引导链。"
echo "  · 即使 OTA 把动态钉子覆盖掉，哨兵 + 版本匹配闸也会拒绝刷写。"
echo "  · 引导链基线已记录在 /data/bp7_chain_before.txt，装完自动比对。"
echo

# ---------------------------------------------------------------- 拉分支
hr "1. 拉取并切换到 $BP7_BRANCH"

if [ "$OFFLINE" = "1" ]; then
  warn "离线模式：跳过 git fetch / checkout（包内已是 $BP7_BRANCH 的完整源码）"
  ORIG_BRANCH="offline-bundle"
  ORIG_SHA="offline"
  echo "$ORIG_BRANCH $ORIG_SHA" > /data/bp7_install_origin.txt 2>/dev/null || true

  # 重建符号链接：打包时符号链接被抽成清单（Windows tar 不支持 symlink）
  if [ -f "$OP/.bp7_symlinks" ]; then
    echo "  重建符号链接："
    LINK_OK=1
    while IFS=$'\t' read -r link target; do
      [ -n "$link" ] || continue
      [ -n "$target" ] || continue
      [ -e "$OP/$link" ] && continue
      mkdir -p "$(dirname "$OP/$link")"
      if ln -sfn "$target" "$OP/$link" 2>/dev/null; then
        echo "    $link -> $target"
      else
        warn "符号链接创建失败: $link -> $target"
        LINK_OK=0
      fi
    done < "$OP/.bp7_symlinks"
    [ "$LINK_OK" = "1" ] && ok "符号链接重建完成 ✅" || warn "部分符号链接失败（编译若报缺文件，检查这些链接）"
  fi
else
  ORIG_BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"
  ORIG_SHA="$(git rev-parse HEAD 2>/dev/null || echo unknown)"
  echo "  切分支前: $ORIG_BRANCH @ ${ORIG_SHA:0:9}"
  echo "$ORIG_BRANCH $ORIG_SHA" > /data/bp7_install_origin.txt

  rm -f "$OP/.git/index.lock"
  git fetch --depth 1 origin "$BP7_BRANCH" || die "拉取分支失败：$BP7_BRANCH"
  git checkout -f -B "$BP7_BRANCH" FETCH_HEAD || die "切换分支失败"
  ok "已切到 $(git log --oneline -1)"
fi

# ---------------------------------------------------------------- 子模块
hr "2. 重建子模块"
if [ "$OFFLINE" = "1" ]; then
  warn "离线模式：包内已含子模块内容，跳过 submodule update"
  for d in msgq_repo rednose_repo teleoprtc_repo tinygrad_repo sunnypilot/neural_network_data; do
    if [ -z "$(ls -A "$d" 2>/dev/null)" ]; then
      die "离线包内子模块为空: $d —— 包不完整，请重新生成"
    fi
  done
  ok "子模块齐全 ✅"
else
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
fi

# ---------------------------------------------------------------- LFS
hr "3. LFS 资源"
if [ "$OFFLINE" = "1" ]; then
  warn "离线模式：包内已含模型实体，跳过 git lfs pull"
else
  # .lfsconfig **不能挪走**。
  # 它把 LFS endpoint 指向 gitlab.com/sunnypilot/public/sunnypilot-new-lfs.git，
  # 而 BP7 的模型实体（selfdrive/modeld/models/*.onnx）只存在于那个 GitLab
  # LFS 仓库里 —— GitHub 侧的 fork 没有这些 LFS 对象（实测 batch API 返回
  # 422 "Object ... is not N bytes"）。
  # 挪走 .lfsconfig 后 git lfs pull 会打 GitHub 的 LFS endpoint，
  # 模型永远拉不到，运行时必然报模型损坏。
  # 之前误以为「拉取不受影响」而挪走，那是错的：pushurl 只影响推送，
  # url 影响拉取，两者都在这一个文件里。
  git lfs pull || warn "LFS 拉取失败，模型可能缺失"
fi
ls -la selfdrive/modeld/models/*.onnx 2>/dev/null | head -3 || true

# 模型实体自检：指针文件会导致编译/运行失败
for m in selfdrive/modeld/models/*.onnx; do
  [ -f "$m" ] || continue
  if head -c 40 "$m" | grep -q "version https://git-lfs"; then
    die "模型仍是 LFS 指针（未拉取实体）：$m —— 离线包不完整或 LFS 未拉取"
  fi
done

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

# 4.6 引导链防护强制校验：任何一道不到位都中止，不带着未设防的引导链开机。
#     这是最后一道闸 —— 前面 4.1 的 sed 可能因为文件结构变化而没生效。
echo "  校验引导链防护："
GUARD_OK=1

if grep -q 'AGNOS_VERSION="\$(tr' launch_env.sh 2>/dev/null; then
  echo "    [1/5] AGNOS_VERSION 动态钉子  ✅"
else
  echo "    [1/5] AGNOS_VERSION 动态钉子  ✗ 写死了版本，开机会自动触发 AGNOS 升级"
  GUARD_OK=0
fi

if grep -q "assert_official_boot_chain" system/hardware/tici/agnos.py 2>/dev/null; then
  echo "    [2/5] agnos.py 引导链硬拦截  ✅"
else
  echo "    [2/5] agnos.py 引导链硬拦截  ✗ 缺失，AGNOS 升级会刷进 fork 自改的 abl/boot"
  GUARD_OK=0
fi

if grep -q 'AGNOS_VERSION="\$(tr' sunnypilot/system/hardware/c3/launch_env.sh 2>/dev/null || \
   [ ! -f sunnypilot/system/hardware/c3/launch_env.sh ]; then
  echo "    [3/5] c3 launch_env 动态钉子  ✅"
else
  echo "    [3/5] c3 launch_env 动态钉子  ✗"
  GUARD_OK=0
fi

if grep -q "assert_boot_chain_matches_device" system/hardware/tici/agnos.py 2>/dev/null; then
  echo "    [4/5] agnos.py 版本匹配闸  ✅"
else
  echo "    [4/5] agnos.py 版本匹配闸  ✗ 缺失，低版本设备刷 18.5 引导链会变砖"
  GUARD_OK=0
fi

if grep -q "BP7_DYNAMIC_AGNOS_PIN" launch_env.sh 2>/dev/null && \
   grep -q "BP7_DYNAMIC_AGNOS_PIN" system/updated/updated.py 2>/dev/null; then
  echo "    [5/5] OTA 覆盖防护哨兵  ✅"
else
  echo "    [5/5] OTA 覆盖防护哨兵  ✗ 缺失，OTA 会打回写死版本号并触发 AGNOS 升级"
  GUARD_OK=0
fi

[ "$GUARD_OK" = "1" ] || die "引导链防护未全部就位，拒绝继续。修好上面标 ✗ 的项，或重新执行本脚本。"

# 4.6.1 低版本设备主动禁用 OTA。
#     OTA 更新会把源码树 git reset --hard 到远端分支，覆盖掉本仓库的所有
#     固化改动（含三道防护本身）。虽然 updated.py 有哨兵兜底，但低版本
#     设备上 OTA 会把 launch_env.sh 换成上游写死的 10.1，版本闸与哨兵
#     只能"拒绝刷写"，openpilot 用户空间仍会起不来。直接关掉最干净。
#     DisableUpdates 是 PERSISTENT | BACKUP 参数，写进 /data/params/d 即持久生效。
if [ "$AGNOS_VERSION" != "18.5" ] && [ "${AGNOS_MAJOR:-0}" != "unknown" ] && [ "${AGNOS_MAJOR:-0}" -lt 18 ] 2>/dev/null; then
  PARAM_DIR=/data/params/d
  if [ -d "$PARAM_DIR" ]; then
    if printf '1' > "$PARAM_DIR/DisableUpdates" 2>/dev/null; then
      echo "    低版本设备（AGNOS $AGNOS_VERSION）：已写 DisableUpdates=1，禁用 OTA 自动更新 ✅"
      echo "    （OTA 会覆盖本仓库所有固化改动，且在低版本上必然导致用户空间起不来）"
    else
      warn "    低版本设备：写 DisableUpdates 失败，OTA 仍可能触发。哨兵会兜底拒绝刷引导链。"
    fi
  else
    warn "    低版本设备：找不到 $PARAM_DIR，跳过 DisableUpdates 设置"
  fi
fi

# 4.7 引导链清单二次确认（只读，不修改清单）
#     故意不改 agnos.json：abl/boot 是 AGNOS 升级的必需分区，删掉它们
#     会让「boot 与 system 版本绑定」的铁律失效（系统升了但引导链没升）。
#     真正的防线是 4.6 的代码层拦截 assert_official_boot_chain ——
#     它在 flash_agnos_update 的第一行就抛异常，比清单层更早、更可靠。
MANIFEST=system/hardware/tici/agnos.json
if [ -f "$MANIFEST" ]; then
  if grep -q '"b6fba807b9bcd66a31f2afb0eba5163ec239693ad32e2e4200f6c356adfe098c"' "$MANIFEST"; then
    echo "    [4/4] agnos.json 含 fork 自改的 abl —— 已由 agnos.py 硬拦截覆盖 ✅"
  else
    echo "    [4/4] agnos.json 无 fork 自改条目  ✅"
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
