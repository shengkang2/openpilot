#!/usr/bin/env python3
"""BYD 控制增强模块（可选，默认关闭）

代码来源
--------
社区 mypilot BYD 移植包（yuluoqingcheng/openpilot-mypilot-community-dbcall）中
两套本分支没有的实现：

  * ``byd源码/carcontroller.py``
      - TTC 预测性制动（前车距离历史 + 相对速率滑动均值 -> 物理减速度融合）
      - 智能跟车 PI 控制器（距离误差 + 积分限幅，取与规划器更保守的一方）
      - 0 帧起步（standstill_timer + 前车移动检测 + 软起步插值）
      - 刹车踏板抑制 LKAS（带按下/释放防抖计数）
  * ``byd2/carcontroller.py``（该文件其实基于 Honda 控制器，只取其中的横向平滑管线）
      - 速度相关死区 / 滑动均值 / 低通 / 直路判定锁定 / 符号翻转抑制
      - 预瞄 / 居中收敛 / 变化率缩放 / 输出死区与迟滞

移植时的改动
------------
1. 剔除 ``server_connect.py`` 在线授权检查（该包会在 carstate 里上报设备序列号
   到硬编码 IP 换取 license），本模块不含任何网络请求。
2. 去掉 Honda 专属逻辑（PCM/gas interceptor/brake pump 等），只保留纯算法。
3. 输入输出对齐本分支的接口：横向用归一化力矩 [-1, 1] 与 m/s 车速；
   纵向用 m/s^2、CS.out.standstill、CS.mrr_leading_dist。
4. 所有功能由 ``tuning.Tuning`` 里的开关控制，默认全部关闭，行为与打补丁前一致。
5. 原实现的 TTC 控制周期硬编码 0.05s，这里改为按实际调用周期传入 dt。

注意：这些参数来自社区实车（汉/宋/唐）调校，本分支并未实车验证，
开启前请先在封闭场地逐项确认。
"""
from collections import deque

import numpy as np

from opendbc.car import DT_CTRL, structs

LongCtrlState = structs.CarControl.Actuators.LongControlState

# ---------------------------------------------------------------------------
# 横向平滑参数（来自 byd2/carcontroller.py，作用于归一化力矩）
# ---------------------------------------------------------------------------
STEER_DEADZONE_BP = [0.0, 6.0, 15.0, 28.0, 38.0]   # m/s
STEER_DEADZONE_V = [0.042, 0.034, 0.026, 0.020, 0.016]

STEER_MA_SIZE = 16                                 # ~160ms @ 100Hz

STEER_LPF_ALPHA_BP = [0.0, 8.0, 18.0, 30.0, 40.0]
STEER_LPF_ALPHA_V = [0.10, 0.14, 0.20, 0.24, 0.18]

STEER_RATE_SCALE_BP = [0.0, 10.0, 22.0, 32.0, 40.0]
STEER_RATE_SCALE_V = [0.28, 0.38, 0.50, 0.62, 0.48]

STEER_PREVIEW_GAIN = 0.08
STEER_PREVIEW_MAX = 0.05
STEER_PREVIEW_MIN_TORQUE = 0.060

STEER_STRAIGHT_THRESH = 0.042
STEER_STRAIGHT_FRAMES = 4
STEER_STRAIGHT_LOCK_THRESH = 0.055
STEER_STRAIGHT_LPF_MAX = 0.06
STEER_STRAIGHT_RATE_MULT = 0.28
STEER_STRAIGHT_CENTER_PULL = 0.78

STEER_OSC_SIGN_CHANGES = 3
STEER_SIGN_FLIP_THRESH = 0.070

STEER_OUTPUT_DZ_BP = [0.0, 10.0, 25.0]
STEER_OUTPUT_DZ_V = [0.022, 0.016, 0.012]
STEER_OUTPUT_HYST = 0.008

# ---------------------------------------------------------------------------
# 纵向增强参数（来自 byd源码/carcontroller.py）
# ---------------------------------------------------------------------------
LONG_LEAD_HISTORY_SIZE = 15
LONG_LEAD_RATE_HISTORY_SIZE = 10
LONG_ACCEL_SMOOTH_FACTOR = 0.25
LONG_STANDSTILL_START_THRESHOLD = 5        # 帧
LONG_TTC_HORIZON = 3.0                     # s
LONG_PREDICTIVE_BRAKE_SAFETY_FACTOR = 0.4  # s
LONG_STANDSTILL_LEAD_MOVE_THRESHOLD = 0.2  # m/s

LONG_PI_KP = 0.25
LONG_PI_KI = 0.03
LONG_TARGET_TIME_GAP = 1.8                 # s

BRAKE_INHIBIT_PRESSED_THRESHOLD = 3
BRAKE_INHIBIT_RELEASE_THRESHOLD = 5


def _apply_deadzone(x, dz):
  """|x| < dz 归零，否则平滑过渡"""
  if abs(x) <= dz:
    return 0.0
  return x - dz if x > 0 else x + dz


def _count_sign_changes(buf):
  """统计相邻样本符号翻转次数，用于检测左右振荡"""
  changes = 0
  prev = 0.0
  for x in buf:
    if prev != 0.0 and x != 0.0 and (prev * x) < 0.0:
      changes += 1
    if x != 0.0:
      prev = x
  return changes


class LateralSmoother:
  """归一化转向力矩平滑管线（仅力矩模式使用）

  流程：滑动均值 -> 速度死区 -> 直路判定 -> 条件预瞄 -> 低通
        -> 居中收敛 -> 变化率缩放 -> 输出死区/迟滞
  """

  def __init__(self, params):
    self.params = params
    self.torque_filtered = 0.0
    self.torque_target_last = 0.0
    self.raw_torque_ma = [0.0] * STEER_MA_SIZE
    self.raw_torque_ma_i = 0
    self.straight_frames = 0
    self.output_steady = 0.0
    self.last_torque = 0.0

  def reset(self):
    self.torque_filtered = 0.0
    self.torque_target_last = 0.0
    self.raw_torque_ma = [0.0] * STEER_MA_SIZE
    self.raw_torque_ma_i = 0
    self.straight_frames = 0
    self.output_steady = 0.0
    self.last_torque = 0.0

  def update(self, torque, v_ego):
    """torque: 归一化力矩 [-1, 1]，返回平滑后的归一化力矩"""
    raw_torque = float(torque)
    v_ego = float(v_ego)
    self.raw_torque_ma[self.raw_torque_ma_i] = raw_torque
    self.raw_torque_ma_i = (self.raw_torque_ma_i + 1) % STEER_MA_SIZE
    ma_torque = sum(self.raw_torque_ma) / STEER_MA_SIZE

    dz = float(np.interp(v_ego, STEER_DEADZONE_BP, STEER_DEADZONE_V))
    deadzoned = _apply_deadzone(ma_torque, dz)

    oscillating = _count_sign_changes(self.raw_torque_ma) >= STEER_OSC_SIGN_CHANGES
    if abs(ma_torque) < STEER_STRAIGHT_THRESH:
      self.straight_frames = min(self.straight_frames + 1, STEER_STRAIGHT_FRAMES + 3)
    else:
      self.straight_frames = max(self.straight_frames - 2, 0)
    straight_mode = self.straight_frames >= STEER_STRAIGHT_FRAMES or oscillating

    # 小幅度反向指令直接归零，避免左右摇摆
    if (self.last_torque != 0.0 and deadzoned != 0.0 and
        (self.last_torque * deadzoned) < 0.0 and abs(deadzoned) < STEER_SIGN_FLIP_THRESH):
      deadzoned = 0.0

    if straight_mode and abs(deadzoned) < STEER_STRAIGHT_LOCK_THRESH:
      deadzoned = 0.0

    torque_delta = deadzoned - self.torque_target_last
    self.torque_target_last = deadzoned
    if not straight_mode and abs(deadzoned) >= STEER_PREVIEW_MIN_TORQUE:
      preview = float(np.clip(torque_delta * STEER_PREVIEW_GAIN, -STEER_PREVIEW_MAX, STEER_PREVIEW_MAX))
    else:
      preview = 0.0
    target_torque = float(np.clip(deadzoned + preview, -1.0, 1.0))

    alpha = float(np.interp(v_ego, STEER_LPF_ALPHA_BP, STEER_LPF_ALPHA_V))
    if straight_mode:
      alpha = min(alpha, STEER_STRAIGHT_LPF_MAX)
    self.torque_filtered = alpha * target_torque + (1.0 - alpha) * self.torque_filtered

    if straight_mode:
      self.torque_filtered *= STEER_STRAIGHT_CENTER_PULL
      if abs(self.torque_filtered) < STEER_STRAIGHT_LOCK_THRESH:
        self.torque_filtered = 0.0

    rate_scale = float(np.interp(v_ego, STEER_RATE_SCALE_BP, STEER_RATE_SCALE_V))
    if straight_mode:
      rate_scale *= STEER_STRAIGHT_RATE_MULT
    up_rate = self.params.STEER_DELTA_UP * DT_CTRL * rate_scale
    dn_rate = self.params.STEER_DELTA_DOWN * DT_CTRL * rate_scale
    limited = float(np.clip(self.torque_filtered,
                            self.last_torque - dn_rate, self.last_torque + up_rate))

    out_dz = float(np.interp(v_ego, STEER_OUTPUT_DZ_BP, STEER_OUTPUT_DZ_V))
    if abs(limited) < out_dz:
      limited = 0.0
      self.output_steady = 0.0
    elif abs(limited - self.output_steady) < STEER_OUTPUT_HYST:
      limited = self.output_steady
    else:
      self.output_steady = limited
    self.last_torque = limited
    return limited


class BrakeInhibit:
  """驾驶员踩刹车时短暂抑制 LKAS 输出，规避偶发 LKS 报错"""

  def __init__(self):
    self.inhibit = False
    self.pressed_cnt = 0
    self.release_cnt = 0

  def reset(self):
    self.inhibit = False
    self.pressed_cnt = 0
    self.release_cnt = 0

  def update(self, brake_pressed):
    if brake_pressed:
      self.release_cnt = 0
      if not self.inhibit:
        self.pressed_cnt += 1
        if self.pressed_cnt >= BRAKE_INHIBIT_PRESSED_THRESHOLD:
          self.inhibit = True
    else:
      self.pressed_cnt = 0
      if self.inhibit:
        self.release_cnt += 1
        if self.release_cnt >= BRAKE_INHIBIT_RELEASE_THRESHOLD:
          self.inhibit = False
    return self.inhibit


class LongitudinalEnhancer:
  """纵向增强：0 帧起步 + PI 跟车 + TTC 预测制动 + 加速度平滑

  只应在 openpilot 纵向（非 modified_stock_long）且 CC.longActive 时调用。
  """

  def __init__(self):
    self.lead_dist_history = deque(maxlen=LONG_LEAD_HISTORY_SIZE)
    self.lead_dist_rate_history = deque(maxlen=LONG_LEAD_RATE_HISTORY_SIZE)
    self.lead_dist_rate = 0.0
    self.last_lead_dist = 0.0
    self.time_to_collision = 100.0
    self.standstill_timer = 0
    self.pi_integral_error = 0.0
    self.accel_last = 0.0
    self.rfss = 0
    self.sss = 0

  def reset(self):
    self.lead_dist_history.clear()
    self.lead_dist_rate_history.clear()
    self.lead_dist_rate = 0.0
    self.last_lead_dist = 0.0
    self.time_to_collision = 100.0
    self.standstill_timer = 0
    self.pi_integral_error = 0.0
    self.accel_last = 0.0
    self.rfss = 0
    self.sss = 0

  def _update_lead_rate(self, lead_dist, dt):
    self.lead_dist_history.append(lead_dist)
    if self.last_lead_dist > 0.0 and len(self.lead_dist_history) > 1:
      current_rate = (self.lead_dist_history[-1] - self.lead_dist_history[-2]) / max(dt, 1e-3)
      self.lead_dist_rate_history.append(current_rate)
      self.lead_dist_rate = float(np.mean(self.lead_dist_rate_history))
    self.last_lead_dist = lead_dist

  def _predictive_brake(self, accel, v_ego, lead_dist):
    if self.lead_dist_rate < -0.1:
      self.time_to_collision = lead_dist / abs(self.lead_dist_rate)
    else:
      self.time_to_collision = 100.0

    if self.time_to_collision >= LONG_TTC_HORIZON:
      return accel

    safety_distance = v_ego * LONG_PREDICTIVE_BRAKE_SAFETY_FACTOR
    required_decel = -(v_ego ** 2) / (2.0 * max(lead_dist - safety_distance, 1.0))
    weight = float(np.clip(1.0 - self.time_to_collision / LONG_TTC_HORIZON, 0.0, 1.0)) ** 1.5
    return (1.0 - weight) * accel + weight * required_decel

  def update(self, CS, accel, long_state, dt=0.02):
    """返回 (accel, rfss, sss)"""
    accel = float(accel)
    lead_dist = float(getattr(CS, 'mrr_leading_dist', 0.0) or 0.0)
    v_ego = float(CS.out.vEgo)

    self._update_lead_rate(lead_dist, dt)

    # 静止/起步状态标志（bydcan 里作为报文字段发出）
    stopping = long_state == LongCtrlState.stopping
    starting = long_state == LongCtrlState.starting
    running = long_state == LongCtrlState.pid
    if stopping and accel < -0.1:
      self.rfss = 0
      self.sss = int(bool(CS.out.standstill))
    elif starting and accel > 0.1 and lead_dist > 3.0:
      self.rfss = int(bool(CS.out.standstill))
      self.sss = 0
    elif running:
      self.rfss = 0
      self.sss = 0

    # 0 帧起步：前车已移动且自身静止超过阈值，直接给一个温和的起步加速度
    lead_moving = self.lead_dist_rate > LONG_STANDSTILL_LEAD_MOVE_THRESHOLD
    if CS.out.standstill and self.standstill_timer > LONG_STANDSTILL_START_THRESHOLD and lead_moving:
      accel = float(np.interp(self.standstill_timer,
                              [LONG_STANDSTILL_START_THRESHOLD, LONG_STANDSTILL_START_THRESHOLD + 40],
                              [0.4, 0.8]))
      self.rfss = 1
      self.sss = 0
    else:
      self.standstill_timer = 0 if not CS.out.standstill else self.standstill_timer + 1

    # 智能跟车 PI：取规划器与 PI 中更保守（更小）的加速度
    if not CS.out.standstill and lead_dist > 0.0:
      target_dist = v_ego * LONG_TARGET_TIME_GAP
      dist_error = lead_dist - target_dist
      self.pi_integral_error += dist_error * dt
      self.pi_integral_error = float(np.clip(self.pi_integral_error, -5.0, 5.0))
      pi_accel = LONG_PI_KP * dist_error + LONG_PI_KI * self.pi_integral_error
      accel = min(accel, pi_accel)

    # TTC 预测制动（半窗后启用，避免历史过短时噪声）
    if len(self.lead_dist_history) >= LONG_LEAD_HISTORY_SIZE // 2:
      accel = self._predictive_brake(accel, v_ego, lead_dist)

    # 加速度平滑：急减速时提高响应速度
    if not CS.out.standstill:
      smoothing = LONG_ACCEL_SMOOTH_FACTOR
      if accel < -1.0:
        smoothing *= 0.5
      accel = smoothing * accel + (1.0 - smoothing) * self.accel_last

    self.accel_last = accel
    return accel, self.rfss, self.sss
