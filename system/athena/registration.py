#!/usr/bin/env python3
import time
import json
import jwt
from pathlib import Path
from datetime import datetime, timedelta, UTC

from openpilot.common.api import api_get
from openpilot.common.params import Params
from openpilot.common.spinner import Spinner
from openpilot.common.swaglog import cloudlog
from openpilot.system.hardware import HARDWARE, PC
from openpilot.system.hardware.hw import Paths

UNREGISTERED_DONGLE_ID = "UnregisteredDevice"

def is_registered_device() -> bool:
  dongle = Params().get("DongleId", encoding='utf-8')
  return dongle not in (None, UNREGISTERED_DONGLE_ID)

def register(show_spinner=False) -> str | None:
  params = Params()
  dongle_id = params.get("DongleId", encoding='utf8')

  if dongle_id and dongle_id != UNREGISTERED_DONGLE_ID:
    return dongle_id  # 已注册

  imei1 = '865420071781912'
  imei2 = '865420071781904'
  serial = HARDWARE.get_serial()
  params.put("IMEI", imei1)
  params.put("HardwareSerial", serial)

  pubkey_path = Path(Paths.persist_root() + "/comma/id_rsa.pub")
  privkey_path = Path(Paths.persist_root() + "/comma/id_rsa")
  if not pubkey_path.is_file() or not privkey_path.is_file():
    cloudlog.warning("Missing key files")
    params.put("DongleId", UNREGISTERED_DONGLE_ID)
    return UNREGISTERED_DONGLE_ID

  with open(pubkey_path) as f1, open(privkey_path) as f2:
    public_key = f1.read()
    private_key = f2.read()

  if show_spinner:
    spinner = Spinner()
    spinner.update("Registering device...")

  backoff = 1
  start_time = time.monotonic()
  max_wait_time = 30  # seconds

  while True:
    try:
      token = jwt.encode(
        {'register': True, 'exp': datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1)},
        private_key, algorithm='RS256'
      )
      resp = api_get("v2/pilotauth/", method='POST', timeout=15,
                     imei=imei1, imei2=imei2, serial=serial,
                     public_key=public_key, register_token=token)

      if resp.status_code in (402, 403):
        cloudlog.warning(f"Registration rejected: {resp.status_code}")
        dongle_id = UNREGISTERED_DONGLE_ID
      else:
        dongleauth = json.loads(resp.text)
        dongle_id = dongleauth.get("dongle_id", UNREGISTERED_DONGLE_ID)
      break
    except Exception:
      cloudlog.exception("Registration failed, retrying...")
      if time.monotonic() - start_time > max_wait_time:
        dongle_id = UNREGISTERED_DONGLE_ID
        break
      time.sleep(backoff)
      backoff = min(backoff + 1, 10)

  if show_spinner:
    spinner.close()

  params.put("DongleId", dongle_id)
  return dongle_id


if __name__ == "__main__":
  print(register())
