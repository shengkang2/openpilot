#!/usr/bin/env python3
from dataclasses import dataclass, field
from enum import IntFlag, StrEnum

from opendbc.car import Bus, CarSpecs, DbcDict, PlatformConfig, Platforms
from opendbc.car.docs_definitions import CarDocs, CarHarness, CarParts
from opendbc.car.fw_query_definitions import FwQueryConfig, Request
from opendbc.car.structs import CarParams
from opendbc.car.byd.params_compat import Params

Ecu = CarParams.Ecu

@dataclass
class BydCarDocs(CarDocs):
  car_parts: CarParts = field(default_factory=CarParts.common([CarHarness.custom]))

@dataclass(frozen=True)
class BydCarSpecs(CarSpecs):
  minSteerSpeed: float = 0.0
  minEnableSpeed: float = -1.0

@dataclass
class BydPlatformConfig(PlatformConfig):
  dbc_dict: DbcDict = field(default_factory=lambda: {Bus.pt: 'byd_generic_pt'})
  flags: int = 0

class BydFlags(IntFlag):
  CANFD = 1
  ANGLE_CONTROL = 2
  ALT_INDICATOR = 4
  SETSPEED_X10 = 8
  BCM_SEAL = 16
  ALT_ACC_EPS = 32
  ALT_ACC_EPS_SEAL = 64
  ALT_ACC_CURISE_MODE = 128
  ALT_ACC_ACCON1 = 256
  ALT_PCM_BTN = 512
  ACC_STOP_FIX = 1024
  ANGLE_DRIVER_OVERRIDE_RELEASE = 2048

class BydSafetyFlags(IntFlag):
  ANGLE_MODE = 1
  ACC_ON1 = 2
  ACC_CRUISEDISP = 4

class LKASConfig:
  DISABLE = 0
  ALARM = 1
  LKA = 2
  ALARM_AND_LKA = 3

class CanBus:
  ESC = 0
  MRR = 1
  MPC = 2
  LOOPBACK = 128
  DROPPED = 192

  @staticmethod
  def checkPanda():
    if Params().get_bool('UseRedPanda'):
      CanBus.ESC = 4
      CanBus.MRR = 5
      CanBus.MPC = 6
      CanBus.LOOPBACK = 132
      CanBus.DROPPED = 196
      print('Using External Panda')
    else:
      CanBus.ESC = 0
      CanBus.MRR = 1
      CanBus.MPC = 2
      CanBus.LOOPBACK = 128
      CanBus.DROPPED = 192
      print('Using Internal Panda')

class CarControllerParams:
  STEER_MAX = 300
  STEER_DELTA_UP = 17
  STEER_DELTA_DOWN = 17
  STEER_DRIVER_ALLOWANCE = 68
  STEER_DRIVER_MULTIPLIER = 3
  STEER_DRIVER_FACTOR = 1
  STEER_ERROR_MAX = 80
  MAX_STEER_ANGLE = 640
  ACCEL_MAX = 3.0
  ACCEL_MIN = -4.5
  K_DASHSPEED = 0.0719088
  K_accel_jerk_upper = 0.1
  K_accel_jerk_lower = 0.5
  K_jerk_xp = [4, 10, 20, 40, 80]
  K_jerk_base_lower_fp = [-2.0, -1.8, -1.4, -1.0, -0.4]
  K_jerk_base_upper_fp = [0.8, 0.7, 0.6, 0.3, 0.2]

  def __init__(self, CP):
    CanBus.checkPanda()

class CAR(Platforms):
  BYD_HAN_DM_20 = BydPlatformConfig([BydCarDocs(name='Byd Han DM 20', package='All', video=None, setup_video=None, min_steer_speed=None, min_enable_speed=None, auto_resume=None, merged=True, support_link='#upstream')], BydCarSpecs(mass=2080.0, wheelbase=2.92, steerRatio=15.0, centerToFrontRatio=0.44, minSteerSpeed=0.0, minEnableSpeed=-1.0, tireStiffnessFactor=1.0), {Bus.pt: 'byd_generic_pt'}, 1024)
  BYD_HAN_EV_20 = BydPlatformConfig([BydCarDocs(name='Byd Han EV 20', package='All', video=None, setup_video=None, min_steer_speed=None, min_enable_speed=None, auto_resume=None, merged=True, support_link='#upstream')], BydCarSpecs(mass=2100.0, wheelbase=2.959, steerRatio=15.0, centerToFrontRatio=0.44, minSteerSpeed=0.0, minEnableSpeed=-1.0, tireStiffnessFactor=1.0), {Bus.pt: 'byd_generic_pt'}, 1024)
  BYD_HAN_DMI_22 = BydPlatformConfig([BydCarDocs(name='Byd Han DMI 22', package='All', video=None, setup_video=None, min_steer_speed=None, min_enable_speed=None, auto_resume=None, merged=True, support_link='#upstream')], BydCarSpecs(mass=2080.0, wheelbase=2.92, steerRatio=15.0, centerToFrontRatio=0.44, minSteerSpeed=0.0, minEnableSpeed=-1.0, tireStiffnessFactor=1.0), {Bus.pt: 'byd_generic_pt'}, 573)
  BYD_HAN_DMI_25 = BydPlatformConfig([BydCarDocs(name='Byd Han DMI 25', package='All', video=None, setup_video=None, min_steer_speed=None, min_enable_speed=None, auto_resume=None, merged=True, support_link='#upstream')], BydCarSpecs(mass=2080.0, wheelbase=2.92, steerRatio=15.0, centerToFrontRatio=0.44, minSteerSpeed=0.0, minEnableSpeed=-1.0, tireStiffnessFactor=1.0), {Bus.pt: 'byd_generic_pt'}, 565)
  BYD_HAN_DMI_22R = BydPlatformConfig([BydCarDocs(name='Byd Han DMI 22R', package='All', video=None, setup_video=None, min_steer_speed=None, min_enable_speed=None, auto_resume=None, merged=True, support_link='#upstream')], BydCarSpecs(mass=2080.0, wheelbase=2.92, steerRatio=15.0, centerToFrontRatio=0.44, minSteerSpeed=0.0, minEnableSpeed=-1.0, tireStiffnessFactor=1.0), {Bus.pt: 'byd_generic_pt'}, 701)
  BYD_HAN_DMI_22J = BydPlatformConfig([BydCarDocs(name='Byd Han DMI 22J', package='All', video=None, setup_video=None, min_steer_speed=None, min_enable_speed=None, auto_resume=None, merged=True, support_link='#upstream')], BydCarSpecs(mass=2080.0, wheelbase=2.92, steerRatio=15.0, centerToFrontRatio=0.44, minSteerSpeed=0.0, minEnableSpeed=-1.0, tireStiffnessFactor=1.0), {Bus.pt: 'byd_generic_pt'}, 607)
  BYD_TANG_DM = BydPlatformConfig([BydCarDocs(name='Byd Tang DM', package='All', video=None, setup_video=None, min_steer_speed=None, min_enable_speed=None, auto_resume=None, merged=True, support_link='#upstream')], BydCarSpecs(mass=2250.0, wheelbase=2.82, steerRatio=15.0, centerToFrontRatio=0.44, minSteerSpeed=0.0, minEnableSpeed=-1.0, tireStiffnessFactor=1.0), {Bus.pt: 'byd_generic_pt'}, 0)
  BYD_TANG_DMI_21 = BydPlatformConfig([BydCarDocs(name='Byd Tang DMI 21', package='All', video=None, setup_video=None, min_steer_speed=None, min_enable_speed=None, auto_resume=None, merged=True, support_link='#upstream')], BydCarSpecs(mass=2250.0, wheelbase=2.82, steerRatio=15.0, centerToFrontRatio=0.44, minSteerSpeed=0.0, minEnableSpeed=-1.0, tireStiffnessFactor=1.0), {Bus.pt: 'byd_generic_pt'}, 1077)
  BYD_TANG_DMP_22 = BydPlatformConfig([BydCarDocs(name='Byd Tang DMP 22', package='All', video=None, setup_video=None, min_steer_speed=None, min_enable_speed=None, auto_resume=None, merged=True, support_link='#upstream')], BydCarSpecs(mass=2445.0, wheelbase=2.82, steerRatio=15.0, centerToFrontRatio=0.6, minSteerSpeed=0.0, minEnableSpeed=-1.0, tireStiffnessFactor=1.0), {Bus.pt: 'byd_generic_pt'}, 701)
  BYD_TANG_DMP_23 = BydPlatformConfig([BydCarDocs(name='Byd Tang DMP 23', package='All', video=None, setup_video=None, min_steer_speed=None, min_enable_speed=None, auto_resume=None, merged=True, support_link='#upstream')], BydCarSpecs(mass=2445.0, wheelbase=2.82, steerRatio=15.0, centerToFrontRatio=0.6, minSteerSpeed=0.0, minEnableSpeed=-1.0, tireStiffnessFactor=1.0), {Bus.pt: 'byd_generic_pt'}, 565)
  BYD_TANG_DMI_24 = BydPlatformConfig([BydCarDocs(name='Byd Tang DMI 24', package='All', video=None, setup_video=None, min_steer_speed=None, min_enable_speed=None, auto_resume=None, merged=True, support_link='#upstream')], BydCarSpecs(mass=2250.0, wheelbase=2.82, steerRatio=15.0, centerToFrontRatio=0.44, minSteerSpeed=0.0, minEnableSpeed=-1.0, tireStiffnessFactor=1.0), {Bus.pt: 'byd_generic_pt'}, 565)
  BYD_SONG_PLUS_DMI_21 = BydPlatformConfig([BydCarDocs(name='Byd Song Plus DMI 21', package='All', video=None, setup_video=None, min_steer_speed=None, min_enable_speed=None, auto_resume=None, merged=True, support_link='#upstream')], BydCarSpecs(mass=1785.0, wheelbase=2.765, steerRatio=15.0, centerToFrontRatio=0.44, minSteerSpeed=0.0, minEnableSpeed=-1.0, tireStiffnessFactor=1.0), {Bus.pt: 'byd_generic_pt'}, 4)
  BYD_SONG_PLUS_DMI_22 = BydPlatformConfig([BydCarDocs(name='Byd Song Plus DMI 22', package='All', video=None, setup_video=None, min_steer_speed=None, min_enable_speed=None, auto_resume=None, merged=True, support_link='#upstream')], BydCarSpecs(mass=1785.0, wheelbase=2.765, steerRatio=15.0, centerToFrontRatio=0.44, minSteerSpeed=0.0, minEnableSpeed=-1.0, tireStiffnessFactor=1.0), {Bus.pt: 'byd_generic_pt'}, 564)
  BYD_SONG_PLUS_DMI_23 = BydPlatformConfig([BydCarDocs(name='Byd Song Plus DMI 23', package='All', video=None, setup_video=None, min_steer_speed=None, min_enable_speed=None, auto_resume=None, merged=True, support_link='#upstream')], BydCarSpecs(mass=1785.0, wheelbase=2.765, steerRatio=15.0, centerToFrontRatio=0.44, minSteerSpeed=0.0, minEnableSpeed=-1.0, tireStiffnessFactor=1.0), {Bus.pt: 'byd_generic_pt'}, 4)
  # 宋 PLUS 5G DM-i 2022：指纹来自第三方移植包实测（205 条报文），车体参数沿用同平台 宋 PLUS DM-i 22，
  # flags 亦沿用 564（ALT_INDICATOR | BCM_SEAL | ALT_ACC_EPS | ALT_PCM_BTN）。
  BYD_SONG_PLUS_5G_DMI_22 = BydPlatformConfig([BydCarDocs(name='Byd Song Plus 5G DMI 22', package='All', video=None, setup_video=None, min_steer_speed=None, min_enable_speed=None, auto_resume=None, merged=True, support_link='#upstream')], BydCarSpecs(mass=1785.0, wheelbase=2.765, steerRatio=15.0, centerToFrontRatio=0.44, minSteerSpeed=0.0, minEnableSpeed=-1.0, tireStiffnessFactor=1.0), {Bus.pt: 'byd_generic_pt'}, 564)
  BYD_SONG_PRO_DMI_22 = BydPlatformConfig([BydCarDocs(name='Byd Song Pro DMI 22', package='All', video=None, setup_video=None, min_steer_speed=None, min_enable_speed=None, auto_resume=None, merged=True, support_link='#upstream')], BydCarSpecs(mass=1785.0, wheelbase=2.712, steerRatio=15.0, centerToFrontRatio=0.44, minSteerSpeed=0.0, minEnableSpeed=-1.0, tireStiffnessFactor=1.0), {Bus.pt: 'byd_generic_pt'}, 0)
  BYD_SONG_L_DMI_24 = BydPlatformConfig([BydCarDocs(name='Byd Song L DMI 24', package='All', video=None, setup_video=None, min_steer_speed=None, min_enable_speed=None, auto_resume=None, merged=True, support_link='#upstream')], BydCarSpecs(mass=2000.0, wheelbase=2.782, steerRatio=15.0, centerToFrontRatio=0.44, minSteerSpeed=0.0, minEnableSpeed=-1.0, tireStiffnessFactor=1.0), {Bus.pt: 'byd_generic_pt'}, 3799)
  BYD_QIN_PLUS_DMI_23 = BydPlatformConfig([BydCarDocs(name='Byd Qin Plus DMI 23', package='All', video=None, setup_video=None, min_steer_speed=None, min_enable_speed=None, auto_resume=None, merged=True, support_link='#upstream')], BydCarSpecs(mass=1580.0, wheelbase=2.718, steerRatio=15.0, centerToFrontRatio=0.44, minSteerSpeed=0.0, minEnableSpeed=-1.0, tireStiffnessFactor=1.0), {Bus.pt: 'byd_generic_pt'}, 0)
  BYD_QIN_L_DMI = BydPlatformConfig([BydCarDocs(name='Byd Qin L DMI', package='All', video=None, setup_video=None, min_steer_speed=None, min_enable_speed=None, auto_resume=None, merged=True, support_link='#upstream')], BydCarSpecs(mass=2036.0, wheelbase=2.9, steerRatio=19.0, centerToFrontRatio=0.44, minSteerSpeed=0.0, minEnableSpeed=-1.0, tireStiffnessFactor=1.0), {Bus.pt: 'byd_generic_pt'}, 3671)
  BYD_SEAL_06_DMI = BydPlatformConfig([BydCarDocs(name='Byd Seal 06 DMI', package='All', video=None, setup_video=None, min_steer_speed=None, min_enable_speed=None, auto_resume=None, merged=True, support_link='#upstream')], BydCarSpecs(mass=2000.0, wheelbase=2.782, steerRatio=15.0, centerToFrontRatio=0.44, minSteerSpeed=0.0, minEnableSpeed=-1.0, tireStiffnessFactor=1.0), {Bus.pt: 'byd_generic_pt'}, 3799)
  BYD_QIN_PRO = BydPlatformConfig([BydCarDocs(name='Byd Qin Pro', package='All', video=None, setup_video=None, min_steer_speed=None, min_enable_speed=None, auto_resume=None, merged=True, support_link='#upstream')], BydCarSpecs(mass=2250.0, wheelbase=2.82, steerRatio=15.0, centerToFrontRatio=0.44, minSteerSpeed=0.0, minEnableSpeed=-1.0, tireStiffnessFactor=1.0), {Bus.pt: 'byd_generic_pt'}, 0)
  BYD_YUAN_PLUS_DMI_22 = BydPlatformConfig([BydCarDocs(name='Byd Yuan Plus DMI 22', package='All', video=None, setup_video=None, min_steer_speed=None, min_enable_speed=None, auto_resume=None, merged=True, support_link='#upstream')], BydCarSpecs(mass=1625.0, wheelbase=2.72, steerRatio=15.0, centerToFrontRatio=0.44, minSteerSpeed=0.0, minEnableSpeed=-1.0, tireStiffnessFactor=1.0), {Bus.pt: 'byd_generic_pt'}, 565)
  BYD_SEAL_23 = BydPlatformConfig([BydCarDocs(name='Byd Seal 23', package='All', video=None, setup_video=None, min_steer_speed=None, min_enable_speed=None, auto_resume=None, merged=True, support_link='#upstream')], BydCarSpecs(mass=2150.0, wheelbase=2.92, steerRatio=15.0, centerToFrontRatio=0.6, minSteerSpeed=0.0, minEnableSpeed=-1.0, tireStiffnessFactor=1.0), {Bus.pt: 'byd_generic_pt'}, 855)
  BYD_SEAL_EV_22 = BydPlatformConfig([BydCarDocs(name='Byd Seal EV 22', package='All', video=None, setup_video=None, min_steer_speed=None, min_enable_speed=None, auto_resume=None, merged=True, support_link='#upstream')], BydCarSpecs(mass=2695.0, wheelbase=3.11, steerRatio=17.0, centerToFrontRatio=0.6, minSteerSpeed=0.0, minEnableSpeed=-1.0, tireStiffnessFactor=1.0), {Bus.pt: 'byd_generic_pt'}, 1623)
  BYD_SEAL_07_DMI = BydPlatformConfig([BydCarDocs(name='Byd Seal 07 DMI', package='All', video=None, setup_video=None, min_steer_speed=None, min_enable_speed=None, auto_resume=None, merged=True, support_link='#upstream')], BydCarSpecs(mass=2695.0, wheelbase=3.11, steerRatio=17.0, centerToFrontRatio=0.6, minSteerSpeed=0.0, minEnableSpeed=-1.0, tireStiffnessFactor=1.0), {Bus.pt: 'byd_generic_pt'}, 1623)
  BYD_FRIGATE_07_DMI = BydPlatformConfig([BydCarDocs(name='Byd Frigate 07 DMI', package='All', video=None, setup_video=None, min_steer_speed=None, min_enable_speed=None, auto_resume=None, merged=True, support_link='#upstream')], BydCarSpecs(mass=2266.0, wheelbase=2.82, steerRatio=19.0, centerToFrontRatio=0.44, minSteerSpeed=0.0, minEnableSpeed=-1.0, tireStiffnessFactor=1.0), {Bus.pt: 'byd_generic_pt'}, 3671)
  BYD_TENGSHI_D9_22R = BydPlatformConfig([BydCarDocs(name='Byd Tengshi D9 22R', package='All', video=None, setup_video=None, min_steer_speed=None, min_enable_speed=None, auto_resume=None, merged=True, support_link='#upstream')], BydCarSpecs(mass=2695.0, wheelbase=3.11, steerRatio=17.0, centerToFrontRatio=0.6, minSteerSpeed=0.0, minEnableSpeed=-1.0, tireStiffnessFactor=1.0), {Bus.pt: 'byd_generic_pt'}, 1751)
  BYD_TENGSHI_D9_22 = BydPlatformConfig([BydCarDocs(name='Byd Tengshi D9 22', package='All', video=None, setup_video=None, min_steer_speed=None, min_enable_speed=None, auto_resume=None, merged=True, support_link='#upstream')], BydCarSpecs(mass=2695.0, wheelbase=3.11, steerRatio=17.0, centerToFrontRatio=0.6, minSteerSpeed=0.0, minEnableSpeed=-1.0, tireStiffnessFactor=1.0), {Bus.pt: 'byd_generic_pt'}, 1623)
  BYD_TENGSHI_D9_24 = BydPlatformConfig([BydCarDocs(name='Byd Tengshi D9 24', package='All', video=None, setup_video=None, min_steer_speed=None, min_enable_speed=None, auto_resume=None, merged=True, support_link='#upstream')], BydCarSpecs(mass=2695.0, wheelbase=3.11, steerRatio=17.0, centerToFrontRatio=0.6, minSteerSpeed=0.0, minEnableSpeed=-1.0, tireStiffnessFactor=1.0), {Bus.pt: 'byd_generic_pt'}, 1623)

class DBC(dict):
  def __missing__(self, key):
    return {Bus.pt: 'byd_generic_pt'}

DBC = DBC({car: {Bus.pt: 'byd_generic_pt'} for car in CAR})

FW_QUERY_CONFIG = FwQueryConfig(
  fw_version_regex=br"[\x00-\xff]{8}",
  requests=[
  Request([b'>\x00', b'"\xf1\x81'], [b'~\x00', b'b\xf1\x81'], whitelist_ecus=[Ecu.eps], rx_offset=0x8, bus=0),
  Request([b'>\x00', b'"\xf1\x81'], [b'~\x00', b'b\xf1\x81'], whitelist_ecus=[Ecu.adas, Ecu.fwdCamera], rx_offset=0x8, bus=2),
])

PLATFORM_HAN_DMEV = {CAR.BYD_HAN_DM_20, CAR.BYD_HAN_EV_20}
PLATFORM_HAN_DMI = {CAR.BYD_HAN_DMI_22, CAR.BYD_HAN_DMI_22R, CAR.BYD_HAN_DMI_25, CAR.BYD_TANG_DMP_22, CAR.BYD_TANG_DMP_23, CAR.BYD_YUAN_PLUS_DMI_22}
PLATFORM_TANG_DM = {CAR.BYD_QIN_PRO, CAR.BYD_TANG_DM}
PLATFORM_TANG_DMI = {CAR.BYD_SONG_PLUS_5G_DMI_22, CAR.BYD_SONG_PLUS_DMI_22, CAR.BYD_SONG_PLUS_DMI_23, CAR.BYD_TANG_DMI_21, CAR.BYD_TANG_DMI_24}
PLATFORM_SONG_PRO = {CAR.BYD_SONG_PRO_DMI_22}
PLATFORM_SONG_PLUS_DMI = {CAR.BYD_SONG_PLUS_DMI_21, CAR.BYD_SONG_PLUS_DMI_23}
PLATFORM_QIN_PLUS_DMI = {CAR.BYD_QIN_PLUS_DMI_23}
PLATFORM_QIN_SEAL06 = {CAR.BYD_QIN_L_DMI}
PLATFORM_YUAN_PLUS_DMI_ATTO3 = set()
PLATFORM_SEAL = {CAR.BYD_SEAL_23}
PLATFORM_TENGSHI = {CAR.BYD_FRIGATE_07_DMI, CAR.BYD_HAN_DMI_22J, CAR.BYD_SEAL_06_DMI, CAR.BYD_SEAL_07_DMI, CAR.BYD_SEAL_EV_22, CAR.BYD_SONG_L_DMI_24, CAR.BYD_TENGSHI_D9_22, CAR.BYD_TENGSHI_D9_22R, CAR.BYD_TENGSHI_D9_24}
PT_RADAR_100 = {CAR.BYD_HAN_DMI_22, CAR.BYD_HAN_DMI_22R, CAR.BYD_HAN_DMI_25, CAR.BYD_TANG_DMP_22, CAR.BYD_TANG_DMP_23, CAR.BYD_TENGSHI_D9_22, CAR.BYD_TENGSHI_D9_22R, CAR.BYD_YUAN_PLUS_DMI_22}
PT_RADAR_80 = {CAR.BYD_SEAL_07_DMI, CAR.BYD_SEAL_EV_22, CAR.BYD_TENGSHI_D9_24}
PT_RADAR_CAR = {CAR.BYD_HAN_DMI_22, CAR.BYD_HAN_DMI_22R, CAR.BYD_HAN_DMI_25, CAR.BYD_HAN_DM_20, CAR.BYD_HAN_EV_20, CAR.BYD_TANG_DMP_22, CAR.BYD_TANG_DMP_23, CAR.BYD_TENGSHI_D9_22, CAR.BYD_TENGSHI_D9_22R, CAR.BYD_YUAN_PLUS_DMI_22}
RADAR_CAR = {CAR.BYD_QIN_PRO, CAR.BYD_TANG_DM}
TORQUE_LAT_CAR = {CAR.BYD_HAN_DMI_22, CAR.BYD_HAN_DMI_22R, CAR.BYD_HAN_DMI_25, CAR.BYD_HAN_DM_20, CAR.BYD_HAN_EV_20, CAR.BYD_QIN_PRO, CAR.BYD_SONG_PLUS_5G_DMI_22, CAR.BYD_SONG_PLUS_DMI_21, CAR.BYD_SONG_PLUS_DMI_22, CAR.BYD_SONG_PLUS_DMI_23, CAR.BYD_SONG_PRO_DMI_22, CAR.BYD_TANG_DM, CAR.BYD_TANG_DMI_21, CAR.BYD_TANG_DMI_24, CAR.BYD_TANG_DMP_22, CAR.BYD_TANG_DMP_23, CAR.BYD_YUAN_PLUS_DMI_22}
EXP_LONG_CAR = {CAR.BYD_FRIGATE_07_DMI, CAR.BYD_HAN_DMI_22, CAR.BYD_HAN_DMI_22J, CAR.BYD_HAN_DMI_22R, CAR.BYD_HAN_DMI_25, CAR.BYD_HAN_DM_20, CAR.BYD_HAN_EV_20, CAR.BYD_QIN_L_DMI, CAR.BYD_QIN_PRO, CAR.BYD_SEAL_06_DMI, CAR.BYD_SEAL_07_DMI, CAR.BYD_SEAL_23, CAR.BYD_SEAL_EV_22, CAR.BYD_SONG_L_DMI_24, CAR.BYD_SONG_PLUS_5G_DMI_22, CAR.BYD_SONG_PLUS_DMI_21, CAR.BYD_SONG_PLUS_DMI_22, CAR.BYD_SONG_PLUS_DMI_23, CAR.BYD_SONG_PRO_DMI_22, CAR.BYD_TANG_DM, CAR.BYD_TANG_DMI_21, CAR.BYD_TANG_DMI_24, CAR.BYD_TANG_DMP_22, CAR.BYD_TANG_DMP_23, CAR.BYD_TENGSHI_D9_22, CAR.BYD_TENGSHI_D9_22R, CAR.BYD_TENGSHI_D9_24, CAR.BYD_YUAN_PLUS_DMI_22}
