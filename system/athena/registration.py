#!/usr/bin/env python3
import time
import json
import jwt
from pathlib import Path
from datetime import datetime, timedelta, UTC

from openpilot.common.api import api_get
from openpilot.common.params import Params
from openpilot.common.spinner import Spinner
from openpilot.selfdrive.selfdrived.alertmanager import set_offroad_alert
from openpilot.system.hardware import HARDWARE, PC
from openpilot.system.hardware.hw import Paths
from openpilot.common.swaglog import cloudlog


UNREGISTERED_DONGLE_ID = "UnregisteredDevice"
MAX_REGISTRATION_TIME_S = 60  # 防止无限阻塞注册逻辑


def is_registered_device() -> bool:
  dongle = Params().get("DongleId", encoding='utf-8')
  return dongle not in (None, UNREGISTERED_DONGLE_ID)


def register(show_spinner=False) -> str | None:
  params = Params()

  dongle_id: str | None = params.get("DongleId", encoding='utf8')
  if dongle_id is None and Path(Paths.persist_root()+"/comma/dongle_id").is_file():
    with open(Paths.persist_root()+"/comma/dongle_id") as f:
      dongle_id = f.read().strip()

  pubkey_path = Path(Paths.persist_root()+"/comma/id_rsa.pub")
  privkey_path = Path(Paths.persist_root()+"/comma/id_rsa")

  if not pubkey_path.is_file() or not privkey_path.is_file():
    cloudlog.warning(f"Missing key files: {pubkey_path} or {privkey_path}")
    dongle_id = UNREGISTERED_DONGLE_ID
    params.put("DongleId", dongle_id)
    return dongle_id

  if dongle_id is not None:
    return dongle_id

  if show_spinner:
    spinner = Spinner()
    spinner.update("registering device")

  try:
    # 读取密钥
    with open(pubkey_path) as f1, open(privkey_path) as f2:
      public_key = f1.read()
      private_key = f2.read()

    # 强制使用固定 IMEI，获取 serial
    serial = HARDWARE.get_serial()
    imei1 = "865420071781912"
    imei2 = "865420071781904"
    params.put("IMEI", imei1)
    params.put("HardwareSerial", serial)

    # 构建 JWT
    try:
      register_token = jwt.encode(
        {'register': True, 'exp': datetime.utcnow() + timedelta(hours=1)},
        private_key, algorithm='RS256'
      )
    except Exception as e:
      cloudlog.exception("JWT generation failed")
      dongle_id = UNREGISTERED_DONGLE_ID
      params.put("DongleId", dongle_id)
      return dongle_id

    # 注册请求
    start_time = time.monotonic()
    backoff = 0
    while True:
      try:
        cloudlog.info("Requesting pilotauth registration")
        resp = api_get("v2/pilotauth/", method='POST', timeout=15,
                       imei=imei1, imei2=imei2, serial=serial,
                       public_key=public_key, register_token=register_token)

        if resp.status_code in (402, 403):
          cloudlog.info(f"Device not allowed to register: HTTP {resp.status_code}")
          dongle_id = UNREGISTERED_DONGLE_ID
        else:
          dongleauth = json.loads(resp.text)
          dongle_id = dongleauth.get("dongle_id", UNREGISTERED_DONGLE_ID)
        break
      except Exception:
        cloudlog.exception("Pilotauth request failed")
        backoff = min(backoff + 1, 10)
        time.sleep(backoff)

      if time.monotonic() - start_time > MAX_REGISTRATION_TIME_S:
        cloudlog.warning("Registration timed out")
        dongle_id = UNREGISTERED_DONGLE_ID
        break

      if show_spinner:
        spinner.update(f"registering device - IMEI: {imei1}, Serial: {serial}")

  finally:
    if show_spinner:
      spinner.close()

  # 保存结果
  params.put("DongleId", dongle_id)
  set_offroad_alert("Offroad_UnofficialHardware", (dongle_id == UNREGISTERED_DONGLE_ID) and not PC)
  return dongle_id


if __name__ == "__main__":
  print(register())
