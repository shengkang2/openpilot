"""吉利车辆控制器。"""
import numpy as np
from opendbc.can.packer import CANPacker
from opendbc.car import Bus, DT_CTRL, rate_limit, structs
from opendbc.car.lateral import apply_driver_steer_torque_limits
from opendbc.car.interfaces import CarControllerBase
from opendbc.geely_port.geelycan import (create_can_steer_command, create_acc_command,
                                         create_gas_command, create_torque_command)
from opendbc.geely_port.values import CarControllerParams

VisualAlert = structs.CarControl.HUDControl.VisualAlert
LongCtrlState = structs.CarControl.Actuators.LongControlState


class CarControllerConstants:
  """控制器常量定义。"""
  # 驾驶员干预检测
  DRIVER_BRAKE_THRESHOLD = 0.01  # 刹车踏板阈值
  DRIVER_GAS_THRESHOLD = 0.05    # 油门踏板阈值 (提高阈值减少误触发)

  # 纵向控制参数
  GAS_BRAKE_HYST_ON = 0.01      # 激活刹车/油门的滞后阈值 (降低阈值，让轻微刹车也能生效)
  GAS_BRAKE_HYST_OFF = 0.005    # 停用刹车/油门的滞后阈值
  GAS_BRAKE_HYST_GAP = 0.01     # 刹车命令变化的最小间隙

  # 加速度速率限制 (参考Toyota, 放宽6倍避免顿挫)
  ACCEL_WINDUP_LIMIT = 4.0 * DT_CTRL * 3    # 加速时限制: 0.24 m/s² per frame
  ACCEL_WINDDOWN_LIMIT = -4.0 * DT_CTRL * 3  # 减速时限制: -0.24 m/s² per frame

  # 气动刹车补偿参数
  WIND_BRAKE_SPEEDS = [0.0, 2.3, 35.0]  # 速度断点(km/h)
  WIND_BRAKE_VALUES = [0.001, 0.002, 0.15]  # 气动刹车值

  # Driver torque threshold (reference: Toyota/Honda approach) / 驾驶员扭矩阈值（参考Toyota/Honda做法）
  MAX_DRIVER_TORQUE_ALLOWANCE = 200  # Driver torque limit (above this: disable control) / 驾驶员扭矩限制（超过此值：禁用控制）


class CarController(CarControllerBase):
  """吉利车辆控制器，支持转向和纵向控制。"""

  def __init__(self, dbc_names, CP, CP_SP):
    CarControllerBase.__init__(self, dbc_names, CP, CP_SP)
    self.params = CarControllerParams(CP)
    self.packer = CANPacker(dbc_names[Bus.pt])

    # 转向控制状态
    self.apply_torque_last = 0
    self.counter = 0
    self.last_steer_frame = 0
    self.last_acc_frame = 0

    # Anti-Nag: 防止"手离方向盘"警告 (参考大众VW实现)
    # 吉利摄像头通过监测转向角变化来检测手是否在方向盘上
    # 原车警告机制: 30秒警告 → 60秒严重警告 → 退出控制
    # 当转向命令保持相同超过一定时间，微调扭矩值以产生角度变化
    self.steer_same_torque_frame = 0
    self.STEER_TIME_STUCK_TORQUE = 10.0  # 秒，30秒警告前触发3次

    # 纵向控制状态
    self.braking = False
    self.brake_steady = 0.0
    self.gas_steady = 0.0
    self.last_accel = 0.0

    # 原厂转向恢复状态
    self.last_steer_disable_time = 0.0
    self.prev_steer_enabled = False

  def _compute_gas_brake(self, accel, speed):
    """计算油门和刹车值，包含气动刹车补偿。

    参数:
      accel: 期望加速度 (m/s²)
      speed: 当前速度 (m/s)

    返回:
      tuple: (gas_value, brake_value) - 油门和刹车值 (0.0-1.0)
    """
    # 气动刹车补偿 - 高速度时空气阻力产生的减速度
    wind_brake = np.interp(speed, CarControllerConstants.WIND_BRAKE_SPEEDS,
                          CarControllerConstants.WIND_BRAKE_VALUES)

    # 计算净加速度（减去气动刹车）
    net_accel = accel - wind_brake

    # 将加速度转换为归一化的油门/刹车值 (0.0-1.0)
    # 油门: 正加速度映射到 [0, ACCEL_MAX] -> [0, 1.0]
    # 刹车: 负加速度映射到 [ACCEL_MIN, 0] -> [0, 1.0]
    if net_accel > 0:
      gas_value = min(net_accel / self.params.ACCEL_MAX, 1.0)
      brake_value = 0.0
    else:
      gas_value = 0.0
      brake_value = min(-net_accel / abs(self.params.ACCEL_MIN), 1.0)

    return gas_value, brake_value

  def _apply_gas_brake_hysteresis(self, gas, brake):
    """对油门和刹车命令应用滞后控制，避免闪烁。

    参数:
      gas: 原始油门值 (0.0-1.0)
      brake: 原始刹车值 (0.0-1.0)

    返回:
      tuple: (gas, brake, braking, gas_steady, brake_steady)
    """
    # 刹车滞后逻辑
    if (brake < CarControllerConstants.GAS_BRAKE_HYST_ON and not self.braking) or \
       brake < CarControllerConstants.GAS_BRAKE_HYST_OFF:
      brake = 0.0
    self.braking = brake > 0.0

    # 刹车稳态控制 - 避免小幅振荡
    if brake == 0.0:
      self.brake_steady = 0.0
    elif brake > self.brake_steady + CarControllerConstants.GAS_BRAKE_HYST_GAP:
      self.brake_steady = brake - CarControllerConstants.GAS_BRAKE_HYST_GAP
    elif brake < self.brake_steady - CarControllerConstants.GAS_BRAKE_HYST_GAP:
      self.brake_steady = brake + CarControllerConstants.GAS_BRAKE_HYST_GAP
    brake = self.brake_steady

    # 油门滞后逻辑（类似刹车）
    gas_hyst_on = CarControllerConstants.GAS_BRAKE_HYST_ON
    gas_hyst_off = CarControllerConstants.GAS_BRAKE_HYST_OFF
    gas_hyst_gap = CarControllerConstants.GAS_BRAKE_HYST_GAP

    if gas < gas_hyst_on:
      gas = 0.0

    # 油门稳态控制
    if gas == 0.0:
      self.gas_steady = 0.0
    elif gas > self.gas_steady + gas_hyst_gap:
      self.gas_steady = gas - gas_hyst_gap
    elif gas < self.gas_steady - gas_hyst_gap:
      self.gas_steady = gas + gas_hyst_gap
    gas = self.gas_steady

    return gas, brake, self.braking, self.gas_steady, self.brake_steady

  # 驾驶员干预检查由Safety层(Panda)自动处理:
  # - Safety层会检查gas_pressed_prev，自动阻止纵向控制
  # - 横向控制通过CC.latActive/longActive状态管理
  # - 参考Honda/Toyota/GM实现，carcontroller不需要单独检查驾驶员干预

  def _handle_longitudinal_control(self, CC, CS, can_sends):
    """处理纵向控制逻辑。

    参数:
      CC: CarControl对象
      CS: CarState对象
      can_sends: CAN消息列表
    """
    # 纵向控制状态判断：
    # - CC.enabled: ACC开启（踩油门覆盖时仍为True）
    # - CC.longActive: OP正在控车（踩油门覆盖时为False）
    # - CC.cruiseControl.override: 踩油门覆盖中（enabled=True但longActive=False）
    #
    # 关键：踩油门覆盖时（override=True），仍需发送ACC_CMD，只是accel=0
    long_active = self.CP.openpilotLongitudinalControl and CC.longActive
    gas_override = self.CP.openpilotLongitudinalControl and CC.enabled and CS.out.gasPressed and not CC.longActive

    if long_active:
      # 控车时：计算加速度命令
      accel = CC.actuators.accel

      # 用户踩油门时accel=0，让用户控制
      if CS.out.gasPressed:
        accel = 0.0  # 停止发送加速度命令，让用户自由控制

      # 跟车距离由 OP personality 系统控制 (selfdrived.py)
      # 按原车距离按钮会触发 gapAdjustCruise 事件，自动切换 personality

      # 速率限制加速度变化 (参考Toyota的generous rate limit，避免顿挫)
      accel = rate_limit(accel, self.last_accel,
                        CarControllerConstants.ACCEL_WINDDOWN_LIMIT,
                        CarControllerConstants.ACCEL_WINDUP_LIMIT)
      self.last_accel = accel

      # 计算油门和刹车值
      gas_value, brake_value = self._compute_gas_brake(accel, CS.out.vEgo)

      # 应用滞后控制
      gas_value, brake_value, _, _, _ = self._apply_gas_brake_hysteresis(gas_value, brake_value)

      # 设置使能标志
      # 关键修复：用户踩油门时禁用刹车，避免油门空转（参考GM at_full_stop逻辑）
      gas_enabled = gas_value > 0
      brake_enabled = brake_value > 0 and not CS.out.gasPressed
    else:
      # 不控车时：发送零值 (参考Honda L236-238)
      accel = 0.0
      gas_value = 0.0
      brake_value = 0.0
      gas_enabled = False
      brake_enabled = False

    # 纵向控制消息发送逻辑（和SP一致）：
    # - 只要开启了纵向控制，就始终发送ACC_CMD
    # - 不控车时：使用原车摄像头数据（long_active=False）
    # - 控车时：修改加速度等字段（long_active=True）
    # 这样openpilot代替原车摄像头发送消息，保持消息连续性
    should_send_acc = self.CP.openpilotLongitudinalControl

    if should_send_acc:
      can_sends.append(create_acc_command(
        self.packer,
        accel,                           # 控车时是计算值，覆盖时是0
        long_active or gas_override,     # 控车标志（覆盖时也算控车）
        CS.cam_acc_msg,                  # 原车摄像头数据
        self.counter,                    # 计数器
        gas_override,                    # 油门覆盖标志
        CS.out.standstill                # 车辆静止标志
      ))

      # 发送直接执行器控制命令（只在真正控车时，覆盖时不发）
      if long_active:
        can_sends.append(create_gas_command(
          self.packer,
          gas_value,
          gas_enabled,
          self.frame % 16
        ))

        can_sends.append(create_torque_command(
          self.packer,
          brake_value,
          brake_enabled,
          self.frame % 16
        ))

  def update(self, CC, CC_SP, CS, now_nanos):
    """生成车辆控制的CAN消息。

    参数:
      CC: 包含执行器命令的CarControl消息
      CS: 包含当前车辆状态的CarState
      now_nanos: 当前时间戳(纳秒)

    返回:
      tuple: (new_actuators, can_sends) - 更新后的执行器和CAN消息
    """
    can_sends = []
    actuators = CC.actuators

    # === 转向控制 ===
    # 横向控制激活状态
    # 注释掉驾驶员扭矩过大退出控制的逻辑，允许大幅度转动
    steer_enabled = CC.latActive  # and abs(CS.out.steeringTorque) < CarControllerConstants.MAX_DRIVER_TORQUE_ALLOWANCE
    new_steer = int(round(actuators.torque * self.params.STEER_MAX))

    # 打灯变道处理：移除转向力度降低
    # 注意：之前设置为0.1会导致变道时方向盘几乎不转动，车辆冲出车道
    # 现在保持正常转向力度，让车辆能够正常变道
    # blinker_on = CS.out.leftBlinker or CS.out.rightBlinker
    # if blinker_on and steer_enabled:
    #   new_steer = int(new_steer * 0.1)

    # 驾驶员扭矩限制
    apply_steer = apply_driver_steer_torque_limits(new_steer, self.apply_torque_last,
                                                    CS.out.steeringTorque, self.params)

    # Anti-Nag: 防止"手离方向盘"警告 (参考大众VW实现)
    # 吉利摄像头通过监测转向角变化来检测手是否在方向盘上
    # 当转向命令保持相同超过1.9秒，微调扭矩值±1以产生微小角度变化
    if steer_enabled:
      if self.apply_torque_last == apply_steer:
        self.steer_same_torque_frame += self.params.STEER_STEP
        if self.steer_same_torque_frame > self.STEER_TIME_STUCK_TORQUE / DT_CTRL:
          # 微调扭矩值，方向与当前扭矩相反（如果扭矩为0则加1）
          if apply_steer != 0:
            apply_steer -= (1, -1)[apply_steer < 0]
          else:
            apply_steer = 1  # 扭矩为0时加1
          self.steer_same_torque_frame = 0
      else:
        self.steer_same_torque_frame = 0
    else:
      self.steer_same_torque_frame = 0

    # 原厂转向渐变恢复
    import time
    if not steer_enabled and self.prev_steer_enabled:
      self.last_steer_disable_time = time.monotonic()
    self.prev_steer_enabled = steer_enabled

    # 渐变恢复原厂控制
    if not steer_enabled and hasattr(CS, 'cam_lkas_msg'):
      stock_steer_cmd = CS.cam_lkas_msg.get('STEER_CMD', 0)
      if stock_steer_cmd > 0:
        elapsed = time.monotonic() - self.last_steer_disable_time
        mul = max(0.0, min(1.0, (elapsed - 0.55) / 0.5))
        steer_dir = CS.cam_lkas_msg.get('STEER_DIR', 0)
        apply_steer = int(stock_steer_cmd * (-1 if steer_dir else 1) * mul)
        apply_steer = apply_steer & ~1

    # 发送转向命令 - 50Hz
    if (self.frame - self.last_steer_frame) >= self.params.STEER_STEP:
      self.counter = (self.counter + 1) % 16

      can_sends.append(create_can_steer_command(
        self.packer,
        apply_steer,
        steer_enabled,
        CS.cam_lkas_msg,
        self.counter
      ))

      self.last_steer_frame = self.frame

    # === 纵向控制 ===
    if (self.frame - self.last_acc_frame) >= self.params.STEER_STEP:
      self._handle_longitudinal_control(CC, CS, can_sends)
      self.last_acc_frame = self.frame

    # === 更新状态 ===
    self.frame += 1
    self.apply_torque_last = apply_steer

    # === 创建反馈执行器 ===
    new_actuators = actuators.as_builder()
    new_actuators.torque = apply_steer / self.params.STEER_MAX
    new_actuators.torqueOutputCan = float(apply_steer)

    return new_actuators, can_sends
