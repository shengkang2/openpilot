#!/usr/bin/env python3
import numpy as np

from openpilot.common.pid import PIDController
from openpilot.system.hardware import HARDWARE

# raise fan setpoint on tici/tizi to reduce noise
# after raising LMH threshold in AGNOS 18.1 to prevent CPU throttling
# BluePilot: comma used +5C (fan setpoint 80C) for quieter fans; BP uses +2C (77C) to split the
# difference -- ~3C cooler than comma's noise-first tuning, still quieter than the pre-sync 75C.
OFFSET = 0 if HARDWARE.get_device_type() == "mici" else 2

# 2026-11-01 noise-first retune (owner asked for a quieter fan):
#   tici setpoint 77C -> 80C (comma's original noise-first value)
#   feedforward start 62C -> 68C, end 102C -> 105C
# Below ~68C the feedforward term is now zero, so the fan spins up later and the
# low-temperature band stays quiet. Cost: steady-state temperature rises ~3-6C;
# the hardware trip points are 110C (step) / 125C (usr), so there is plenty of margin.
# mici keeps the upstream curve untouched.
QUIET_TUNING = HARDWARE.get_device_type() != "mici"
SETPOINT_C = 80.0 if QUIET_TUNING else 75.0 + OFFSET
FF_START_C = 68.0 if QUIET_TUNING else 60.0 + OFFSET
FF_END_C = 105.0 if QUIET_TUNING else 100.0 + OFFSET


class FanController:
  def __init__(self, rate: int) -> None:
    self.last_ignition = False
    self.controller = PIDController(k_p=0, k_i=4e-3, rate=rate)

  def update(self, cur_temp: float, ignition: bool) -> int:
    self.controller.pos_limit = 100 if ignition else 30
    self.controller.neg_limit = 30 if ignition else 0

    if ignition != self.last_ignition:
      self.controller.reset()
    self.last_ignition = ignition

    return int(self.controller.update(
                 error=(cur_temp - SETPOINT_C),  # temperature setpoint in C
                 feedforward=np.interp(cur_temp, [FF_START_C, FF_END_C], [0, 100])
              ))
