#!/usr/bin/env bash

export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export VECLIB_MAXIMUM_THREADS=1

# models get lower priority than ui
# - ui is ~5ms
# - modeld is 20ms
# - DM is 10ms
# in order to run ui at 60fps (16.67ms), we need to allow
# it to preempt the model workloads. we have enough
# headroom for this until ui is moved to the CPU.
export QCOM_PRIORITY=12

if [ -z "$AGNOS_VERSION" ]; then
  # BluePilot: AGNOS_VERSION 必须钉成「实机当前版本」，不能写死。
  # 写死 18.5 的后果：设备上是 18.4 时，launch_chffrplus.sh 的 agnos_init 会发现
  # /VERSION != AGNOS_VERSION，自动跑 agnos.py 拉整套清单重刷 —— 而 bp7 自带的
  # agnos.json 里 abl/boot 都是 fork 自改的（abl=b6fba807、boot=19ff57b6），
  # 刷进去 bootloader 校验失败，设备直接变砖（Unsupported firmware detected）。
  # 历史上已经因此变砖两次，这里改成运行时读 /VERSION，装到任何 AGNOS 版本都安全。
  #
  # 低版本设备（12.x / 13.x）尤其关键：这类设备的 bootloader 与 18.5 的
  # rootfs 模块不兼容，刷进去必砖。所以宁可读不到 /VERSION 也不猜版本。
  if [ -r /VERSION ]; then
    export AGNOS_VERSION="$(tr -d '[:space:]' < /VERSION)"
  else
    # 读不到 /VERSION：不能回落任何具体版本号。
    # 用一个绝不可能等于真实 /VERSION 的哨兵值，让 agnos_init 的版本比较
    # 判定为「需要升级」并进入升级分支 —— 但那条分支有 agnos.py 的硬拦截，
    # 会拒绝刷 fork 自改的引导链。宁可起不来，也绝不能刷坏 bootloader。
    export AGNOS_VERSION="__BP7_NO_VERSION__"
    echo "BP7: 读不到 /VERSION，禁用 AGNOS 自动升级（agnos.py 硬拦截兜底）" >&2
  fi
fi

# BluePilot: 哨兵标记 —— 表示本文件的 AGNOS_VERSION 是动态读取的。
# system/updated/updated.py 的 handle_agnos_update() 会拿 launch_env.sh 里的
# AGNOS_VERSION 跟实机 /VERSION 比。OTA 更新会把整个源码树 git reset --hard
# 到远端分支，覆盖掉这份动态钉子，退回到上游写死的版本号 —— 那时
# handle_agnos_update 会认为「版本不符」而启动 AGNOS 升级刷写。
# 这个标记让 updated.py 能识别出「版本不符只是因为钉子被覆盖」，
# 从而拒绝升级，而不是真的去刷引导链。
export BP7_DYNAMIC_AGNOS_PIN="1"

export STAGING_ROOT="/data/safe_staging"

# BluePilot: connect backend (BPConnectBackend). openpilot already reads API_HOST / ATHENA_HOST
# everywhere it talks to the backend (common/api/comma_connect.py, system/athena/athenad.py,
# registration and the uploader), so setting them here redirects all of it with no other code
# changes. Takes effect on reboot.
#   0 / unset = Comma Connect (stock defaults)
#   1         = Konik Stable (api.konik.ai / athena.konik.ai)
#   2         = Offline Mode (bogus hosts — uploads can never succeed)
# Legacy: migrate BPUseKonik=1 -> BPConnectBackend=1 when the new param file is missing.
BP_CONNECT_BACKEND="$(cat /data/params/d/BPConnectBackend 2>/dev/null)"
if [ -z "$BP_CONNECT_BACKEND" ] && [ "$(cat /data/params/d/BPUseKonik 2>/dev/null)" = "1" ]; then
  BP_CONNECT_BACKEND="1"
  mkdir -p /data/params/d
  printf '%s' "1" > /data/params/d/BPConnectBackend
fi
if [ "$BP_CONNECT_BACKEND" = "1" ]; then
  export API_HOST="https://api.konik.ai"
  export ATHENA_HOST="wss://athena.konik.ai"
elif [ "$BP_CONNECT_BACKEND" = "2" ]; then
  # RFC 2606 .invalid never resolves, so offline mode can never egress
  export API_HOST="https://api.invalid"
  export ATHENA_HOST="wss://athena.invalid"
fi
# End BluePilot
