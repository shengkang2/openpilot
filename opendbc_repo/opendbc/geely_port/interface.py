"""吉利车辆接口。"""
from opendbc.car import Bus, structs, get_safety_config
from opendbc.car.interfaces import CarInterfaceBase
from opendbc.geely_port.carstate import CarState
from opendbc.geely_port.carcontroller import CarController
from opendbc.geely_port.radar_interface import RadarInterface
from opendbc.geely_port.values import CAR, DBC, CarControllerParams, GeelyFlags
from opendbc.safety import ALTERNATIVE_EXPERIENCE
from openpilot.common.params import Params


class CarInterface(CarInterfaceBase):
  """吉利车辆接口，支持传统模式和实验模式。"""

  # openpilot框架的类属性
  CarState = CarState
  CarController = CarController
  RadarInterface = RadarInterface

  @staticmethod
  def get_pid_accel_limits(CP, current_speed, cruise_speed):
    """获取纵向控制的PID加速度限制。"""
    return CarControllerParams(CP).ACCEL_MIN, CarControllerParams(CP).ACCEL_MAX

  @staticmethod
  def _get_params(ret, candidate, fingerprint, car_fw, alpha_long, is_release, docs):
    """配置吉利车辆参数。"""
    ret.brand = "geely"
    ret.carFingerprint = candidate

    # 车辆规格
    ret.transmissionType = structs.CarParams.TransmissionType.automatic
    ret.radarUnavailable = Bus.radar not in DBC[candidate]

    # 转向配置
    ret.steerControlType = structs.CarParams.SteerControlType.torque
    ret.steerActuatorDelay = 0.1   # 转向延迟 (降低延迟提高响应速度，参考Honda)
    ret.steerLimitTimer = 0.1      # 限制计时器

    # 横向调优
    ret.lateralTuning.init('pid')

    # 纵向控制模式 - 参考Honda Bosch处理方式
    # 支持实验模式：允许用户在UI中切换E2E纵向控制
    ret.alphaLongitudinalAvailable = True  # 启用实验性纵向控制选项
    ret.openpilotLongitudinalControl = alpha_long  # 用户是否启用了实验性纵向

    # 始终使用 pcmCruise 模式：直接读取 PCM_BUTTONS 的设定速度，而不是自己处理按钮
    # 这样 OP 和车机的定速会保持同步（都是每次 +1 km/h）
    ret.pcmCruise = True

    # 安全配置 - 根据纵向控制状态设置safety参数
    # TODO(geely-port): 本分支的 car.capnp 里还没有 SafetyModel.geely，
    # panda 也没有 modes/geely.h。补齐这两处之前，这一行会抛 AttributeError，
    # 因此本包目前不注册到 opendbc/car/values.py（详见 README.md）。
    safety_param = 1 if ret.openpilotLongitudinalControl else 0
    ret.safetyConfigs = [get_safety_config(structs.CarParams.SafetyModel.geely, safety_param)]

    # 禁用油门脱离ACC (踩油门时不退出巡航 - 吉利支持GAS_OVERRIDE模式)
    ret.alternativeExperience = ALTERNATIVE_EXPERIENCE.DISABLE_DISENGAGE_ON_GAS

    # MADS (M-Advanced Driver Assistance System) 模式
    # 开启后，按下ACC自动激活转向；关闭后，需要额外按LFA按钮激活转向
    params = Params()
    if params.get_bool("EnableMADS"):
      ret.flags |= int(GeelyFlags.MADS_ENABLED)

    # 配置特定车辆参数
    if candidate == CAR.GEELY_BINYUE:
      # 转向扭矩限制
      ret.lateralParams.torqueBP = [0, 598]
      ret.lateralParams.torqueV = [0, 598]

      # 横向控制PID调优 - 对齐Proton参数
      ret.lateralTuning.pid.kpBP = [0., 25., 35., 40.]
      ret.lateralTuning.pid.kpV = [0.06, 0.18, 0.18, 0.19]  # 使用Proton的P增益
      ret.lateralTuning.pid.kiBP = [0., 20., 30.]
      ret.lateralTuning.pid.kiV = [0.04, 0.08, 0.16]  # 使用Proton的I增益
      ret.lateralTuning.pid.kf = 0.0000015  # 使用Proton的前馈增益

      # 纵向调优（对齐Proton参考设置）
      ret.longitudinalTuning.kpBP = [0., 5., 20.]
      ret.longitudinalTuning.kpV = [5.0, 3.6, 3.6]  # 与Proton保持一致
      ret.longitudinalTuning.kiBP = [0., 5., 20.]
      ret.longitudinalTuning.kiV = [1.5, 1.0, 1.0]  # 与Proton保持一致
      ret.longitudinalActuatorDelay = 0.5

      # 车辆动力学 - wheelbase/centerToFront/minEnableSpeed 等由 CarSpecs 自动设置
      ret.wheelSpeedFactor = 1.0

      # 启用功能
      ret.enableBsm = True  # 盲区监测

      # 低速和停车参数（关键：避免MPC在低速时失败）
      ret.stopAccel = -2.0          # 停车时的加速度 (m/s²)
      ret.vEgoStopping = 0.5        # 认为车辆正在停止的速度阈值 (m/s)
      ret.vEgoStarting = 0.5        # 认为车辆正在启动的速度阈值 (m/s)
      ret.stoppingDecelRate = 0.8   # 停车减速率 (m/s²/s)

      # 停止-继续自动恢复 - 仅在OP纵向控制启用时
      ret.autoResumeSng = ret.openpilotLongitudinalControl

    else:
      # 未知车辆 - 仅仪表盘摄像头
      ret.dashcamOnly = True
      ret.safetyConfigs = [get_safety_config(structs.CarParams.SafetyModel.noOutput)]

    return ret

  # 接口的其余部分使用基类实现
  # CarState和CarController将自动导入
