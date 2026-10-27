#!/usr/bin/env bash

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null && pwd )"

source "$DIR/launch_env.sh"

# BluePilot: set boot and logo images (non-interactive, safe to call repeatedly)
"$DIR/scripts/boot_logo.sh" --headless --update --force --quiet

function agnos_init {
  # TODO: move this to agnos
  sudo rm -f /data/etc/NetworkManager/system-connections/*.nmmeta
  rm -f /data/scons_cache/config.lock

  # set success flag for current boot slot
  sudo abctl --set_success

  # TODO: do this without udev in AGNOS
  # udev does this, but sometimes we startup faster
  sudo chgrp gpu /dev/adsprpc-smd /dev/ion /dev/kgsl-3d0
  sudo chmod 660 /dev/adsprpc-smd /dev/ion /dev/kgsl-3d0

  # Check if AGNOS update is required
  if [ $(< /VERSION) != "$AGNOS_VERSION" ]; then
    # BluePilot: 三道额外闸门，拦住「低版本设备刷成不匹配引导链」这条变砖路径。
    #
    # 变砖机理：boot 与 system 是版本绑定的。若把与当前 bootloader 不匹配的
    # AGNOS 整套刷进去（xbl/abl/boot 全换），设备 bootloader 拒绝加载
    # → Unsupported firmware detected → SSH 与网络全断，只能 QDL 全刷救砖。
    # 低版本设备（12.x / 13.x）刷 18.5 的引导链必然踩中，历史已变砖两次。

    # 闸门 1：动态钉子哨兵。launch_env.sh 的 AGNOS_VERSION 是运行时读
    # /VERSION 的，理论上永远与实机相等。走到这个分支说明环境异常，
    # 此时任何刷写都是赌博 —— 直接跳过。
    if [ "${BP7_DYNAMIC_AGNOS_PIN:-}" = "1" ]; then
      echo "BP7: AGNOS_VERSION 动态钉子与实机不一致，疑似环境异常，跳过 AGNOS 自动升级" >&2
      return 0
    fi

    # 闸门 2：哨兵版本号。读不到 /VERSION 时 launch_env.sh 会设这个值，
    # 说明无法确定目标版本，不刷。
    if [ "$AGNOS_VERSION" = "__BP7_NO_VERSION__" ]; then
      echo "BP7: 无法确定目标 AGNOS 版本，跳过 AGNOS 自动升级" >&2
      return 0
    fi

    # 闸门 3：禁止降级。目标版本比实机旧（12.x 刷 10.1 之类）说明拉到了
    # 上游写死的旧版本号，刷进去一定不匹配。用 sort -V 做版本比较。
    if printf '%s\n%s\n' "$AGNOS_VERSION" "$(< /VERSION)" | sort -V -C 2>/dev/null; then
      echo "BP7: 目标 AGNOS 版本 ($AGNOS_VERSION) 不高于实机 ($(< /VERSION))，拒绝降级刷写" >&2
      return 0
    fi

    AGNOS_PY="$DIR/system/hardware/tici/agnos.py"
    MANIFEST="$DIR/system/hardware/tici/agnos.json"
    if $AGNOS_PY --verify $MANIFEST; then
      sudo reboot
    fi
    $DIR/system/hardware/tici/updater $AGNOS_PY $MANIFEST
  fi
}

function fix_egl_adreno {
  # BluePilot: comma's on-screen URL installer points the GPU EGL/GLES libs at the Adreno
  # drivers. ford-op/BluePilot installs by git clone (private repo), which skips that
  # installer, so ldconfig's higher-versioned glvnd/Mesa libs win and magic.service (the
  # AGNOS display server) fails eglGetDisplay -> no UI. Re-point them like the installer does.
  local lib=/usr/lib/aarch64-linux-gnu
  if [ "$(readlink $lib/libEGL.so.1)" != "libEGL.so.1.0.0" ] || \
     [ "$(readlink $lib/libGLESv2.so.2)" != "libGLESv2.so.2.0.0" ]; then
    sudo mount -o remount,rw /
    sudo ln -sf libEGL.so.1.0.0 "$lib/libEGL.so.1"
    sudo ln -sf libGLESv2.so.2.0.0 "$lib/libGLESv2.so.2"
    sudo mount -o remount,ro /
    sudo systemctl restart magic.service 2>/dev/null || true
  fi
}

function launch {
  # Remove orphaned git lock if it exists on boot
  [ -f "$DIR/.git/index.lock" ] && rm -f $DIR/.git/index.lock

  # Check to see if there's a valid overlay-based update available. Conditions
  # are as follows:
  #
  # 1. The DIR init file has to exist, with a newer modtime than anything in
  #    the DIR Git repo. This checks for local development work or the user
  #    switching branches/forks, which should not be overwritten.
  # 2. The FINALIZED consistent file has to exist, indicating there's an update
  #    that completed successfully and synced to disk.

  if [ -f "${DIR}/.overlay_init" ]; then
    find ${DIR}/.git -newer ${DIR}/.overlay_init | grep -q '.' 2> /dev/null
    if [ $? -eq 0 ]; then
      echo "${DIR} has been modified, skipping overlay update installation"
    else
      if [ -f "${STAGING_ROOT}/finalized/.overlay_consistent" ]; then
        if [ ! -d /data/safe_staging/old_openpilot ]; then
          echo "Valid overlay update found, installing"
          LAUNCHER_LOCATION="${BASH_SOURCE[0]}"

          mv $DIR /data/safe_staging/old_openpilot
          mv "${STAGING_ROOT}/finalized" $DIR
          cd $DIR

          echo "Restarting launch script ${LAUNCHER_LOCATION}"
          unset AGNOS_VERSION
          exec "${LAUNCHER_LOCATION}"
        else
          echo "openpilot backup found, not updating"
          # TODO: restore backup? This means the updater didn't start after swapping
        fi
      fi
    fi
  fi

  # handle pythonpath
  ln -sfn $(pwd) /data/pythonpath
  # BluePilot: 保留 /data/pylibs。AGNOS 18.x 的 /usr/local/venv 里 capnproto 是半装状态
  # （dist-info 在、install/ 目录缺），而 /usr/local 只读没法重装，只能把依赖轮子
  # 离线装到 /data/pylibs。这行 export 会覆盖 launch_env.sh 里的设置，所以两处都要带。
  export PYTHONPATH="/data/pylibs:$PWD"

  # jetlink: the vendored package links into the tree's root so `import jetlink`
  # finds it, as this tree's own packages are found by name. Rebuilt every boot
  # because a symlink is the one thing a git checkout does not guarantee
  ln -sfn "$PWD/jetlink_repo/jetlink" "$PWD/jetlink"

  # hardware specific init
  if [ -f /AGNOS ]; then
    agnos_init
    fix_egl_adreno
    # C3: 共享 USB hub 上先压住 LTE 模组，等 pandad 连上 panda 再放行
    python3 -c "from openpilot.system.hardware.tici.modem_usb import defer_modem_usb; defer_modem_usb()" || true
  fi

  # write tmux scrollback to a file
  tmux capture-pane -pq -S-1000 > /tmp/launch_log

  # start manager
  cd system/manager
  if [ ! -f $DIR/prebuilt ]; then
    # BluePilot: 自举 —— 补齐 uv 缓存路径、swapfile、LFS 模型实体、sign.py 执行位。
    # 走 AGNOS 界面「填 URL 安装」这条路时不会执行 install.sh，编译环境全缺，
    # 结果是 uv sync 撑爆 /home、scons 被 OOM 杀掉、模型是指针文件。
    # 这个脚本幂等且失败不阻断启动。
    [ -f "$DIR/scripts/bp7_bootstrap.sh" ] && bash "$DIR/scripts/bp7_bootstrap.sh" || true
    # BluePilot: verbose build UI (progress + live scons line + failure log). Falls back to the
    # stock build if bp_build.py can't start, so a UI bug can't leave the device unable to build.
    ./bp_build.py || ./build.py
  fi
  ./manager.py

  # if broken, keep on screen error
  while true; do sleep 1; done
}

launch
