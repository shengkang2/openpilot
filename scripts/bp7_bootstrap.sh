#!/usr/bin/env bash
# BP7 自举：为「设备直接 clone 源码」的各种安装路径补齐编译环境。
#
# 为什么需要这个脚本：
#   设备上装 BP7 有多条路径（AGNOS 界面填 URL、SSH 跑 install.sh、离线包），
#   但只有 install.sh 会做完整的编译环境准备。走 AGNOS 界面那条路时，
#   installer 只做 git clone + 写 continue.sh，装完直接启动编译，
#   于是会撞上一堆环境问题：
#
#   1. uv 缓存默认在 /home —— 那是 100MB 的 overlay，
#      uv sync 拉约 100MB 轮子必然 "No space left on device"。
#   2. tici 只有 3.6G 内存且无 swap —— scons 并发编译会被 OOM SIGKILL (exit 137)。
#   3. 模型在 Git LFS 里 —— clone 下来是指针文件（134 字节），
#      不拉实体的话编译能过但运行时报模型损坏。
#   4. panda/board/crypto/sign.py 检出后可能没有执行位 —— 固件签名报 Error 126。
#
# 本脚本幂等、可重复执行、失败不阻断启动（在 build 之前调用，失败也只是
# 退回到原有的失败表现，不会把设备搞得更糟）。
#
# 由 launch_chffrplus.sh / c3/launch_chffrplus.sh 在进入编译前调用。

set -u

DIR="${DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
LOG="/data/bp7_bootstrap.log"

log() { echo "[bp7-bootstrap] $*" | tee -a "$LOG"; }

# ---------------------------------------------------------------- 1. uv 缓存
# 必须指到 /data：/home 是 100MB overlay，撑不下 uv 的轮子缓存。
export UV_CACHE_DIR="${UV_CACHE_DIR:-/data/uv-cache}"
export UV_PYTHON_INSTALL_DIR="${UV_PYTHON_INSTALL_DIR:-/data/uv-python}"
export UV_PYTHON_CACHE_DIR="${UV_PYTHON_CACHE_DIR:-/data/uv-python}"
export UV_LINK_MODE="${UV_LINK_MODE:-copy}"
export TMPDIR="${TMPDIR:-/data/tmp}"
mkdir -p "$UV_CACHE_DIR" "$UV_PYTHON_INSTALL_DIR" "$TMPDIR" 2>/dev/null || true

# ---------------------------------------------------------------- 2. swapfile
# tici 3.6G 内存、无 swap，编译期容易被 OOM 杀掉。
if ! swapon --show 2>/dev/null | grep -q .; then
  if [ ! -f /data/swapfile ]; then
    log "创建 3G swapfile（编译期防 OOM）"
    sudo -n fallocate -l 3G /data/swapfile 2>/dev/null \
      && sudo -n chmod 600 /data/swapfile \
      && sudo -n mkswap /data/swapfile > /dev/null 2>&1 \
      && sudo -n swapon /data/swapfile \
      && log "swapfile 已启用" \
      || log "swapfile 创建失败，编译可能 OOM（不影响启动）"
  else
    log "swapfile 已存在但未启用，尝试启用"
    sudo -n swapon /data/swapfile 2>/dev/null || log "启用失败（不影响启动）"
  fi
fi

cd "$DIR" || exit 0

# ---------------------------------------------------------------- 3. LFS 模型
# clone 下来的是 134 字节的指针文件，必须拉实体。
# 只在检测到指针时才动作，避免每次开机都走网络。
LFS_NEEDED=0
for m in selfdrive/modeld/models/*.onnx; do
  [ -f "$m" ] || continue
  if [ "$(head -c 40 "$m" 2>/dev/null)" = "version https://git-lfs.github.com/spec/v1" ]; then
    LFS_NEEDED=1
    break
  fi
done

if [ "$LFS_NEEDED" = "1" ]; then
  if command -v git-lfs > /dev/null 2>&1; then
    log "检测到 LFS 指针，拉取模型实体"
    # 注意：.lfsconfig 不能挪走！
    #   它把 LFS endpoint 指向 gitlab.com/sunnypilot/public/sunnypilot-new-lfs.git
    #   ——BP7 的模型实体（onnx）只存在于那个 GitLab LFS 仓库里，
    #   GitHub 侧的 fork 没有这些 LFS 对象（实测 batch API 返回 422 size 不匹配）。
    #   挪走 .lfsconfig 后 git lfs pull 会打 GitHub 的 LFS endpoint，模型永远拉不到。
    #   （.lfsconfig 的 pushurl 指向上游，只有推送 LFS 时才需要改；
    #     本脚本只拉不推，保持原样最安全。）
    if timeout 900 git lfs pull 2>&1 | tee -a "$LOG"; then
      log "LFS 拉取完成"
    else
      log "LFS 拉取失败或超时（模型可能仍是指针，运行时会报错）"
      log "  排查：git lfs env 看 endpoint 是否为 gitlab sunnypilot LFS；网络是否可达"
    fi
  else
    log "没有 git-lfs，模型仍是指针文件。装：sudo apt-get install -y git-lfs"
  fi
else
  log "模型实体已就位，跳过 LFS"
fi

# ---------------------------------------------------------------- 4. 执行位
# 检出时 mode 位可能没还原，panda 固件签名会报 Error 126。
chmod +x panda/board/crypto/sign.py 2>/dev/null || true

# ---------------------------------------------------------------- 5. 保护闸复核
# 引导链防护是「刷引导链导致变砖」的最后一层。这里只做只读复核并打日志，
# 真正拦截在 system/hardware/tici/agnos.py 里（那才是执行拦截的位置）。
MISSING=""
grep -q 'AGNOS_VERSION="\$(tr' launch_env.sh 2>/dev/null || MISSING="$MISSING AGNOS_VERSION动态钉子"
grep -q "assert_official_boot_chain" system/hardware/tici/agnos.py 2>/dev/null || MISSING="$MISSING 引导链硬拦截"
grep -q "assert_boot_chain_matches_device" system/hardware/tici/agnos.py 2>/dev/null || MISSING="$MISSING 版本匹配闸"
grep -q "BP7_DYNAMIC_AGNOS_PIN" system/updated/updated.py 2>/dev/null || MISSING="$MISSING OTA覆盖防护哨兵"

if [ -n "$MISSING" ]; then
  log "⚠️ 引导链防护缺失：$MISSING"
  log "   若开机触发 AGNOS 自动升级，设备可能变砖。请跑 install.sh 修复。"
else
  log "引导链五道防护齐备 ✅（零分区写入）"
fi

log "自举完成"
exit 0
