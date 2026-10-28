# bp7 — BluePilot 7.0 自用分支（comma three / tici 中文 + C3 适配 + Blendful）

在 bluepilot BPVERSION 7.0.0 基础上做的自用分支，面向 **comma three (tici)**：

- 补回上游删掉的 **comma 3 整条 panda 链路**，并关掉 C3 渠道闸门
- **中文全量汉化**（zh-CHS / zh-CHT 零缺译）+ 80px 位图字库
- **一键安装**（AGNOS 界面填 URL）、离线包、引导链五道防护
- **驾驶员监控总开关**，关掉即进程级停止
- **Jetlink 外接算力**（Jetson / PC / Mac / iPhone 跑大模型）
- **Blendful 混合横向策略**（移植 sunnypilot #2073，ALPHA，默认关闭）

完整清单与逐项说明见 [第三章](#三本分支改了什么功能总览)。

---

## 一、链接安装

### 方式 A：设备开机界面填 URL（最接近「一步安装」）

comma three 开机后有一个 setup 界面，选 **Custom Software → Enter URL**，
填下面这个地址即可：

```
https://installer.comma.ai/shengkang2/openpilot/bp7.020261020
```

**这个 URL 的工作原理**（重要，决定了它能干什么）：

AGNOS 会去 `installer.comma.ai` 请求一个**针对你的仓库和分支定制过的 ELF 安装器**。
comma 的服务端会现场把安装器里的仓库地址和分支名替换成你 URL 里指定的值，
所以它**不是**下载源码，而是下载一个「只会 clone 这一个仓库这一个分支」的小程序。
设备上执行它的效果等价于：

```bash
git clone --depth=1 --recurse-submodules -b bp7.020261020 \
  https://github.com/shengkang2/openpilot.git /data/openpilot
```

然后写 `/data/continue.sh` 并重启，首次启动时编译。

已实测验证：服务端返回的 ELF 里确实嵌着
`https://github.com/shengkang2/openpilot.git` 和 `bp7.020261020`。

**BP7 为这条路径专门做的适配**（`scripts/bp7_bootstrap.sh`）：
AGNOS 这条路**不会**执行 `install.sh`，编译环境全缺，会连环失败——
uv 缓存默认落在 100MB 的 `/home` overlay（No space left）、
tici 3.6G 内存无 swap 编译被 OOM 杀掉、模型在 LFS 里是指针文件、
`sign.py` 缺执行位。自举脚本在**进入编译前**自动补齐这四项，
并只读复核五道引导链防护。它幂等，失败也不会阻断启动。

也支持只填 `owner/repo/branch` 的简写形式（AGNOS 会自动补 `installer.comma.ai/` 前缀）。

> ⚠️ **这条路径没有装前体检。** 走 SSH 跑 install.sh 时，脚本会在动手前检查
> AGNOS 版本、引导链哈希并对低版本设备（<18.5）直接拦截；
> 而 AGNOS 界面这条路跳过所有检查，直接 clone + 编译。
> **BP7 的模型与依赖是按 AGNOS 18.5 编译的**，设备底包必须是 18.5，
> 否则编译必然失败（缺 acados / capnproto 等依赖，那些库只有 18.5 镜像自带）。
>
> 好消息是变砖风险不因此增加：安装全程只写 `/data/openpilot`，
> **不刷任何分区**，引导链零改动。防护代码（`agnos.py` 硬拦截、
> 版本匹配闸、`launch_env.sh` 动态钉子、OTA 哨兵）都在**源码里**，
> clone 下来就带着，开机时照常生效。
>
> 如果装完起不来，先看 `/data/bp7_bootstrap.log`（自举日志），
> 再看 `/data/launch_log`（启动日志）。

### 方式 B：设备上一条命令（SSH / ADB shell）

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/shengkang2/openpilot/bp7.020261020/install.sh)
```

**不需要先手动 clone。** 脚本会自动完成 bootstrap：

```
0. 环境自检 → 0.5 引导链基线 → 0.6 装前体检
   → [若 /data/openpilot 不存在] 0.1 自动 clone（含 LFS）
   → 1 切分支 → 2 子模块 → 3 LFS → 4 源码适配 → 5 依赖 → 6 编译 → 7 启动 → 8 引导链比对
```

安装耗时：clone+拉模型约 5-15 分钟，编译约 20-40 分钟（tici 无 GPU，用 `scons -j2`）。

### 方式 C：离线包（设备访问不了 GitHub 时）

设备在国内、GitHub 不通时用这条。PC 上生成包：

```bash
bash tools/make_bundle.sh          # 产出 dist/bp7-offline.tar.gz，约 406MB
```

传到设备并安装：

```bash
scp dist/bp7-offline.tar.gz comma@<设备IP>:/data/
ssh comma@<设备IP>

# /data/openpilot 是 comma 服务的固定工作目录，必须展开到这里
sudo -n rm -rf /data/openpilot && sudo -n mkdir -p /data/openpilot
tar -xzf /data/bp7-offline.tar.gz -C /data/openpilot
bash /data/openpilot/install.sh
```

离线包自带子模块 + LFS 模型实体 + 17 个符号链接清单，install.sh 会自动重建符号链接、
跳过所有网络请求。包内带 `.bp7_offline` 标记，脚本据此进入离线模式。

### 方式 D：设备上已有仓库，只想更新

```bash
cd /data/openpilot
bash <(curl -fsSL https://raw.githubusercontent.com/shengkang2/openpilot/bp7.020261020/install.sh)
```

### 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `BP7_BRANCH` | `bp7.020261020` | 要安装的分支 |
| `BP7_REPO` | `https://github.com/shengkang2/openpilot.git` | 仓库地址 |
| `BP7_JOBS` | `2` | 编译并发（tici 只有 3.6G 内存） |
| `BP7_SKIP_BUILD` | `0` | 设为 `1` 只做源码适配不编译 |
| `BP7_FORCE_LOW_AGNOS` | `0` | 低版本设备（<18.5）需显式设为 `1` 才继续 |
| `OP` | `/data/openpilot` | openpilot 根目录 |

### 安装日志

| 位置 | 内容 |
|---|---|
| `/data/bp7_install.log` | install.sh 全程日志 |
| `/data/bp7_bootstrap.log` | 自举脚本日志（uv 缓存 / swapfile / LFS / 防护复核） |
| `/data/bp7_chain_before.txt` | 装前引导链哈希基线 |
| `/data/bp7_chain_after.txt` | 装后哈希，与基线比对证明零改动 |

### 回滚

```bash
cd /data/openpilot && git checkout -f <原分支> && bash install.sh
```

引导链全程零写入，回滚不需要刷任何分区。

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

## 三、本分支改了什么（功能总览）

### 3.0 总览表

| 类别 | 功能 | 验证情况 |
|---|---|---|
| 设备 | comma 3 (tici) 完整适配：panda F4/DOS 链路 + USB 传输 + 模组抢电保护 + 预编译固件 | 实机 |
| 设备 | 关闭上游 C3 渠道闸门，自建分支可在 C3 上 onroad | 实机 |
| 安装 | AGNOS 界面填 URL 一键安装（自举脚本补齐缺失的编译环境） | 实机 |
| 安装 | `install.sh` 自动 clone / 离线包 / 已有仓库增量更新 | 实机 |
| 安装 | 引导链五道防护 + 装前体检 + 装后自检，全程零分区写入 | 实机（刷前刷后哈希一致） |
| 体验 | 关闭「未注册到 comma.ai」红条（只关提示，注册逻辑不动） | 实机 |
| 稳定性 | 补 `Offroad_AcceleratorUnavailable` params 白名单（漏注册会让 UI 每秒崩一次） | 实机 |
| 稳定性 | camerad 缺摄像头子设备时降级而非 abort | 实机 |
| 中文 | UI 全量汉化：zh-CHS / zh-CHT 零缺译（约 860 词条），框架层 `tr()` 抽取 | 实机 |
| 中文 | 80px NotoSansSC 位图字库（841 字形 / 728 汉字），按字号整数比缩放 | 实机 |
| 功能 | 驾驶员监控（DM）总开关 `DriverModelEnable`，关掉后进程级停止 | 实机 |
| 功能 | 无驾驶员摄像头的机器（3XL）自动降级为「DM 关闭」 | 实机 |
| 功能 | Jetlink 外接算力接入（大模型在 USB-C 外接机上跑，comma 只做前处理与控车） | 实机 |
| 功能 | Jetlink 设置面板补注册 + 握手顺序修复 | 实机 |
| 功能 | **Blendful 混合横向策略**（移植 sunnypilot #2073，ALPHA，默认关闭） | 代码级 + 单测，**待实机** |
| 构建 | `PYTHONPATH` 保留 `/data/pylibs`（AGNOS 18.x 的 capnproto 半装） | 实机 |
| 构建 | `sign.py` 补执行位（否则固件签名 Error 126） | 实机 |

### 3.1 comma 3 (tici) 适配

官方 bp-7.0 在 2025 年底随上游删除了 comma 3 所需的整条 panda 链路。本分支把整条链路补回，
C3 适配逻辑取自 `shengkang2/openpilot@spbp260825`（已在 C3 实机验证），
pandad 主流程保持 BP 原样（rivian flasher / check_panda_support / single-panda 断言都不动）：

- **panda 固件层**：`panda/` 整目录替换为含 F4/DOS 的版本（`board/stm32f4`、`dos.h`、
  `HW_TYPE_DOS(6)` 回归），`SConscript` 同时构建 panda(F4) 与 panda_h7；
  `.gitmodules` 去掉 panda 子模块，改为随仓库携带
- **预编译固件**：`panda/board/obj/` 四个 `*.bin.signed` 入库，设备端不必重新签名
- **pandad 传输层**：新增 `panda_comms.{h,cc}` USB 实现，句柄改
  `unique_ptr<PandaCommsHandle>` 支持 USB/SPI 多态，构造与 `list()` 改为 USB 优先、SPI 回落；
  `SConstruct` 的 `allowed_system_libs` 放行 `usb-1.0`
- **签名与刷写**：`get_expected_signature()` 按 `hw_type` 选 F4/H7，刷写白名单放行 `HW_TYPE_DOS`
- **C3 共享 USB hub 抢电保护**：C3 上 EC25 模组（500mA）与内部 DOS panda 共用同一 hub，
  模组抢先枚举会把 panda 挤下线。做法是开机先压住模组（`system/hardware/tici/modem_usb.py`，
  udev 规则 + `authorized=0`），pandad 稳定 1s 后再放行；
  `launch_chffrplus.sh` 在 `agnos_init` 后调用 `defer_modem_usb()`

### 3.2 关闭 C3 渠道闸门

`system/hardware/hardwared.py`：上游弃坑 comma 3 后加了

```python
is_unsupported_combo = TICI and get_device_type() == "tici" and channel_type != "tici"
```

导致 `bp7.020261020`（`channel_type=feature`）在 C3 上 `onroad_conditions["not_tici"]`
恒为 `False`、**永远无法 engage**，并弹 `Offroad_TiciSupport`。本分支直接置 `False`
（与在役的 spbp260825 做法一致），panda / pandad 层不改动。

### 3.3 关闭「未注册到 comma.ai」红条警报

`system/athena/registration.py`：`Offroad_UnregisteredHardware` 恒置 `False`。
**只关提示，注册逻辑一行没动**（`dongle_id` 照样尝试注册并写入参数）。

### 3.4 补 params 白名单

`common/params_keys.h` 补 `Offroad_AcceleratorUnavailable`。

bp7 的 `system/hardware/hardwared.py:331` 会写这个 key，
`selfdrive/selfdrived/alerts_offroad.json:58` 也定义了它，
但白名单漏注册（旁边 14 个 `Offroad_*` 都在）。
`Params.get()` 走 C++ `check_key()` 严格校验，直接抛异常把 UI 打死，**每秒崩一次**。

### 3.5 中文化

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

### 3.6 驾驶员监控（DM）总开关

`DriverModelEnable`（默认开）是**唯一真相源**，关掉后是进程级停止，不是"继续跑但不出告警"：

| 层 | 行为 |
|---|---|
| `system/manager/process_config.py` | `dmonitoringmodeld` / `dmonitoringd` 不启动；`camerad` 带 `DISABLE_DRIVER=1`，整条驾驶员摄像头流水线（ISP / ICP / 1080p VIPC）不启动，仅在预览时开 |
| `selfdrive/monitoring/dm_availability.py` | `driver_monitoring_disabled()` 单一判定：参数关闭，或机器上数不到 `cam-sensor-driver` 子设备（3XL 只有 2 个 → 判为无摄像头） |
| `selfdrive/selfdrived` | `driverStateV2` / `driverMonitoringState` 进 `ignore_alive/freq/valid`，避免停掉的 DM 被读成 `cameraMalfunction` / `commIssue`；ignore 以 10Hz 随参数实时同步，不占 100Hz 控制路径 |
| `selfdrive/controls/controlsd.py` | `forceDecel` 只在该包还活着时才认 `alertLevel` —— 原来断流后 SubMaster 一直返回最后一包，stale 的 `alertLevel` / `lockout` 会**永久 forceDecel、永久 tooDistracted** |
| UI | 大小屏 `driver_state` 断流直接不画；驾驶员摄像头预览显示「driver monitoring is off」而不是永远「camera starting」；`circular_alerts` 的 e2e 提示（绿灯起步 / 前车起步）在 DM 关闭时视为就绪 |

顺带修掉一个真实回归：`longitudinalPlanSP` 的 SP 事件原先被错放在 DM 代码块里，DM 一关就整块不发。

未上 DM 开关的机器（比如 3XL 硬件的车）不需要手动关：判定会把开关本身置上，设置界面显示的就是设备真实行为。

### 3.7 camerad 缺摄像头子设备时降级

`openSensor()` 里 `open_v4l_by_name_and_index()` 返回 -1 时是 `assert`。没有驾驶员摄像头的机器
（3XL）连 `cam-sensor-driver` 子设备都没有，camerad 会在开机时反复 abort，
把两颗路面摄像头一起带走。改成与传感器 probe 失败相同的降级路径：
`enabled = false` 后返回，`sendState()` 再补一道守卫，避免 `pm` 为空时被事件回调踩到。

### 3.8 Jetlink 外接算力（Jetson / PC / Mac / iPhone）

在 comma 的 USB-C 口外接一台机器跑大模型：相机、warp、parser、controlsd、panda、CAN
全部留在 comma，外接机只是**纯函数**（warp 后的帧 + 上下文进，18452 个浮点出）。
大模型只在「无人接管」时换入，掉帧超预算就回退小模型。

#### 3.8.1 接入层

- **vendored**（未改上游代码）：`jetlink_repo/jetlink`（37 个文件，jetlink 0.8.7 / API 3，MIT）
  + `jetlink_repo/scripts/comma/jetlink-root.sh`（configfs gadget、NCM、UDC、VM 调优）；
  树根 `jetlink` 符号链接由 `launch_chffrplus.sh` 每次开机重建
- **转接层 `bluepilot/jetlink_adapter`**（顶层只用标准库，`jetlinkd` 常驻约 10MB）：
  实现 `jetlink.openpilot.interface.Openpilot`，用 jetlink 自带 `conformance()` 对照 API 3
  校验全通过（Openpilot / StatusSide / WorkerSide / ModelSide）；
  `in_control()` 直接用 bp 的 MADS 判定（启用/转向，或 MADS enabled 含 paused），
  不需要 dp 那套 ALKA + lkasOn 替代；`SmallModel` 代理翻译
  `after_enqueue`（可调用）与 bp `ModelState.prepare_only`（bool）的签名差异；
  `build_warp.py` 在构建期生成 `driving_warp_<cam>_512x256_tinygrad.pkl`
  （bp 的 warp 熔在 `warp_enqueue` 里，没有独立 pickle）
- **modeld**：`prepare()`（在 `config_realtime_process` 之前，tinygrad 线程不能继承
  FIFO54/core7）→ `attach()` → `use_submaster(sm)`；每帧写 `frame_drop_ratio`，
  handover 时重置掉帧滤波；发布 `modelDataV2SP.acceleratorState` / `bigModel`
- **manager**：新增 `jetlinkd`（`always_run` + `should_run`，`UsbGpuPresent` 时让位）
- **selfdrived**：4 个加速器事件（`EventName` @98–@101）、`jetlinkd` 视为可选进程、
  切换后 1 秒 settling 内抑制 `commIssue` / `posenet` / `locationd`
- **hardwared**：`Offroad_AcceleratorUnavailable` 离线告警；关机前先请外接机一起下电（≤25s）
- **UI**：`ui_state` 5Hz 快照 + `JetlinkState`；设置里的 Jetlink 面板显示
  Off / USB / iOS、链路状态、传输量、端口、将用的大模型、进度、失败原因、模型清单
- **capnp**：`ModelDataV2SP` 增加 `acceleratorState`（6 态，名字与 jetlink `STATES` 一致）
  与 `bigModel`；`EventName` 增加 @98–@101（bp 原最大 @97）
- **已知限制**：只在 `selfdrive/modeld`（stock runner）上接线；
  sunnypilot 的 `modeld_tinygrad`（自定义 bundle）暂未接入，此时 `acceleratorState` 恒为 `none`

#### 3.8.2 补回设置面板

bluepilot 上游把 `JetlinkLayout` 只注册进原版 `selfdrive/ui/layouts/settings/settings.py`，
但 sunnypilot 覆盖版的 `_panels` 字典漏了这一项。
`layers/main.py` 在 `gui_app.sunnypilot_ui()` 为真时用 `SettingsLayoutSP`，所以菜单里永远看不到 Jetlink。

`PanelType.JETLINK = 6` 枚举一直存在，`icons/jetlink.png` 也在，纯粹是面板注册漏了。

#### 3.8.3 握手顺序修复

`jetlink_repo/jetlink/openpilot/provision.py`：改为
`open_link → wait_for_jetson → provision()`（`provision()` 内含 `hello()`）。

原顺序先下载模型再开链路，而 `hello()` 只在 `provision()` 里调用 ——
下载失败就永远走不到 `provision()`，`server.json` 永远为空，
手机侧只能看到 `the device is gone` 无限循环。

### 3.9 Blendful 混合横向策略（ALPHA，移植 sunnypilot #2073）

上游是 `sunnypilot/sunnypilot#2073`（`laneful-curves` 分支，作者 Discountchubbs，仍未合并）。
本分支是**手工移植**，不是 cherry-pick：该 PR 基于 sunnypilot 2026-10 的 `openpilot/`
monorepo 布局和被重写过约 40% 的 `modeld.py`，而本分支基座是 6 月分叉的扁平布局，
15 个既有文件上下文全不一致，按「增量重锚定」落地。

**它是什么**：不是「车道线 vs 无车道线」二选一，而是**连续混合** ——
车道线可信时向车道中心做曲率修正，不可信时更多依赖模型预测路径。
只有单侧线（甚至只有路缘石）也能用，不是完整 laneful 模式；空车道时退化为纯 laneless。

**落地内容**

| 位置 | 改动 |
|---|---|
| `sunnypilot/modeld_v2/blendful.py` | 新增核心数学：横向信任度、左右车道概率、绕行判定、曲率修正（含淡出与复位） |
| `sunnypilot/modeld_v2/tests/test_blendful.py` | 上游 9 个用例随代码一起移植 |
| `sunnypilot/modeld_v2/modeld.py` | `get_action_from_model()` 增加可选 `blendful` 回调，修正注入点在 generation≥10 平滑**之后**；`main()` 读 `Blendful` 参数、算 `blendful_active`（desire=none 且无变道）、发布 7 个诊断字段 |
| `cereal/custom.capnp` | `ModelDataV2SP` 新增 `blendfulCurvature @3` … `blendfulLaneWidth @9`；**`@1/@2` 的 Jetlink 字段原样保留**，跳过了属于 RELC 的两个 road-edge 字段 |
| `cereal/services.py` | `modelDataV2SP` 提到 20Hz / BIG 队列（诊断字段要上 UI） |
| `common/params_keys.h` | 新增 `Blendful`（`PERSISTENT \| BACKUP`，默认 `"0"`） |
| `selfdrive/ui/sunnypilot/onroad/blendful.py` | 新增可视化：信任度着色、修正量读数、绕行/车道概率 |
| 三个渲染器 | 大屏、mici、sunnypilot mixin 各挂一处，仅非 DISENGAGED 时绘制 |
| Models 设置页 | 大小屏各一个「Blendful (Alpha)」开关 |
| Sunnylink | `model_behavior` 增加 `Blendful` 项 + `custom_model_active` capability |

**两级门控（安全项，不能省）**

1. **modeld 侧**：`blendful_capable` 只认 `Runner.tinygrad`（即 modeld_v2 / 自定义 bundle）。
   stock / snpe runner 上开关无效；demo 与 `COMBINED_MODEL_PKL` 允许
2. **UI 侧**：开关只在选了自定义模型包时可见可点（Sunnylink 那项用 `custom_model_active` 同理）

关掉时 `update()` 严格返回 0 并把内部状态复位，**关闭态与未移植前逐帧等价**。

**验证情况**

- 上游 9 个单元测试全过：居中不推、向中心拉、换向慢建、弱线退化 laneless、单线闪烁保持、
  绕行让行、trust 下降不放大、关开关归零复位、低速淡出
- 接线与配置检查 20 项全过：capnp 序号唯一升序、modeld 只写 schema 中存在的字段、
  `enabled=False` 严格返回 0、inactive 单调淡出、参数/服务/UI/配置项齐全
- 改动文件全部 `py_compile` 通过
- **真机编译、UI 渲染、横向行为未验证** —— 这也是它仍标 ALPHA 的原因

**怎么用**：设置 → 模型 → 选一个自定义（modeld_v2）模型包 → 打开「Blendful (Alpha)」→
先在封闭路面的低速弯道确认手感。出问题直接关开关即可，下一帧就回退（不用重启 modeld）。

### 3.10 PYTHONPATH 保留 `/data/pylibs`

AGNOS 18.x 的 `/usr/local/venv` 里 capnproto 是半装状态（dist-info 在、`install/` 缺），
且 `/usr/local` 只读无法重装。把依赖轮子离线装到 `/data/pylibs` 是唯一出路。

两处 `launch_chffrplus.sh` 都要带 —— `launch_chffrplus.sh` 的
`export PYTHONPATH="$PWD"` 会覆盖 `launch_env.sh` 的设置。

### 3.11 `sign.py` 执行位

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

## 五、验证状态

### 5.1 实机验证

- tici + AGNOS 18.4，`bp7.020261020` 编译通过并稳定运行
- **全程零分区写入**，引导链 `xbl_a=830f71fd` 刷前刷后一致
- `comma` 服务 active，`manager.py` / `selfdrive.ui.ui` / `pandad` / `mapd` 全部在跑
- `modeld` / `camerad` 未起属正常：offroad 状态下不启动
- C3 panda 链路（F4 固件签名 + USB 传输 + 模组抢电保护）实际可用
- 汉化后 UI 无越界/缺字，`zh-CHS` / `zh-CHT` 零空译
- DM 关闭后 `dmonitoringd` / `dmonitoringmodeld` 不在进程表，`camerad` 无 ISP/ICP 占用
- Jetlink 外接机接入、面板状态、握手、掉电联动实测通过

### 5.2 仅代码级验证（未上真机）

- **Blendful**：单元测试 9/9、接线与配置检查 20/20、`py_compile` 全过；
  真机 SCons 编译（capnp 重生成）、UI 渲染、横向行为**尚未验证**

---

## 六、工具脚本

| 脚本 | 用途 |
|---|---|
| `install.sh` | 一键安装（链接安装入口，自动 bootstrap / 离线模式 / 增量更新） |
| `scripts/bp7_bootstrap.sh` | AGNOS 填 URL 安装后的开机自举（uv 缓存 / swapfile / LFS 模型 / 执行位 / 防护复核） |
| `tools/make_bundle.sh` | 生成离线包 `dist/bp7-offline.tar.gz`（约 406MB） |
| `tools/gen_cn_font.py` | 生成中文位图字库（`--size 80`） |
| `tools/fix_jetlink_i18n.py` | Jetlink 汉化补丁（幂等） |
| `tools/add_jetlink_po.py` | 补 po / pot 词条（幂等） |
| `tools/check_jetlink_i18n_anchors.py` | 校验汉化补丁锚点是否仍存在 |
| `tools/check_cn_patches.py` | 校验改动文件语法 |

---

## 七、已知限制

- **Blendful 仍是 ALPHA**：上游 PR #2073 未合并，调参未收敛，没有上游测试数据兜底。
  默认关闭，关闭态对行为零影响；开启后横向手感需自行评估。
  上游若后续改字段序号或改注入点，移植部分需要重新对锚。
- **Blendful 只对 modeld_v2 模型生效**：stock / snpe runner 上开关无效，
  需要选一个自定义（tinygrad bundle）模型包。
- **Blendful 未接入 UI 告警通道**：只有可视化与 Sunnylink 状态，不产生自检事件。
- **Jetlink 中文化的字体图集要小**：CJK 图集加大开机内存/CPU 负载。
  若用家用电源头供电，可能跨过欠压阈值导致无限重启闪烁（供电问题，非软件）。
  车上 panda 供电稳定。
- **Jetlink 未接的 runner**：`modeld_tinygrad`（自定义 bundle）路径下
  `acceleratorState` 恒为 `none`，即自定义模型 + 外接算力不能同时用。
- `bluepilot/ui/jetlink_ui.py` 的 `JetlinkIcons` 类写好了但全仓零实例化，
  主页和行车界面的 Jetlink 状态图标从未接入（属功能开发，非修复）。
- CI 只产出源码包，**不产出设备可直装的 prebuilt**（sunnypilot 上游那套需要自托管 tici runner）。
  设备端仍需本地编译，已验证 `scons -j2` 可行。

---

## 八、更新日志

| 日期 | 内容 |
|---|---|
| 2026-10-20 | C3 (tici) 支持：panda F4/DOS 链路补回、预编译固件入库、关闭 C3 渠道闸门 |
| 2026-10-20 | Jetlink 外接算力接入（含 capnp 事件序号修正） |
| 2026-10-20 | 驾驶员监控总开关 `DriverModelEnable` |
| 2026-10-21 | `camerad` 缺摄像头子设备降级，不再开机 abort |
| 2026-10-21 | DM 开关收敛为唯一真相源，关闭后进程级停止；修掉 DM 关闭时的 e2e 提示与 `longitudinalPlanSP` 回归 |
| 2026-10-21 | UI 全量汉化：zh-CHS / zh-CHT 零缺译，框架层 `tr()` 抽取，80px 位图字库 |
| 2026-10-24 | 引导链三重防护（代码层硬拦截 + 装前体检 + 装后自检） |
| 2026-10-24 | 低版本设备防护：版本匹配闸 + OTA 覆盖哨兵 + 装前拦截 |
| 2026-10-24 | 安装链路补全：`install.sh` 自动 bootstrap clone、离线包、符号链接重建 |
| 2026-10-24 | 支持 AGNOS 界面「填 URL 一键安装」：新增 `scripts/bp7_bootstrap.sh` + 修正 LFS 拉取配置 |
| 2026-10-28 | **Blendful 混合横向策略移植**（sunnypilot #2073，ALPHA，默认关闭） |

