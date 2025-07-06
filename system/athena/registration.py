#!/usr/bin/env python3
import time
import json
import requests
from pathlib import Path
from datetime import datetime

from openpilot.common.params import Params
from openpilot.common.spinner import Spinner
from openpilot.common.swaglog import cloudlog
from openpilot.system.hardware import HARDWARE
from openpilot.system.hardware.hw import Paths

UNREGISTERED_DONGLE_ID = "UnregisteredDevice"

SUNNYLINK_REGISTER_URL = "http://sunnylink.local/api/register"  # ✅ 你的 SunnyLink 注册接口

def register(show_spinner=False) -> str:
  params = Params()
  dongle_id = params.get("DongleId", encoding='utf-8')

  if dongle_id and dongle_id != UNREGISTERED_DONGLE_ID:
    return dongle_id

  imei1 = "865420071781912"
  imei2 = "865420071781904"
  serial = HARDWARE.get_serial()

  pubkey_path = Path(Paths.persist_root() + "/comma/id_rsa.pub")
  if not pubkey_path.is_file():
    cloudlog.warning("Missing public key file")
    params.put("DongleId", UNREGISTERED_DONGLE_ID)
    return UNREGISTERED_DONGLE_ID

  with open(pubkey_path) as f:
    public_key = f.read().strip()

  data = {
    "serial": serial,
    "imei1": imei1,
    "imei2": imei2,
    "public_key": public_key,
    "timestamp": datetime.utcnow().isoformat()
  }

  if show_spinner:
    spinner = Spinner()
    spinner.update("Registering with SunnyLink...")

  try:
    r = requests.post(SUNNYLINK_REGISTER_URL, json=data, timeout=10)
    if r.status_code == 200:
      resp = r.json()
      dongle_id = resp.get("dongle_id", UNREGISTERED_DONGLE_ID)
      cloudlog.info(f"Registered: {dongle_id}")
    else:
      dongle_id = UNREGISTERED_DONGLE_ID
      cloudlog.error(f"SunnyLink registration failed: {r.status_code}")
  except Exception as e:
    cloudlog.exception("Exception during SunnyLink registration")
    dongle_id = UNREGISTERED_DONGLE_ID

  if show_spinner:
    spinner.close()

  params.put("DongleId", dongle_id)
  return dongle_id


if __name__ == "__main__":
  print("DongleId:", register(show_spinner=True))
