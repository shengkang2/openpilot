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
        self.learning_mode = True
        self.learning_samples = 0

    def update(self, can_parsers) -> tuple[structs.CarState, structs.CarStateSP]:
        cp = can_parsers[Bus.pt]
        cp_cam = can_parsers[Bus.cam]

        ret = structs.CarState()
        ret_sp = structs.CarStateSP()

        if self.CP.flags & FordFlags.ALT_STEER_ANGLE:
            self.vehicle_sensors_valid = (
                int((cp.vl["ParkAid_Data"]["ExtSteeringAngleReq2"] + 1000) * 10) not in (32766, 32767)
                and cp.vl["ParkAid_Data"]["EPASExtAngleStatReq"] == 0
                and cp.vl["ParkAid_Data"]["ApaSys_D_Stat"] in (0, 1)
            )
            ret.vehicleSensorsInvalid = not self.vehicle_sensors_valid
        else:
            ret.vehicleSensorsInvalid = cp.vl["SteeringPinion_Data"]["StePinCompAnEst_D_Qf"] != 3

        # car speed
        ret.vEgoRaw = cp.vl["BrakeSysFeatures"]["Veh_V_ActlBrk"] * CV.KPH_TO_MS
        ret.vEgo, ret.aEgo = self.update_speed_kf(ret.vEgoRaw)
        if self.CP.flags & FordFlags.CANFD:
            ret.vEgoCluster = ((cp.vl["Cluster_Info_3_FD1"]["DISPLAY_SPEED_SCALING"]/100) * cp.vl["EngVehicleSpThrottle2"]["Veh_V_ActlEng"] +
                             cp.vl["Cluster_Info_3_FD1"]["DISPLAY_SPEED_OFFSET"]) * CV.KPH_TO_MS

        ret.yawRate = cp.vl["Yaw_Data_FD1"]["VehYaw_W_Actl"]
        ret.standstill = cp.vl["DesiredTorqBrk"]["VehStop_D_Stat"] == 1

        # gas pedal
        ret.gas = cp.vl["EngVehicleSpThrottle"]["ApedPos_Pc_ActlArb"] / 100.
        ret.gasPressed = ret.gas > 1e-6

        # brake pedal
        ret.brake = cp.vl["BrakeSnData_4"]["BrkTot_Tq_Actl"] / 32756.
        ret.brakePressed = cp.vl["EngBrakeData"]["BpedDrvAppl_D_Actl"] == 2
        ret.parkingBrake = cp.vl["DesiredTorqBrk"]["PrkBrkStatus"] in (1, 2)

        # steering wheel
        if self.CP.flags & FordFlags.ALT_STEER_ANGLE:
            steering_angle_init = cp.vl["SteeringPinion_Data_Alt"]["StePinRelInit_An_Sns"]
            if getattr(self, "vehicle_sensors_valid", False):
                steering_angle_est = cp.vl["ParkAid_Data"]["ExtSteeringAngleReq2"]
                self.steering_angle_offset_deg = steering_angle_est - steering_angle_init
            ret.steeringAngleDeg = steering_angle_init + self.steering_angle_offset_deg
        else:
            ret.steeringAngleDeg = cp.vl["SteeringPinion_Data"]["StePinComp_An_Est"]
        ret.steeringTorque = cp.vl["EPAS_INFO"]["SteeringColumnTorque"]
        ret.steeringPressed = self.update_steering_pressed(abs(ret.steeringTorque) > CarControllerParams.STEER_DRIVER_ALLOWANCE, 5)
        ret.steerFaultTemporary = cp.vl["EPAS_INFO"]["EPAS_Failure"] == 1
        ret.steerFaultPermanent = cp.vl["EPAS_INFO"]["EPAS_Failure"] in (2, 3)
        ret.espDisabled = cp.vl["Cluster_Info1_FD1"]["DrvSlipCtlMde_D_Rq"] != 0

        if self.CP.flags & FordFlags.CANFD:
            ret.steerFaultTemporary |= cp.vl["Lane_Assist_Data3_FD1"]["LatCtlSte_D_Stat"] not in (1, 2, 3)

        # cruise state
        is_metric = cp.vl["INSTRUMENT_PANEL"]["METRIC_UNITS"] == 1 if not self.CP.flags & FordFlags.CANFD else cp_cam.vl["IPMA_Data2"]["IsaVLimUnit_D_Rq"] == 1
        ret.cruiseState.speed = cp.vl["EngBrakeData"]["Veh_V_DsplyCcSet"] * (CV.KPH_TO_MS if is_metric else CV.MPH_TO_MS)
        ret.cruiseState.enabled = cp.vl["EngBrakeData"]["CcStat_D_Actl"] in (4, 5)
        ret.cruiseState.available = cp.vl["EngBrakeData"]["CcStat_D_Actl"] in (3, 4, 5)
        ret.cruiseState.nonAdaptive = cp.vl["Cluster_Info1_FD1"]["AccEnbl_B_RqDrv"] == 0
        ret.cruiseState.standstill = cp.vl["EngBrakeData"]["AccStopMde_D_Rq"] == 3
        ret.accFaulted = cp.vl["EngBrakeData"]["CcStat_D_Actl"] in (1, 2)

        if self.CP.flags & FordFlags.CANFD:
            ret.cruiseState.speedLimit = self.update_traffic_signals(cp_cam)

        if not self.CP.openpilotLongitudinalControl:
            ret.accFaulted = ret.accFaulted or cp_cam.vl["ACCDATA"]["CmbbDeny_B_Actl"] == 1

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

        ret.engineRpm = cp.vl["EngVehicleSpThrottle"]["EngAout_N_Actl"]

        # safety
        ret.stockFcw = bool(cp_cam.vl["ACCDATA_3"]["FcwVisblWarn_B_Rq"])
        ret.stockAeb = bool(cp_cam.vl["ACCDATA_2"]["CmbbBrkDecel_B_Rq"])

        # button presses
        ret.leftBlinker = cp.vl["Steering_Data_FD1"]["TurnLghtSwtch_D_Stat"] == 1
        ret.rightBlinker = cp.vl["Steering_Data_FD1"]["TurnLghtSwtch_D_Stat"] == 2
        ret.genericToggle = bool(cp.vl["Steering_Data_FD1"]["TjaButtnOnOffPress"])
        prev_distance_button = self.distance_button
        prev_lc_button = self.lc_button
        self.distance_button = cp.vl["Steering_Data_FD1"]["AccButtnGapTogglePress"]
        self.lc_button = bool(cp.vl["Steering_Data_FD1"]["TjaButtnOnOffPress"])

        # lock info
        ret.doorOpen = any([cp.vl["BodyInfo_3_FD1"]["DrStatDrv_B_Actl"], cp.vl["BodyInfo_3_FD1"]["DrStatPsngr_B_Actl"],
                            cp.vl["BodyInfo_3_FD1"]["DrStatRl_B_Actl"], cp.vl["BodyInfo_3_FD1"]["DrStatRr_B_Actl"]])
        ret.seatbeltUnlatched = cp.vl["RCMStatusMessage2_FD1"]["FirstRowBuckleDriver"] == 2

        # blindspot sensors
        if self.CP.enableBsm:
            cp_bsm = cp_cam if self.CP.flags & FordFlags.CANFD else cp
            ret.leftBlindspot = cp_bsm.vl["Side_Detect_L_Stat"]["SodDetctLeft_D_Stat"] != 0
            ret.rightBlindspot = cp_bsm.vl["Side_Detect_R_Stat"]["SodDetctRight_D_Stat"] != 0

        # Stock steering buttons
        self.buttons_stock_values = cp.vl["Steering_Data_FD1"]
        self.acc_tja_status_stock_values = cp_cam.vl["ACCDATA_3"]
        self.lkas_status_stock_values = cp_cam.vl["IPMA_Data"]

        MadsCarState.update_mads(self, ret, can_parsers)

        ret.buttonEvents = [
            *create_button_events(self.distance_button, prev_distance_button, {1: ButtonType.gapAdjustCruise}),
            *create_button_events(self.lc_button, prev_lc_button, {1: ButtonType.lkas}),
        ]

        self.car_state_bp_msg = self.update_car_state_bp(cp)
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
        if not self.gear_learning['drive']:
            return GearShifter.unknown, "unknown", None
        
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
        speed = cp.vl["BrakeSysFeatures"]["Veh_V_ActlBrk"] * CV.KPH_TO_MS
        if speed > 1.0:
            return GearShifter.drive
        
        brake_pressed = cp.vl["EngBrakeData"]["BpedDrvAppl_D_Actl"] == 2
        if brake_pressed and speed < 0.1:
            return GearShifter.neutral
        
        return GearShifter.unknown

    def _learn_gear_mapping(self, current_gear, gear_signals):
        """学习档位映射"""
        if current_gear == GearShifter.unknown:
            return
        
        self.learning_samples += 1
        
        gear_name = current_gear.name.lower() if hasattr(current_gear, 'name') else str(current_gear)
        if gear_name in self.gear_learning:
            for signal_value in gear_signals.values():
                self.gear_learning[gear_name].add(signal_value)
        
        if self.learning_samples > 50:
            self.learning_mode = False
            debug(f"[CarState] 学习完成: {self.gear_learning}")

    def update_car_state_bp(self, cp):
        """Update the CarStateBP message for HEV/PHEV data"""
        dat = messaging.new_message("carStateBP")
        dat.valid = True

        hybrid_drive = dat.carStateBP.hybridDrive
        hybrid_battery = dat.carStateBP.hybridBattery

        hybrid_drive.dataAvailable = False
        hybrid_drive.throttleDemandPercent = 0.0
        hybrid_drive.throttleThresholdPercent = 0.0
        hybrid_drive.powerFlowMode = ""
        hybrid_drive.engineOnReason = ""

        hybrid_battery.dataAvailable = False
        hybrid_battery.voltHighLimit = 0.0
        hybrid_battery.voltLowLimit = 0.0
        hybrid_battery.voltActual = 0.0
        hybrid_battery.ampsActual = 0.0
        hybrid_battery.socMinPerc = 0.0
        hybrid_battery.socMaxPerc = 0.0
        hybrid_battery.socActual = 0.0

        # HEV cluster data
        try:
            if self.CP.flags & FordFlags.HEV_CLUSTER_DATA:
                hev_data = cp.vl["Cluster_HEV_Data2"]
                if hev_data is not None:
                    hybrid_drive.dataAvailable = True
                    hybrid_drive.throttleDemandPercent = hev_data["EffWhlLvl2_Pc_Dsply"]
                    hybrid_drive.throttleThresholdPercent = hev_data["EffWhlThres_Pc_Dsply"]
                    hybrid_drive.powerFlowMode = get_hev_power_flow_text(hev_data["PwrFlowTxt_D_Dsply"])
                    hybrid_drive.engineOnReason = get_hev_engine_on_reason_text(hev_data["EngOnMsg1_D_Dsply"])
        except (KeyError, AttributeError):
            pass

        # HEV battery data
        try:
            if self.CP.flags & FordFlags.HEV_BATTERY_DATA:
                batt_data1 = cp.vl["Battery_Traction_1_FD1"]
                batt_data3 = cp.vl["Battery_Traction_3_FD1"]
                batt_data4 = cp.vl["Battery_Traction_4_FD1"]

                if all(x is not None for x in [batt_data1, batt_data3, batt_data4]):
                    hybrid_battery.dataAvailable = True
                    hybrid_battery.voltHighLimit = batt_data1["BattTrac_U_LimHi"]
                    hybrid_battery.voltLowLimit = batt_data1["BattTrac_U_LimLo"]
                    hybrid_battery.voltActual = batt_data1["BattTrac_U_Actl"]
                    hybrid_battery.ampsActual = batt_data1["BattTrac_I_Actl"]
                    hybrid_battery.socMinPerc = batt_data3["BattTracSoc_Pc_MnPrtct"]
                    hybrid_battery.socMaxPerc = batt_data3["BattTracSoc_Pc_MxPrtct"]
                    hybrid_battery.socActual = batt_data4["BattTracSoc2_Pc_Actl"]
        except (KeyError, AttributeError):
            pass

        return dat

    def update_traffic_signals(self, cp_cam):
        if self.CP.flags & FordFlags.CANFD:
            self.v_limit = cp_cam.vl["Traffic_RecognitnData"]["TsrVLim1MsgTxt_D_Rq"]
            v_limit_unit = cp_cam.vl["Traffic_RecognitnData"]["TsrVlUnitMsgTxt_D_Rq"]

            speed_factor = CV.MPH_TO_MS if v_limit_unit == 2 else CV.KPH_TO_MS if v_limit_unit == 1 else 0

            return self.v_limit * speed_factor if self.v_limit not in (0, 255) else 0

    @staticmethod
    def get_can_parsers(CP, CP_SP):
        pt_messages = [
            ("VehicleOperatingModes", 100),
            ("BrakeSysFeatures", 50),
            ("Yaw_Data_FD1", 100),
            ("DesiredTorqBrk", 50),
            ("EngVehicleSpThrottle", 100),
            ("EngVehicleSpThrottle2", 50),
            ("BrakeSnData_4", 50),
            ("EngBrakeData", 10),
            ("Cluster_Info1_FD1", 10),
            ("EPAS_INFO", 50),
            ("Steering_Data_FD1", 10),
            ("BodyInfo_3_FD1", 2),
            ("RCMStatusMessage2_FD1", 10),
        ]

        if CP.flags & FordFlags.HEV_CLUSTER_DATA:
            pt_messages.append(("Cluster_HEV_Data2", 10))

        if CP.flags & FordFlags.HEV_BATTERY_DATA:
            pt_messages.append(("Battery_Traction_1_FD1", 10))
            pt_messages.append(("Battery_Traction_3_FD1", 10))
            pt_messages.append(("Battery_Traction_4_FD1", 10))

        if CP.flags & FordFlags.ALT_STEER_ANGLE:
            pt_messages += [
                ("SteeringPinion_Data_Alt", 100),
                ("ParkAid_Data", 50),
            ]
            if CP.transmissionType == TransmissionType.automatic:
                pt_messages.append(("TransGearData", 10))
        else:
            pt_messages += [
                ("SteeringPinion_Data", 100),
            ]
            if CP.transmissionType == TransmissionType.automatic:
                pt_messages += [
                    ("PowertrainData_10", 10)
                ]

        if CP.flags & FordFlags.CANFD:
            pt_messages += [
                ("Lane_Assist_Data3_FD1", 33),
                ("Cluster_Info_3_FD1", 10),
            ]
        else:
            pt_messages += [
                ("INSTRUMENT_PANEL", 1),
            ]

        if CP.transmissionType == TransmissionType.automatic:
            pt_messages += [
                ("Gear_Shift_by_Wire_FD1", 10),
            ]
        elif CP.transmissionType == TransmissionType.manual:
            pt_messages += [
                ("Engine_Clutch_Data", 33),
                ("BCM_Lamp_Stat_FD1", 1),
            ]

        if CP.enableBsm and not (CP.flags & FordFlags.CANFD):
            pt_messages += [
                ("Side_Detect_L_Stat", 5),
                ("Side_Detect_R_Stat", 5),
            ]

        cam_messages = [
            ("ACCDATA", 50),
            ("ACCDATA_2", 50),
            ("ACCDATA_3", 5),
            ("IPMA_Data", 1),
        ]

        if CP.flags & FordFlags.CANFD:
            cam_messages += [
                ("Traffic_RecognitnData", 1),
                ("IPMA_Data2", 1),
            ]

        if CP.enableBsm and CP.flags & FordFlags.CANFD:
            cam_messages += [
                ("Side_Detect_L_Stat", 5),
                ("Side_Detect_R_Stat", 5),
            ]

        return {
            Bus.pt: CANParser(DBC[CP.carFingerprint][Bus.pt], pt_messages, CanBus(CP).main),
            Bus.cam: CANParser(DBC[CP.carFingerprint][Bus.pt], cam_messages, CanBus(CP).camera),
        }
