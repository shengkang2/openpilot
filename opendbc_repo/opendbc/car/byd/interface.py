#!/usr/bin/env python3
import os
from math import fabs, exp

from opendbc.car import get_safety_config, structs
from opendbc.car.common.conversions import Conversions as CV
from opendbc.car.byd.params_compat import Params
from opendbc.car.byd.carcontroller import CarController
from opendbc.car.byd.carstate import CarState
from opendbc.car.byd.radar_interface import RadarInterface
from opendbc.car.interfaces import CarInterfaceBase, TorqueFromLateralAccelCallbackType
from opendbc.car.byd.values import CAR, CanBus, BydFlags, BydSafetyFlags, TORQUE_LAT_CAR, EXP_LONG_CAR, PT_RADAR_CAR, RADAR_CAR, PLATFORM_SEAL, PLATFORM_TENGSHI, PLATFORM_QIN_SEAL06, PLATFORM_QIN_PLUS_DMI

from opendbc.car.byd.tuning import Tuning

ButtonType = structs.CarState.ButtonEvent.Type
GearShifter = structs.CarState.GearShifter
TransmissionType = structs.CarParams.TransmissionType
NetworkLocation = structs.CarParams.NetworkLocation

class CarInterface(CarInterfaceBase):
  CarState = CarState
  CarController = CarController
  RadarInterface = RadarInterface

  def torque_from_lateral_accel_siglin(self, lateral_acceleration: float,
                                        torque_params: structs.CarParams.LateralTorqueTuning) -> float:
    # sigmoid + linear curve, see community BYD tuning notes
    from math import exp

    def sig(val):
      # https://timvieira.github.io/blog/post/2014/02/11/exp-normalize-trick
      if val >= 0:
        return 1 / (1 + exp(-val)) - 0.5
      else:
        z = exp(val)
        return z / (1 + z) - 0.5

    a, b, c = Tuning.LAT_SIGLIN_TABLE
    steer_torque = (sig(lateral_acceleration * a) * b) + (lateral_acceleration * c)
    return float(steer_torque / torque_params.latAccelFactor)

  def torque_from_lateral_accel(self) -> TorqueFromLateralAccelCallbackType:
    if Params().get_bool("BydLatUseSiglin"):
      return self.torque_from_lateral_accel_siglin
    return self.torque_from_lateral_accel_linear

  @staticmethod
  def _get_params(ret: structs.CarParams, candidate, fingerprint, car_fw, alpha_long, is_release, docs) -> structs.CarParams:
    ret.brand = "byd"
    valid_safety_index = 0
    if Params().get_bool("UseRedPanda"):
      ret.safetyConfigs = [get_safety_config(structs.CarParams.SafetyModel.noOutput),get_safety_config(structs.CarParams.SafetyModel.byd)]
      valid_safety_index = 1
    else:
      ret.safetyConfigs = [get_safety_config(structs.CarParams.SafetyModel.byd)]

    ret.dashcamOnly = False

    if Params().get_bool("EnableExtRadar"):
      ret.radarUnavailable = False
    else:
      radar_car = candidate in (PT_RADAR_CAR | RADAR_CAR)
      ret.radarUnavailable = not radar_car

    ret.enableBsm = 0x418 in fingerprint[CanBus.ESC]
    ret.transmissionType = TransmissionType.direct

    if candidate in {CAR.BYD_TANG_DMP_22, CAR.BYD_HAN_DMI_22R}:
      ret.safetyConfigs[valid_safety_index].safetyParam |= BydSafetyFlags.ACC_CRUISEDISP.value
    elif candidate in (PLATFORM_TENGSHI | PLATFORM_QIN_SEAL06 | PLATFORM_QIN_PLUS_DMI):
      ret.safetyConfigs[valid_safety_index].safetyParam |= BydSafetyFlags.ANGLE_MODE.value
      if ret.flags & BydFlags.ALT_ACC_CURISE_MODE:
        ret.safetyConfigs[valid_safety_index].safetyParam |= BydSafetyFlags.ACC_CRUISEDISP.value
    elif candidate in PLATFORM_SEAL:
      ret.safetyConfigs[valid_safety_index].safetyParam |= BydSafetyFlags.ANGLE_MODE.value
      ret.safetyConfigs[valid_safety_index].safetyParam |= BydSafetyFlags.ACC_ON1.value
    else: #汉dm，唐dm，宋Pro
      pass

    if candidate in TORQUE_LAT_CAR:
      CarInterfaceBase.configure_torque_tune(candidate, ret.lateralTuning)
    else:
      ret.steerControlType = structs.CarParams.SteerControlType.angle
      ret.flags |= BydFlags.ANGLE_CONTROL.value

    ret.openpilotLongitudinalControl = candidate in EXP_LONG_CAR

    #car specified settings
    if candidate in TORQUE_LAT_CAR:
      ret.minEnableSpeed = -1.
      ret.minSteerSpeed = 0.1 * CV.KPH_TO_MS
      ret.autoResumeSng = True
      ret.stopAccel = -0.3
      ret.longitudinalActuatorDelay = 0.5
      ret.steerActuatorDelay = 0.2  # 转向执行器延迟，测量是0.4，但是在torqued.py里55行会加上0.2
      ret.steerLimitTimer = 0.6
    elif candidate in PLATFORM_QIN_SEAL06:
      ret.minEnableSpeed = -1.
      ret.minSteerSpeed = 0.
      ret.autoResumeSng = True
      ret.stopAccel = -0.3
      ret.longitudinalActuatorDelay = 0.5
      ret.steerActuatorDelay = 0.3
      ret.steerLimitTimer = 0.5
    elif candidate in (PLATFORM_SEAL | PLATFORM_TENGSHI):
      ret.minEnableSpeed = -1.
      ret.minSteerSpeed = 0.1 * CV.KPH_TO_MS
      ret.autoResumeSng = True
      ret.stopAccel = -0.3
      ret.longitudinalActuatorDelay = 0.5
      ret.steerActuatorDelay = 0.1  # 转向执行器延迟，测量是0.4，但是在torqued.py里55行会加上0.2
      ret.steerLimitTimer = 1.0
    else:
      ret.dashcamOnly = True


    return ret
