#!/usr/bin/env bash

export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export VECLIB_MAXIMUM_THREADS=1

if [ -z "$AGNOS_VERSION" ]; then
  # BluePilot: 这份 launch_env.sh 是 c3 硬件分支的，原文写死 AGNOS_VERSION="12.8"。
  # comma three (tici) 实际跑的是 AGNOS 18.x，于是开机 agnos_init 判定版本不符，
  # 自动去刷 c3/agnos.json —— 那份清单带完整引导链，刷完 bootloader 拒绝加载 → 变砖。
  # 这是历史上最容易漏掉、也最致命的一处：根目录 launch_env.sh 改了，这里没改照样砖。
  # 改成运行时读实机 /VERSION，任何 AGNOS 版本装都不会触发自动升级刷写。
  if [ -r /VERSION ]; then
    export AGNOS_VERSION="$(tr -d '[:space:]' < /VERSION)"
  else
    # 读不到 /VERSION 时不猜版本号：用绝不可能匹配的哨兵值，
    # 让版本比较走升级分支，由 agnos.py 的硬拦截兜底拒绝刷引导链。
    export AGNOS_VERSION="__BP7_NO_VERSION__"
    echo "BP7: 读不到 /VERSION，禁用 AGNOS 自动升级（agnos.py 硬拦截兜底）" >&2
  fi
fi

# BluePilot: 哨兵标记，见根目录 launch_env.sh 的同名说明。
export BP7_DYNAMIC_AGNOS_PIN="1"

export STAGING_ROOT="/data/safe_staging"
