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
  if [ -r /VERSION ]; then
    export AGNOS_VERSION="$(tr -d '[:space:]' < /VERSION)"
  else
    export AGNOS_VERSION="18.5"
  fi
fi

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
