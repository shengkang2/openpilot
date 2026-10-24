# bp7 — BluePilot 7.0（comma three / tici 中文优化版）

在 bluepilot BPVERSION 7.0.0 基础上做的中文与稳定性优化版本，面向 **comma three (tici)**。

---

## 一、链接安装

### 方式 A：设备上一条命令（推荐）

在 comma three 上通过 SSH / ADB shell 执行：

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/shengkang2/openpilot/bp7.020261020/install.sh)
```

脚本会依次完成：环境自检 → 切分支 → 重建子模块 → 拉 LFS → 源码级适配 →
依赖准备 → 编译 → 重启服务 → 引导链比对。

### 方式 B：下载源码包

Release 直链：

```
https://github.com/shengkang2/openpilot/releases/download/bp7-release/<tag>/bp7-prebuilt-src.tar.gz
```

解包到 `/data/openpilot` 后跑 `bash install.sh` 完成编译。

### 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `BP7_BRANCH` | `bp7.020261020` | 要安装的分支 |
| `BP7_REPO` | `https://github.com/shengkang2/openpilot.git` | 仓库地址 |
| `BP7_JOBS` | `2` | 编译并发（tici 只有 3.6G 内存） |
| `BP7_SKIP_BUILD` | `0` | 设为 `1` 只做源码适配不编译 |
| `OP` | `/data/openpilot` | openpilot 根目录 |

---

## 二、安全设计：全程零分区写入

**这是本分支最重要的约束。** 历史上所有变砖都与刷引导链有关，所有成功案例都是零分区写入。

| 铁律 | 说明 |
|---|---|
| 不碰引导链 | `xbl / xbl_config / abl / aop / devcfg` 五个分区全程只读，脚本装完自动比对 sha256 |
| 不换槽 | 不执行 `abctl --set_active`，槽位由你决定 |
| 不刷 boot/system | 不执行 `agnos.py`，不碰任何镜像 |
| AGNOS_VERSION 动态钉 | 两处 `launch_env.sh` 都在运行时读 `/VERSION`，装到任何 AGNOS 版本都不触发开机自动升级 |
| **代码层硬拦截** | `agnos.py` 在 `flash_agnos_update()` 第一行就拒绝 fork 自改的 abl/boot，抛异常中止 |
| **装前体检** | `install.sh` 第 0.6 步只读体检，输出设备型号/槽位/AGNOS 版本/引导链哈希 |
| **装后自检** | 第 4.6 步校验三道防护全部就位，任何一道缺失直接中止安装 |
| 失败可回滚 | 编译失败不影响系统启动，`git checkout` 回原分支重编即可 |

### 五道防护：为什么装 bp7 不会刷坏引导链

设备是 comma three，bp7 是 AGNOS 18.5 底包，版本不一定对得上。
真正会变砖的路径只有一条：**开机时 `agnos_init` 发现 `/VERSION != AGNOS_VERSION`
→ 自动跑 `agnos.py` 拉整套清单重刷 → 刷进不匹配的引导链 → bootloader 拒绝加载。**

针对这一条，本分支设了五道独立的闸：

**第一道 · 消除触发条件** —— 两处 `launch_env.sh` 的 `AGNOS_VERSION` 改成
运行时读 `/VERSION`。这样 `/VERSION != AGNOS_VERSION` 永远为假，
开机根本不会走进刷引导链的分支。

**第二道 · 代码层硬拦截** —— 万一有人手动跑 `agnos.py`（或 `system/updated/updated.py`
的 `handle_agnos_update()` 触发），`agnos.py` 在 `flash_agnos_update()` 的**第一行**
就调用 `assert_official_boot_chain()`，检测到清单里有 fork 自改的
abl（`b6fba807…`）或 boot（`19ff57b6…`）就抛异常中止，
**在任何写操作之前**（包括 `abctl --set_unbootable`），分区一个字节都不会动。

**第三道 · 版本匹配闸** —— `assert_boot_chain_matches_device()` 拦「官方但版本
不匹配」的引导链。bp7 的 `agnos.json` 是 AGNOS 18.5 的整套镜像；刷到 12.x / 13.x
设备上，18.5 的 xbl/abl 与该设备的 bootloader 世代不匹配，bootloader 直接拒绝加载。
这道闸比对实机 `/VERSION` 与清单对应的 AGNOS 版本，不一致就中止整份清单。

**第四道 · OTA 覆盖防护** —— openpilot 自带的 OTA 会把源码树
`git reset --hard` 到远端分支，**覆盖掉上面第一道闸的动态钉子**，
把 `AGNOS_VERSION` 打回上游写死的值（上游 master 是 `"10.1"`）。
`launch_env.sh` 导出哨兵 `BP7_DYNAMIC_AGNOS_PIN=1`，
`system/updated/updated.py` 的 `handle_agnos_update()` 检测到哨兵就**拒绝升级** ——
版本不符只是因为钉子被覆盖，不是真的需要刷机。

**第五道 · 装前体检 + 装后自检** —— `install.sh` 第 0.6 步只读输出设备状态，
低版本设备直接拦截；第 4.6 步校验前四道防护确实在源码里生效，任何一道缺失就
`die` 中止，**绝不允许带着未设防的引导链去开机**。

### 低版本设备（12.x / 13.x）的特别说明

**结论：不会砖，但也装不上。**

不会砖的理由：变砖只有「刷引导链」这一条路径，而上面五道闸把它的所有入口
（开机 `agnos_init`、手动 `agnos.py`、OTA `handle_agnos_update`）都封死了，
而且 `install.sh` 全程零分区写入。

装不上的理由：bp7 需要 AGNOS 18.5 底包自带的依赖 ——
**acados / capnproto / eigen 头文件与 Python 3.12.13**。
12.x / 13.x 的系统里没有这套东西，`uv sync` 也装不出 acados 的原生库，
编译必然失败。历史记录确认过：bp7 在 AGNOS 16 上就「无解」。

所以 `install.sh` 在低版本设备上会**明确拦截并说明原因**：

```
⚠️  检测到低版本设备：AGNOS 12.8（低于 bp7 底包 18.5）
  预期结果：编译大概率失败 / 即使编过用户空间也可能起不来
  安全保证：全程零分区写入，不会变砖，可回滚
确认要继续请设 BP7_FORCE_LOW_AGNOS=1
```

另外低版本设备上 `install.sh` 会自动写 `DisableUpdates=1`（持久化参数），
把 OTA 关掉 —— OTA 会覆盖本仓库的所有固化改动，且在低版本上必然导致用户空间起不来。

**正确做法：先用官方途径把设备升到 AGNOS 18.5，再装 bp7。**
升 AGNOS 本身有刷引导链的风险，但那是官方同版本的引导链，不会变砖。

### 为什么 AGNOS_VERSION 必须动态

bp7 自带的 `system/hardware/tici/agnos.json` 里 `abl=b6fba807`、`boot=19ff57b6`
都是 fork 自改的，不是官方镜像。而 `sunnypilot/system/hardware/c3/launch_env.sh`
原本写死 `AGNOS_VERSION="12.8"`，根目录 `launch_env.sh` 写死 `"18.5"`。

两者叠加的后果：设备上是 AGNOS 18.x，开机时 `agnos_init` 发现版本不符 →
自动跑 `agnos.py` 拉整套清单重刷 → bootloader 校验失败 →
`Unsupported firmware detected` / `Reflash the firmware` → **SSH 与网络全断，只能 QDL 全刷救砖**。

历史上已经因此变砖两次。本分支从五个层面消除了它：动态钉子消除触发条件，
代码层拦截兜底，版本匹配闸挡住跨代刷写，OTA 哨兵挡住钉子被覆盖，
install.sh 自检防止带着隐患开机。

### 关于版本不匹配（这不会变砖）

bp7 按 18.5 编译，设备底包如果是别的版本，openpilot 用户空间可能起不来。
但这跟引导链无关 —— 引导链零改动，可以回滚：

```bash
cd /data/openpilot && git checkout -f <原分支> && bash install.sh
```

**boot 与 system 必须同版本**这条铁律依然有效，但那只在需要**刷机**时起作用。
`install.sh` 不刷机，所以不涉及。

---

## 三、本分支做了什么

### 3.1 关闭「未注册到 comma.ai」红条警报

`system/athena/registration.py`：`Offroad_UnregisteredHardware` 恒置 `False`。
**只关提示，注册逻辑一行没动**（`dongle_id` 照样尝试注册并写入参数）。

### 3.2 补 params 白名单

`common/params_keys.h` 补 `Offroad_AcceleratorUnavailable`。

bp7 的 `system/hardware/hardwared.py:331` 会写这个 key，
`selfdrive/selfdrived/alerts_offroad.json:58` 也定义了它，
但白名单漏注册（旁边 14 个 `Offroad_*` 都在）。
`Params.get()` 走 C++ `check_key()` 严格校验，直接抛异常把 UI 打死，**每秒崩一次**。

### 3.3 中文化

| 文件 | 改动 |
|---|---|
| `selfdrive/assets/fonts/Zh-*.fnt/.png` | 80px NotoSansSC 位图字库，841 字形 / 728 汉字 |
| `system/ui/lib/application.py` | `FontWeight` 增加 `ZH_*` 四字重，`font_fallback` 按原字重映射 |
| `selfdrive/ui/sunnypilot/layouts/settings/settings.py` | `NavButton._render` 两处补 `tr()` |
| `system/ui/widgets/list_view.py` | 框架层：`ListItem.title/description`、`ButtonAction.text`、`TextAction.text`、`MultipleButtonAction` 统一包 `tr()` |
| `bluepilot/ui/widgets/network_card.py` | `"NETWORK"` 硬编码 → `tr()` |
| `bluepilot/ui/widgets/metric_card.py` | CPU/GPU/MEMORY/VEHICLE/CONNECT/SUNNYLINK 标签统一翻译 |
| `bluepilot/ui/widgets/drive_stats.py` | ALL TIME / PAST WEEK / Drives / Hours / KM / Miles 包 `tr()` |
| `bluepilot/ui/layouts/jetlink.py` | 12 处动态文案改 `tr("模板 {}").format(值)` |
| `bluepilot/ui/jetlink_ui.py` | 6 处状态说明包 `tr()` |
| `selfdrive/ui/translations/app_zh-CHS.po` | 860 条词条 |

#### 字体为什么是 80px

Inter 图集基准 200px，UI 只用 40~85px（**缩小** → 清晰）；
原 48px 中文字库在 UI 里被放大到 55~75px，**非整数倍放大必然模糊**。

BMFont 位图字库的 `info size` 要接近 UI 实际最大渲染尺寸，**宁大勿小**。
改 80px 后最大场景 75.4px = 0.94x（缩小，清晰）。图集 2048×2669~2754，在 4096 安全线内。

#### 字库生成

```bash
python3 tools/gen_cn_font.py --size 80
```

需要 `Pillow` + `fontTools` + `NotoSansSC`（设备 `/usr/share/fonts`，PC `C:\Windows\Fonts`）。

`collect_chars()` **全量扫描 po 文件**（不区分 msgid/msgstr、不过滤复数形式）。
按 `msgstr ` 前缀精细解析很容易漏掉 `msgstr[0] "{} 分钟前"` 里的「钟」。

### 3.4 补回 Jetlink 面板

bluepilot 上游把 `JetlinkLayout` 只注册进原版 `selfdrive/ui/layouts/settings/settings.py`，
但 sunnypilot 覆盖版的 `_panels` 字典漏了这一项。
`layers/main.py` 在 `gui_app.sunnypilot_ui()` 为真时用 `SettingsLayoutSP`，所以菜单里永远看不到 Jetlink。

`PanelType.JETLINK = 6` 枚举一直存在，`icons/jetlink.png` 也在，纯粹是面板注册漏了。

### 3.5 Jetlink 握手顺序修复

`jetlink_repo/jetlink/openpilot/provision.py`：改为
`open_link → wait_for_jetson → provision()`（`provision()` 内含 `hello()`）。

原顺序先下载模型再开链路，而 `hello()` 只在 `provision()` 里调用 ——
下载失败就永远走不到 `provision()`，`server.json` 永远为空，
手机侧只能看到 `the device is gone` 无限循环。

### 3.6 PYTHONPATH 保留 `/data/pylibs`

AGNOS 18.x 的 `/usr/local/venv` 里 capnproto 是半装状态（dist-info 在、`install/` 缺），
且 `/usr/local` 只读无法重装。把依赖轮子离线装到 `/data/pylibs` 是唯一出路。

两处 `launch_chffrplus.sh` 都要带 —— `launch_chffrplus.sh` 的
`export PYTHONPATH="$PWD"` 会覆盖 `launch_env.sh` 的设置。

### 3.7 `sign.py` 执行位

`panda/board/crypto/sign.py` 检出时 mode 位可能没还原 → `Error 126 Permission denied`。
`install.sh` 会 `chmod +x`。

---

## 四、编译相关的坑

| 问题 | 原因 | 解法 |
|---|---|---|
| `git fetch` 静默卡死 | comma 上没有凭据助手，非交互 SSH 会挂起等密码 | `GIT_TERMINAL_PROMPT=0 GIT_ASKPASS=/bin/true GCM_INTERACTIVE=never` |
| `No space left on device` | `/home` 是 **100MB overlay**，而 `uv sync` 要下约 100MB 轮子 | `UV_CACHE_DIR` / `UV_PYTHON_INSTALL_DIR` / `TMPDIR` 全指到 `/data`，`UV_LINK_MODE=copy` |
| `No tool module 'rednose_filter'` | 切分支后子模块目录是上一分支的半份残留 | 先 `rm -rf` 5 个子模块目录，再 `git submodule update --init --recursive` |
| `Error 126 Permission denied` | `sign.py` 缺执行位 | `chmod +x` |
| `BUILD EXIT=137` | tici 3.6G 无 swap，build.py 默认高并发被 OOM SIGKILL | 加 3G swapfile + `systemctl stop comma` + `scons -j2` |
| SSH 断开后编译被杀 | `nohup ... &` 仍被 SIGHUP 带走 | `nohup setsid bash -c '...' > /dev/null 2>&1 < /dev/null &` |

5 个子模块：`msgq_repo` `rednose_repo` `teleoprtc_repo` `tinygrad_repo` `sunnypilot/neural_network_data`。

---

## 五、设备上验证过的状态

- tici + AGNOS 18.4，`bp7.020261020` 编译通过并稳定运行
- **全程零分区写入**，引导链 `xbl_a=830f71fd` 刷前刷后一致
- `comma` 服务 active，`manager.py` / `selfdrive.ui.ui` / `pandad` / `mapd` 全部在跑
- `modeld` / `camerad` 未起属正常：offroad 状态下不启动

---

## 六、工具脚本

| 脚本 | 用途 |
|---|---|
| `install.sh` | 一键安装（链接安装入口） |
| `tools/gen_cn_font.py` | 生成中文位图字库 |
| `tools/fix_jetlink_i18n.py` | Jetlink 汉化补丁（幂等） |
| `tools/add_jetlink_po.py` | 补 po / pot 词条（幂等） |
| `tools/check_jetlink_i18n_anchors.py` | 校验汉化补丁锚点是否仍存在 |
| `tools/check_cn_patches.py` | 校验改动文件语法 |

---

## 七、已知限制

- **Jetlink 中文化的字体图集要小**：CJK 图集加大开机内存/CPU 负载。
  若用家用电源头供电，可能跨过欠压阈值导致无限重启闪烁（供电问题，非软件）。
  车上 panda 供电稳定。
- `bluepilot/ui/jetlink_ui.py` 的 `JetlinkIcons` 类写好了但全仓零实例化，
  主页和行车界面的 Jetlink 状态图标从未接入（属功能开发，非修复）。
- CI 只产出源码包，**不产出设备可直装的 prebuilt**（sunnypilot 上游那套需要自托管 tici runner）。
  设备端仍需本地编译，已验证 `scons -j2` 可行。
