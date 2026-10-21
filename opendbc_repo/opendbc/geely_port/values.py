#!/usr/bin/env python3
"""吉利（Geely）平台配置。

⚠️ 本包目前**未注册**：`opendbc/car/values.py` 里没有 GEELY，`opendbc/car/fingerprints.py`
也不会加载它。原因见同目录 README.md（缺 DBC、缺 panda safety、缺 SafetyModel.geely）。

已按本分支（sunnypilot / opendbc_repo）的 PlatformConfig / CarDocs 形态适配；
社区原版按旧的 (docs, specs) 两参形式构造，在本分支会直接 TypeError。
"""
from dataclasses import dataclass, field
from enum import IntFlag

from opendbc.car import Bus, CarSpecs, DbcDict, PlatformConfig, Platforms
from opendbc.car.docs_definitions import CarDocs, CarHarness, CarParts
from opendbc.car.fw_query_definitions import FwQueryConfig
from opendbc.car.structs import CarParams

Ecu = CarParams.Ecu

# 仪表车速相对实际车速的系数（社区实车标定值）
HUD_MULTIPLIER = 1.035


class CarControllerParams:
  STEER_STEP = 2          # 100Hz / 2 = 50Hz
  STEER_MAX = 598         # 实车验证的最大转向力矩
  STEER_DELTA_UP = 20     # 每帧增量（@50Hz）
  STEER_DELTA_DOWN = 30   # 每帧回退量（@50Hz）

  # 总系数 = STEER_DRIVER_FACTOR × STEER_DRIVER_MULTIPLIER = 30
  # 必须与 safety/modes/geely.h 中的 GEELY_DRIVER_TORQUE_FACTOR 保持一致
  STEER_DRIVER_ALLOWANCE = 0
  STEER_DRIVER_MULTIPLIER = 15
  STEER_DRIVER_FACTOR = 2

  ACCEL_MAX = 1.5
  ACCEL_MIN = -3.5

  NEAR_STOP_BRAKE_PHASE = 0.5
  ACC_HUD_STEP = 50

  def __init__(self, CP):
    # 转向力矩上限取 lateralParams.torqueV 的最大值（单点标定，非速度相关）
    lateral_params = getattr(CP, "lateralParams", None)
    if lateral_params and hasattr(lateral_params, "torqueV") and len(lateral_params.torqueV) > 0:
      self.STEER_MAX = int(lateral_params.torqueV[-1])

    if CP.flags & GeelyFlags.RAISED_ACCEL_LIMIT:
      self.ACCEL_MAX = 2.0


class GeelyFlags(IntFlag):
  RAISED_ACCEL_LIMIT = 1 << 0
  STOCK_ACC = 1 << 1
  ALC_ENABLED = 1 << 2
  MADS_ENABLED = 1 << 3
  HAS_GAS_INTERCEPTOR = 1 << 4


class GeelySafetyFlags(IntFlag):
  STOCK_LONGITUDINAL = 1 << 0


class CanBus:
  PT = 0     # 动力总线
  CAM = 2    # 原车摄像头 / ADAS 总线


GEELY_BINYUE_DBC: DbcDict = {
  Bus.pt: 'geely_binyue_pt',
  Bus.radar: 'geely_radar_bus1',
  Bus.cam: 'geely_binyue_pt',
}


@dataclass
class GeelyCarDocs(CarDocs):
  car_parts: CarParts = field(default_factory=CarParts.common([CarHarness.obd_ii]))


@dataclass
class GeelyPlatformConfig(PlatformConfig):
  dbc_dict: DbcDict = field(default_factory=lambda: dict(GEELY_BINYUE_DBC))


class CAR(Platforms):
  GEELY_BINYUE = GeelyPlatformConfig(
    [GeelyCarDocs(name='Geely Binyue', package='All')],
    CarSpecs(
      mass=1370.0,
      wheelbase=2.6,
      steerRatio=15.0,
      centerToFrontRatio=0.44,
      tireStiffnessFactor=0.9871,
    ),
    dict(GEELY_BINYUE_DBC),
    int(GeelyFlags.ALC_ENABLED),
  )


DBC = CAR.create_dbc_map()

# 吉利不通过 UDS 公开固件版本，社区版用空请求列表；若后续要用固件指纹需补 Request
FW_QUERY_CONFIG = FwQueryConfig(requests=[])

# 社区版给的占位固件号，未实车抓取，仅用于让框架结构完整
FW_VERSIONS = {
  CAR.GEELY_BINYUE: {
    (Ecu.eps, 0x730, None): [b'GEELY_EPS_V1.0'],
    (Ecu.engine, 0x7e0, None): [b'GEELY_ECU_V1.0'],
    (Ecu.fwdCamera, 0x750, None): [b'GEELY_CAM_V1.0'],
  },
}
