# 吉利（Geely Binyue）移植包 —— **未启用**

来源：<https://github.com/yuluoqingcheng/openpilot-mypilot-community-dbcall> 的 `吉利源码/`。
原包按 openpilot 0.9.x / carrot 0.9.9 的旧接口编写，这里已做**机械适配**（见下），
但**缺少三样硬依赖，无法实车运行，因此故意不注册到 `opendbc.car.values`**。

## 为什么放在 `opendbc/geely_port/` 而不是 `opendbc/car/geely/`

`opendbc/car/interfaces.py::get_interface_attr()` 会 `os.walk(opendbc/car)`，
把**每个子目录**都 `__import__` 一遍来收集 `FINGERPRINTS` / `FW_VERSIONS`。
如果把未注册的 `car/geely/` 放进去：

1. 它的指纹（60 个 CAN ID）会被合并进全局 `_FINGERPRINTS`，但 `PLATFORMS` 里没有
   `GEELY_BINYUE`，一旦别的车误匹配到这组 ID，会 `KeyError` 或直接进 dashcamOnly；
2. `values.py` 在 import 阶段就会构造 `CAR`，任何类型不匹配都会把整个 openpilot 拖挂。

所以放在扫描目录之外，只有显式 `import opendbc.geely_port.xxx` 才会加载。

## 缺少的三样东西（缺一不可）

| # | 缺什么 | 现状 | 补法 |
| :--- | :--- | :--- | :--- |
| 1 | `geely_binyue_pt.dbc`、`geely_radar_bus1.dbc` | **社区包没有附带**，只有消用方（`CANParser`/`CANPacker`/`CANDefine`） | 从实车抓包重建，或用作者未公开的 DBC；放到 `opendbc/dbc/` |
| 2 | panda safety：`opendbc/safety/modes/geely.h` | **社区包没有**；`values.py` 里却引用了 `GEELY_DRIVER_TORQUE_FACTOR` | 按 `modes/byd.h` 的写法新写一个（力矩上限 598、上升 20 / 下降 30 @50Hz、驾驶员扭矩系数 30，报文 `ADAS_LKAS`），并注册到 `safety.h` 与 `safety_declarations.h` 的 `SAFETY_GEELY` |
| 3 | `structs.CarParams.SafetyModel.geely` | 本分支 `car.capnp` 的 `SafetyModel` 枚举里没有 geely | 在 `opendbc_repo/opendbc/car/car.capnp` 的 `enum SafetyModel` 末尾增值（不重用旧编号），然后重新生成 capnp |

## 已做的适配（相对于社区原版）

| 文件 | 改动 |
| :--- | :--- |
| `carstate.py` | `from opendbc.can import CANParser, CANDefine` → `opendbc.can.parser` + `opendbc.car.can_define`；`update(can_parsers, hud_control=None)` → `update(can_parsers)`；返回值 `ret` → `(ret, self.out_sp)`（本分支契约）；`get_can_parsers(CP)` → `(CP, CP_SP)`；`get_wheel_speeds()`（本分支已移除）→ `parse_wheel_speeds()` |
| `carcontroller.py` | `apply_driver_steer_torque_limits` 从 `opendbc.car` 改到 `opendbc.car.lateral`；`__init__(dbc_names, CP)` → `(dbc_names, CP, CP_SP)`；`update(CC, CS, now_nanos)` → `(CC, CC_SP, CS, now_nanos)`；返回执行器改用 `actuators.as_builder()` |
| `radar_interface.py` | `CANParser` 改用 `opendbc.can.parser` |
| `values.py` | `PlatformConfig` 改为本分支的 `(car_docs, specs, dbc_dict, flags)` 形态；`CarDocs` 子类去掉 `package` 必填以外的旧字段；补 `DbcDict` 类型 |
| 包路径 | `opendbc.car.geely.*` → `opendbc.geely_port.*` |

**未适配、保持原样的风险点**（有 `TODO(geely-port)` 标记）：
- 轮速单位：原码 `WHEELSPEED_F/B` 直接取原始值，本分支 `parse_wheel_speeds()` 需要 unit，
  暂时按 `KPH_TO_MS`。**DBC 到手后必须核对 factor，否则 vEgo 会差 3.6 倍。**
- `radar_interface.update(can_strings)` 仍是旧签名；本分支基类是 `update(can_packets)` 并自己
  `cp.update()`。雷达接口需要再改一次（或在 CarInterface 里不走雷达）。
- `interface.py` 里 `SafetyModel.geely` 目前会抛 AttributeError（见上表第 3 项）。

## 收尾清单（DBC 与 safety 就绪后）

1. 把两个 DBC 放进 `opendbc/dbc/`。
2. 写 `opendbc/safety/modes/geely.h`（参考 `byd.h`），在 `safety/safety.h` 里
   `#include` 并注册 `geely_hooks`，在 `safety_declarations.h` 里加 `SAFETY_GEELY`。
3. `car.capnp` 加 `geely @N :SafetyModel;` 并重新生成。
4. 修 `radar_interface.update()` 签名、核对轮速单位。
5. 注册品牌：`opendbc/car/values.py` 加
   `from opendbc.geely_port.values import CAR as GEELY`，并把 `GEELY` 加进 `Platform` 联合；
   `opendbc/car/fingerprints.py` 同样加 import（`FW_VERSIONS`/`FINGERPRINTS` 由 `get_interface_attr` 合并）。
   **注意**：本分支的 `get_interface_attr` 只扫描 `opendbc/car/*`，所以注册时要
   把整个目录移回 `opendbc/car/geely/` 并把 import 前缀改回去。
6. 跑 `pytest opendbc/car/tests/`（`test_car_interfaces.py` 会逐平台构造接口，能暴露 DBC 信号缺失）。

## 这套代码里值得保留的东西

- `geelycan.py` 的 CRC8（多项式 0x2F / init 0xFF / xorout 0xFF）与整包转发策略
  （不控车时原样转发摄像头报文，只改控制字段），是可以直接复用的。
- `carstate.py` 里的按钮编码（CANCEL=3 / SET_DECEL=5 / SET_ACTIVATE=1 / RES_ACCEL=4 / RES_RESUME=2）、
  转向灯最小帧数 112、`HUD_MULTIPLIER=1.035` 都是实车抓出来的。
- `radar_interface.py` 头部有一整套 Continental ARS410（ARS4-B）逆向结论：
  距离 `0.98*(b3<<8|b4)/256 - 3.4`、相对速度 `(b0-127.6)/1.27`、相对加速度 `(g2b4-128)/12.5`、
  航迹 ID = 槽号 + 40×代次、报文无横向位置（`yRel` 恒 0）。
  这些公式独立于 DBC，即使没有 DBC 也有参考价值。
- `fingerprints.py` 里 60 个实车 CAN ID + DLC，可直接作为抓包对照表。
