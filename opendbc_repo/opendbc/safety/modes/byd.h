#pragma once

#include "opendbc/safety/declarations.h"

// BYD safety mode for sunnypilot
// Ported from the community BYD adaptation (mypilot "高阶" source, carrotpilot
// BYD lineage), adapted to the sunnypilot safety architecture.
//
// safetyParam flags (must match opendbc/car/byd/values.py BydSafetyFlags):
//   bit0 ANGLE_MODE     - platform uses angle-based lateral control (CID_TCDUBH)
//   bit1 ACC_ON1        - ACC engagement variant used by Seal 23
//   bit2 ACC_CRUISEDISP - cruise display variant used by newer DMI platforms
//
// Torque platforms (Han DM/EV, Tang, Song, Qin, Yuan...) send LKAS torque on
// CID_ACC_MPC_STATE (0x316). Angle platforms (Tengshi D9, Seal, Qin L, Song L,
// Han DMI 25, ...) send steering angle on CID_TCDUBH (482, 0.1 deg/LSB).
// Measured steering angle arrives on CID_VSUYVS (287, 0.1 deg/LSB).

#define BYD_CANADDR_STEER_ANGLE       287    // CID_VSUYVS
#define BYD_CANADDR_CARSPEED          0x121
#define BYD_CANADDR_IPB               0x1F0
#define BYD_CANADDR_ACC_MPC_STATE     0x316
#define BYD_CANADDR_ACC_EPS_STATE     0x318
#define BYD_CANADDR_ACC_HUD_ADAS      0x32D
#define BYD_CANADDR_ACC_CMD           0x32E
#define BYD_CANADDR_DRIVE_STATE       0x242
#define BYD_CANADDR_PEDAL             0x342
#define BYD_CANADDR_PCM_BUTTONS       0x3B0
#define BYD_CANADDR_ANGLE_CONTROL     482    // CID_TCDUBH

#define BYD_CANBUS_ESC 0
#define BYD_CANBUS_MRR 1
#define BYD_CANBUS_MPC 2

// safetyParam flags (keep in sync with opendbc/car/byd/values.py BydSafetyFlags)
#define BYD_FLAG_ANGLE_MODE      1U
#define BYD_FLAG_ACC_ON1         2U
#define BYD_FLAG_ACC_CRUISEDISP  4U

static bool byd_eps_cruiseactivated = false;

static void byd_rx_hook(const CANPacket_t *msg) {
  int bus = (int)msg->bus;
  int addr = (int)msg->addr;

  if (bus == BYD_CANBUS_ESC) {
    if (addr == BYD_CANADDR_PEDAL) {
      gas_pressed = (msg->data[0] != 0U);
      brake_pressed = (msg->data[1] != 0U);
    } else if (addr == BYD_CANADDR_CARSPEED) {
      unsigned int speed_raw = msg->data[0] | ((msg->data[1] & 0xFU) << 8);
      vehicle_moving = (speed_raw > 0U);
      UPDATE_VEHICLE_SPEED((float)speed_raw * 0.1f / 3.6f);  // 0.1 kph/LSB -> m/s
    } else if (addr == BYD_CANADDR_STEER_ANGLE) {
      int angle_can = to_signed(msg->data[0] | (msg->data[1] << 8), 16);  // sig_uefwof, 0.1 deg/LSB
      update_sample(&angle_meas, angle_can);
    } else if (addr == BYD_CANADDR_ACC_EPS_STATE) {
      byd_eps_cruiseactivated = GET_BIT(msg, 1U);  // CruiseActivated
      int torque_motor = ((msg->data[2] & 0xFU) << 8) | msg->data[1];  // MainTorque
      torque_motor = to_signed(torque_motor, 12);
      update_sample(&torque_meas, torque_motor);
    } else {
      //empty
    }
  } else if (bus == BYD_CANBUS_MPC) {
    if (addr == BYD_CANADDR_ACC_HUD_ADAS) {
      unsigned int accstate = ((msg->data[2] >> 3) & 0x07U);
      bool cruise_engaged = (accstate == 3U) || (accstate == 5U);  // 3=acc_active, 5=user force accel
      pcm_cruise_check(cruise_engaged);
    }
  }
}

static bool byd_tx_hook(const CANPacket_t *msg) {
  bool tx = true;
  bool violation = false;
  int bus = (int)msg->bus;
  int addr = (int)msg->addr;
  bool angle_mode = GET_FLAG(current_safety_param, BYD_FLAG_ANGLE_MODE);

  if (bus == BYD_CANBUS_ESC) {
    if (angle_mode && (addr == BYD_CANADDR_ANGLE_CONTROL)) {
      // Angle-based steering command, CID_TCDUBH (482)
      // sig_kqgoqc: 24|16@1- (0.1, 0) [-780|779.9], little endian from byte 3
      int desired_angle = to_signed(msg->data[3] | (msg->data[4] << 8), 16);
      bool steer_control_enabled = (msg->data[2] & 0x02U) != 0U;  // sig_ausukb

      const AngleSteeringLimits BYD_ANGLE_STEERING_LIMITS = {
        .max_angle = 640,             // 64.0 deg steering wheel (community controller limit)
        .angle_deg_to_can = 10,        // 0.1 deg/LSB
        .frequency = 100U,
      };

      // conservative vehicle model params (typical BYD passenger car)
      const AngleSteeringParams BYD_STEERING_PARAMS = {
        .slip_factor = 0.0,           // conservative: no slip correction
        .steer_ratio = 15.0,
        .wheelbase = 2.9,
      };

      violation |= steer_angle_cmd_checks_vm(desired_angle, steer_control_enabled,
                                             BYD_ANGLE_STEERING_LIMITS, BYD_STEERING_PARAMS);
    } else if (!angle_mode && (addr == BYD_CANADDR_ACC_MPC_STATE)) {
      // Torque-based steering command, CID_ACC_MPC_STATE (0x316)
      const TorqueSteeringLimits BYD_STEERING_LIMITS = {
        .max_torque = 300,
        .max_rate_up = 17,
        .max_rate_down = 17,
        .max_rt_delta = 113,
        .max_torque_error = 80,
        .type = TorqueMotorLimited,
      };

      int desired_torque = ((msg->data[3] & 0x07U) << 8U) | msg->data[2];
      desired_torque = to_signed(desired_torque, 11);
      bool steer_req = GET_BIT(msg, 28U) || byd_eps_cruiseactivated;  // LKAS_Active

      violation |= steer_torque_cmd_checks(desired_torque, steer_req, BYD_STEERING_LIMITS);
    }
  }

  if (violation) {
    tx = false;
  }

  return tx;
}

static bool byd_fwd_hook(int bus, int addr) {
  bool block_msg = false;

  const bool is_lkas = ((addr == BYD_CANADDR_ACC_MPC_STATE) || (addr == BYD_CANADDR_ACC_CMD) ||
                        (addr == BYD_CANADDR_ANGLE_CONTROL));
  const bool is_eps = false;

  if (((bus == BYD_CANBUS_ESC) && is_eps) || ((bus == BYD_CANBUS_MPC) && is_lkas)) {
    block_msg = true;
  }

  return block_msg;
}

static safety_config byd_init(uint16_t param) {
  SAFETY_UNUSED(param);
  byd_eps_cruiseactivated = false;

  static const CanMsg BYD_TX_MSGS[] = {
    {BYD_CANADDR_ACC_CMD,         BYD_CANBUS_ESC, 8, .check_relay = false},
    {BYD_CANADDR_ACC_MPC_STATE,   BYD_CANBUS_ESC, 8, .check_relay = true},
    {BYD_CANADDR_ACC_EPS_STATE,   BYD_CANBUS_MPC, 8, .check_relay = false},
    {BYD_CANADDR_ANGLE_CONTROL,   BYD_CANBUS_ESC, 8, .check_relay = true},
  };

  static RxCheck BYD_RX_CHECKS[] = {
    {.msg = {{BYD_CANADDR_PEDAL,         BYD_CANBUS_ESC, 8, .ignore_checksum = true, .ignore_counter = true, .frequency = 50U}, { 0 }, { 0 }}},
    {.msg = {{BYD_CANADDR_CARSPEED,      BYD_CANBUS_ESC, 8, .ignore_checksum = true, .ignore_counter = true, .frequency = 50U}, { 0 }, { 0 }}},
    {.msg = {{BYD_CANADDR_STEER_ANGLE,   BYD_CANBUS_ESC, 5, .ignore_checksum = true, .ignore_counter = true, .frequency = 100U}, { 0 }, { 0 }}},
    {.msg = {{BYD_CANADDR_ACC_EPS_STATE, BYD_CANBUS_ESC, 8, .ignore_checksum = true, .ignore_counter = true, .frequency = 50U}, { 0 }, { 0 }}},
    {.msg = {{BYD_CANADDR_ACC_HUD_ADAS,  BYD_CANBUS_MPC, 8, .ignore_checksum = true, .ignore_counter = true, .frequency = 50U}, { 0 }, { 0 }}},
  };

  safety_config ret;
  SET_RX_CHECKS(BYD_RX_CHECKS, ret);
  SET_TX_MSGS(BYD_TX_MSGS, ret);
  return ret;
}

const safety_hooks byd_hooks = {
  .init = byd_init,
  .rx = byd_rx_hook,
  .tx = byd_tx_hook,
  .fwd = byd_fwd_hook,
};
