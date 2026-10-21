# BYD 参考资料（非运行时数据）

本目录的内容**不会被任何代码加载**，只是把社区 mypilot BYD 移植包里
无法直接接线、但有参考价值的原始资料归档进来，方便后续逆向与二次开发。

来源：<https://github.com/yuluoqingcheng/openpilot-mypilot-community-dbcall>
（以下简称"社区包"），由 mypilot 团队/社区贡献者逆向所得。

## 文件说明

| 文件 | 原路径 | 说明 |
| :--- | :--- | :--- |
| `byd_all_nodes.dbc` | `byd大全.dbc` | 比亚迪全车系全节点逆向字典（EPS/ADAS/RADAR/CAMERA/BCM/VCU/BMS），约 600+ 报文 ID，抓包与二次开发的底料 |
| `byd_song_plus.dbc` | `比亚迪3/Bydsong(1).dbc` | 宋系实车抓包 DBC（42KB，信号注释最全） |
| `byd_tang_dmp.dbc` | `比亚迪3/唐DMP_based_on_han.dbc` | 唐 DM-p 基于汉平台扩展的 DBC |
| `byd_han_dmev_2020.dbc` | `BYD_Files/opendbc/dbc/byd_han_dmev_2020.dbc` | 汉 DM/EV 2020 旧代 DBC；当前平台统一用 `opendbc/dbc/byd_generic_pt.dbc`，此文件仅作对照 |
| `lat_models/*.json` | `高阶Python源码_v2/.../torque_data/lat_models/` | 汉 DM 20、汉 DM-i 22、宋 PLUS DM-i 22 的横向力矩模型数据 |

## 为什么 lat_models 没有接入

社区包里的 `lat_models/*.json` 是旧版 opendbc/sunnypilot 神经网络横向
（NNFF）的数据格式。本分支的 opendbc 已经不再读取 `torque_data/lat_models`
目录（已确认无任何代码引用），神经横向走的是
`opendbc/sunnypilot/car/torque_data/neural_ff_weights.json` 与
`openpilot/sunnypilot/neural_network_data`。直接放进去不会被使用，
需要把系数转成当前 NNFF 权重格式才有意义，因此仅作数据留档。

## 关于社区包的授权检查

社区包的 `高阶Python源码_v2` 里带有一个 `opendbc/car/byd/server_connect.py`，
会在 `CarState.__init__` 中把设备序列号、设备型号、分支/commit 上报到硬编码的
`http://39.108.82.40/api/check` 换取 license。本分支**没有任何**相关代码，
本目录归档的文件也不含该逻辑（DBC 与 JSON 为纯数据）。
如果后续再参考该包的其他文件，请先检查 import 里是否含 `server_connect`。
