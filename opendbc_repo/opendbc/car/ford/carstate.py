from opendbc.can.can_define import CANDefine
from opendbc.can.parser import CANParser
from opendbc.car import Bus, create_button_events, structs
from opendbc.car.common.conversions import Conversions as CV
from openpilot.common.params import Params
from opendbc.car.ford.fordcan import CanBus
from opendbc.car.ford.values import DBC, CarControllerParams, FordConfig, FordFlags
from opendbc.car.interfaces import CarStateBase
from cereal import messaging
from bluepilot.logger.bp_logger import debug, info, warning, error, critical
from opendbc.sunnypilot.car.ford.mads import MadsCarState

# from opendbc.car.ford.fordcanparser import FordCanParser
from opendbc.car.ford.helpers import get_hev_power_flow_text, get_hev_engine_on_reason_text

ButtonType = structs.CarState.ButtonEvent.Type
GearShifter = structs.CarState.GearShifter
TransmissionType = structs.CarParams.TransmissionType


class CarState(CarStateBase, MadsCarState):
  def __init__(self, CP, CP_SP):
    CarStateBase.__init__(self, CP, CP_SP)
    MadsCarState.__init__(self, CP, CP_SP)
    can_define = CANDefine(DBC[CP.carFingerprint][Bus.pt])
    self.params = Params()
    # self.ford_can_parser = FordCanParser(CP)

    self.bluecruise_cluster_present = FordConfig.BLUECRUISE_CLUSTER_PRESENT
    self.steering_angle_offset_deg = 0.0

    if CP.transmissionType == TransmissionType.automatic:
      if CP.flags & FordFlags.CANFD:
        self.shifter_values = can_define.dv["Gear_Shift_by_Wire_FD1"]["TrnRng_D_RqGsm"]
        debug("使用 CAN FD 档位信号: Gear_Shift_by_Wire_FD1.TrnRng_D_RqGsm")
      elif CP.flags & FordFlags.ALT_STEER_ANGLE:
        self.shifter_values = can_define.dv["TransGearData"]["GearLvrPos_D_Actl"]
        debug("使用 ALT_STEER_ANGLE 档位信号: TransGearData.GearLvrPos_D_Actl")
      else:
        self.shifter_values = can_define.dv["PowertrainData_10"]["TrnRng_D_Rq"]
        debug("使用标准档位信号: PowertrainData_10.TrnRng_D_Rq")

    self.cluster_min_speed = CV.KPH_TO_MS * 1.5
    self.cluster_speed_hyst_gap = CV.KPH_TO_MS / 2.
    self.distance_button = 0
    self.lc_button = 0

    self.params.put_bool("FordPrefHevDataAvailable", True if CP.flags & FordFlags.HEV_CLUSTER_DATA else False)
    self.params.put_bool("FordPrefHevBattDataAvailable", True if CP.flags & FordFlags.HEV_BATTERY_DATA else False)
    self.hev_data_available = CP.flags & FordFlags.HEV_CLUSTER_DATA

    # 档位识别相关
    self._last_gear_shifter = None
    self._last_gear_src = None
    self._last_gear_raw = None
    self._gear_debug_counter = 0
    
    # 学习模式：记录不同档位对应的信号值
    self.gear_learning = {
        'park': set(),
        'reverse': set(),
        'neutral': set(),
        'drive': set()
    }
    self.learning_mode = True  # 开始为学习模式
    self.learning_samples = 0


  def update(self, can_parsers) -> tuple[structs.CarState, structs.CarStateSP]:
    cp = can_parsers[Bus.pt]
    cp_cam = can_parsers[Bus.cam]

    ret = structs.CarState()
    ret_sp = structs.CarStateSP()

    # ... (保持其他代码不变，只修改档位识别部分) ...

    # ===== 智能档位识别 =====
    if self.CP.transmissionType == TransmissionType.automatic:
      gear_signals = self._collect_gear_signals(cp)
      
      # 尝试多种识别策略
      ret.gearShifter, src, raw_val = self._smart_gear_detection(cp, gear_signals)
      
      # 学习模式：基于车辆运动状态验证档位
      if self.learning_mode:
        self._learn_gear_mapping(ret.gearShifter, gear_signals)
      
      # 档位切换调试
      if (ret.gearShifter != self._last_gear_shifter) or (src != self._last_gear_src) or (raw_val != self._last_gear_raw):
        debug(f"[CarState] 档位: {src} raw={raw_val} -> {ret.gearShifter}")
        self._last_gear_shifter = ret.gearShifter
        self._last_gear_src = src
        self._last_gear_raw = raw_val

    elif self.CP.transmissionType == TransmissionType.manual:
      ret.clutchPressed = cp.vl["Engine_Clutch_Data"]["CluPdlPos_Pc_Meas"] > 0
      if bool(cp.vl["BCM_Lamp_Stat_FD1"]["RvrseLghtOn_B_Stat"]):
        ret.gearShifter = GearShifter.reverse
      else:
        ret.gearShifter = GearShifter.drive

    # ... (保持其他代码不变) ...

    return ret, ret_sp

  def _collect_gear_signals(self, cp):
    """收集所有档位相关信号"""
    gear_signals = {}
    for msg_name in cp.vl:
      if any(keyword in str(msg_name).lower() for keyword in ['gear', 'trn', 'trans', 'shift', 'rng', 'lvr']):
        gear_signals[msg_name] = cp.vl[msg_name]
    return gear_signals

  def _smart_gear_detection(self, cp, gear_signals):
    """智能档位检测"""
    # 策略1: 优先检测已知信号源
    gear, src, raw_val = self._detect_from_known_sources(cp)
    if gear != GearShifter.unknown:
        return gear, src, raw_val
    
    # 策略2: 基于学习到的映射
    gear, src, raw_val = self._detect_from_learned_mapping(gear_signals)
    if gear != GearShifter.unknown:
        return gear, src, raw_val
    
    # 策略3: 基于车辆状态推断
    gear = self._infer_gear_from_vehicle_state(cp)
    if gear != GearShifter.unknown:
        return gear, "inferred", None
    
    return GearShifter.unknown, "unknown", None

  def _detect_from_known_sources(self, cp):
    """从已知信号源检测档位"""
    # 1) TransGearData.GearLvrPos_D_Actl
    if "TransGearData" in cp.vl and "GearLvrPos_D_Actl" in cp.vl["TransGearData"]:
        raw_val = cp.vl["TransGearData"]["GearLvrPos_D_Actl"]
        # 尝试多种可能的映射
        if raw_val == 0: return GearShifter.park, "TransGearData", raw_val
        if raw_val == 1: return GearShifter.reverse, "TransGearData", raw_val
        if raw_val == 2: return GearShifter.neutral, "TransGearData", raw_val
        if raw_val == 3: return GearShifter.drive, "TransGearData", raw_val
        if raw_val in [4, 5]: return GearShifter.drive, "TransGearData", raw_val

    # 2) Gear_Shift_by_Wire_FD1.TrnRng_D_RqGsm
    if "Gear_Shift_by_Wire_FD1" in cp.vl and "TrnRng_D_RqGsm" in cp.vl["Gear_Shift_by_Wire_FD1"]:
        raw_val = cp.vl["Gear_Shift_by_Wire_FD1"]["TrnRng_D_RqGsm"]
        if raw_val == 1: return GearShifter.park, "CAN_FD", raw_val
        if raw_val == 3: return GearShifter.reverse, "CAN_FD", raw_val
        if raw_val == 2: return GearShifter.neutral, "CAN_FD", raw_val
        if raw_val == 4: return GearShifter.drive, "CAN_FD", raw_val
        if raw_val in [5, 6]: return GearShifter.drive, "CAN_FD", raw_val

    # 3) PowertrainData_10.TrnRng_D_Rq
    if "PowertrainData_10" in cp.vl and "TrnRng_D_Rq" in cp.vl["PowertrainData_10"]:
        raw_val = cp.vl["PowertrainData_10"]["TrnRng_D_Rq"]
        if raw_val == 5: return GearShifter.park, "Powertrain", raw_val
        if raw_val == 7: return GearShifter.reverse, "Powertrain", raw_val
        if raw_val == 6: return GearShifter.neutral, "Powertrain", raw_val
        if raw_val == 8: return GearShifter.drive, "Powertrain", raw_val
        if raw_val == 9: return GearShifter.drive, "Powertrain", raw_val

    return GearShifter.unknown, "unknown", None

  def _detect_from_learned_mapping(self, gear_signals):
    """基于学习到的映射检测档位"""
    if not self.gear_learning['drive']:  # 还没有学习到映射
        return GearShifter.unknown, "unknown", None
    
    # 检查当前信号是否匹配学习到的模式
    for signal_name, signal_value in gear_signals.items():
        if signal_value in self.gear_learning['drive']:
            return GearShifter.drive, f"learned_{signal_name}", signal_value
        if signal_value in self.gear_learning['reverse']:
            return GearShifter.reverse, f"learned_{signal_name}", signal_value
        if signal_value in self.gear_learning['neutral']:
            return GearShifter.neutral, f"learned_{signal_name}", signal_value
        if signal_value in self.gear_learning['park']:
            return GearShifter.park, f"learned_{signal_name}", signal_value
    
    return GearShifter.unknown, "unknown", None

  def _infer_gear_from_vehicle_state(self, cp):
    """基于车辆状态推断档位"""
    # 如果车辆在移动且速度 > 0，很可能是D档
    speed = cp.vl["BrakeSysFeatures"]["Veh_V_ActlBrk"] * CV.KPH_TO_MS
    if speed > 1.0:  # 速度大于1 m/s
        return GearShifter.drive
    
    # 如果刹车踩下且车辆静止，可能是N档或D档
    brake_pressed = cp.vl["EngBrakeData"]["BpedDrvAppl_D_Actl"] == 2
    if brake_pressed and speed < 0.1:
        return GearShifter.neutral
    
    return GearShifter.unknown

  def _learn_gear_mapping(self, current_gear, gear_signals):
    """学习档位映射"""
    if current_gear == GearShifter.unknown:
        return
    
    self.learning_samples += 1
    
    # 为每个检测到的档位记录信号值
    gear_name = current_gear.name.lower() if hasattr(current_gear, 'name') else str(current_gear)
    if gear_name in self.gear_learning:
        for signal_value in gear_signals.values():
            self.gear_learning[gear_name].add(signal_value)
    
    # 学习足够样本后关闭学习模式
    if self.learning_samples > 50:
        self.learning_mode = False
        debug(f"[CarState] 学习完成: {self.gear_learning}")

  # ... (保持其他方法不变) ...

  @staticmethod
  def get_can_parsers(CP, CP_SP):
    # ... (保持原有的CAN解析器配置不变) ...
