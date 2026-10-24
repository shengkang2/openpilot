#!/usr/bin/env bash
# 生成 bp7 离线安装包（设备访问不了 GitHub 时用）
#
# 用法（在仓库根目录，PC 上执行）：
#   bash tools/make_bundle.sh [输出目录]
#
# 产出：bp7-offline.tar.gz（约 500MB，含子模块 + LFS 模型实体）
#
# 传到设备后：
#   scp bp7-offline.tar.gz comma@<设备IP>:/data/
#   ssh comma@<设备IP>
#   sudo -n rm -rf /data/openpilot && sudo -n mkdir -p /data/openpilot
#   tar -xzf /data/bp7-offline.tar.gz -C /data/openpilot
#   bash /data/openpilot/install.sh
#
# 设计要点：
#   - 符号链接单独存成清单（.bp7_symlinks），由设备端 install.sh 重建。
#     Windows 的 tar 不支持 symlink，Linux/macOS 上也能正确处理。
#   - 包里不带 .git（省体积）。install.sh 识别 .bp7_offline 标记后，
#     跳过 git fetch / submodule / LFS，直接用包内完整源码。

set -euo pipefail

OUT_DIR="${1:-$(pwd)/dist}"
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
SHA="$(git rev-parse --short HEAD)"
STAGE="$OUT_DIR/bp7-offline"

echo "bp7 离线包生成器  分支=$BRANCH @ $SHA"

for c in git tar gzip; do
  command -v "$c" > /dev/null 2>&1 || { echo "缺少 $c"; exit 1; }
done

# ---------------------------------------------------------------- 1 子模块
echo "[1/5] 检查子模块"
git submodule update --init --recursive > /dev/null 2>&1 || \
  echo "  ! 子模块初始化有失败，缺失部分会导致编译不过"
for d in msgq_repo rednose_repo teleoprtc_repo tinygrad_repo sunnypilot/neural_network_data; do
  [ -z "$(ls -A "$d" 2>/dev/null)" ] && echo "  ! 子模块为空: $d"
done

# ---------------------------------------------------------------- 2 LFS
echo "[2/5] 检查 LFS 模型实体"
MISSING=0
for m in selfdrive/modeld/models/*.onnx; do
  [ -f "$m" ] || continue
  if head -c 40 "$m" | grep -q "version https://git-lfs"; then
    echo "  ! 仍是 LFS 指针: $m"; MISSING=1
  fi
done
[ "$MISSING" = "0" ] && echo "  模型实体齐全 ✅"
if [ "$MISSING" = "1" ]; then
  echo "  尝试 git lfs pull ..."
  [ -f .lfsconfig ] && mv -f .lfsconfig .lfsconfig.bak
  git lfs pull || echo "  ! LFS 拉取失败，请检查网络后重试"
fi

# ---------------------------------------------------------------- 3 复制工作树
echo "[3/5] 复制工作树到 $STAGE"
rm -rf "$STAGE"
mkdir -p "$STAGE"

# 不用 git archive：它不包含 LFS 实体，也不含子模块内容，
# 而且 Windows 上 tar 解 symlink 会失败。改为直接复制工作树。
# 排除 .git 与构建产物。
tar --exclude=.git --exclude=prebuilt --exclude=dist --exclude='*.pyc' \
    --exclude=__pycache__ --exclude=.venv \
    -cf - . 2>/dev/null | tar -xf - -C "$STAGE" || {
  echo "复制失败（可能含 symlink）。改用逐目录复制。"
  rm -rf "$STAGE"; mkdir -p "$STAGE"
  for item in * .[^.]*; do
    [ "$item" = "." ] && continue
    [ "$item" = ".." ] && continue
    [ "$item" = ".git" ] && continue
    cp -r "$item" "$STAGE/" 2>/dev/null || true
  done
}

# 子模块：上面 tar 拷贝的是子模块工作树（因为它们是真实目录），
# 但要确认内容非空
for d in msgq_repo rednose_repo teleoprtc_repo tinygrad_repo sunnypilot/neural_network_data; do
  if [ -z "$(ls -A "$STAGE/$d" 2>/dev/null)" ]; then
    echo "  ! 打包后子模块为空: $d —— 单独拷贝"
    rm -rf "$STAGE/$d"; mkdir -p "$STAGE/$d"
    (cd "$d" && tar --exclude=.git -cf - . 2>/dev/null) | tar -xf - -C "$STAGE/$d" 2>/dev/null || \
      cp -r "$d/." "$STAGE/$d/" 2>/dev/null || true
  fi
done

# ---------------------------------------------------------------- 4 符号链接清单
echo "[4/5] 提取符号链接清单"
: > "$STAGE/.bp7_symlinks"
git ls-files -s | awk '$1=="120000"{print $4}' | while read -r link; do
  target="$(cat "$link" 2>/dev/null || true)"
  [ -z "$target" ] && continue
  printf '%s\t%s\n' "$link" "$target" >> "$STAGE/.bp7_symlinks"
done
echo "  符号链接 $(wc -l < "$STAGE/.bp7_symlinks") 个（设备端会重建）"

# 打包时把符号链接位置从工作树里移除（否则设备上会是文本文件）
while IFS=$'\t' read -r link target; do
  [ -n "$link" ] || continue
  rm -f "$STAGE/$link"
done < "$STAGE/.bp7_symlinks"

# 离线标记
echo "BP7_OFFLINE_BUNDLE=1" > "$STAGE/.bp7_offline"

# ---------------------------------------------------------------- 5 说明 + 压缩
cat > "$STAGE/离线安装说明.txt" <<EOF
bp7 离线安装包
分支: $BRANCH
提交: $SHA
生成时间: $(date '+%Y-%m-%d %H:%M:%S')

设备上执行（/data/openpilot 是 comma 服务的固定工作目录，必须展开到这里）：
  sudo -n rm -rf /data/openpilot && sudo -n mkdir -p /data/openpilot
  tar -xzf /data/bp7-offline.tar.gz -C /data/openpilot
  bash /data/openpilot/install.sh

看日志： tail -f /data/bp7_install.log
安全：全程零分区写入，不刷 boot/system/xbl/abl，不换槽。
EOF

echo "[5/5] 压缩"
rm -f "$OUT_DIR/bp7-offline.tar.gz"
tar -czf "$OUT_DIR/bp7-offline.tar.gz" -C "$STAGE" . 2>/dev/null || \
  tar -czf "$OUT_DIR/bp7-offline.tar.gz" -C "$STAGE" *

SIZE="$(du -h "$OUT_DIR/bp7-offline.tar.gz" | cut -f1)"
echo
echo "完成: $OUT_DIR/bp7-offline.tar.gz ($SIZE)"
echo
echo "传设备： scp $OUT_DIR/bp7-offline.tar.gz comma@<设备IP>:/data/"
echo "设备上： tar -xzf /data/bp7-offline.tar.gz -C /data/openpilot && bash /data/openpilot/install.sh"
