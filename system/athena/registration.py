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

def is_registered_device() -> bool:
  dongle = Params().get("DongleId", encoding='utf-8')
  return dongle not in (None, UNREGISTERED_DONGLE_ID)


def register(show_spinner=False) -> str | None:
  params = Params()

  dongle_id: str | None = params.get("DongleId", encoding='utf8')
  if dongle_id is None and Path(Paths.persist_root()+"/comma/dongle_id").is_file():
    with open(Paths.persist_root()+"/comma/dongle_id") as f:
      dongle_id = f.read().strip()

  pubkey = Path(Paths.persist_root()+"/comma/id_rsa.pub")
  privkey = Path(Paths.persist_root()+"/comma/id_rsa")
  if not pubkey.is_file() or not privkey.is_file():
    dongle_id = UNREGISTERED_DONGLE_ID
    cloudlog.warning(f"missing key files: {pubkey} or {privkey}")
  elif dongle_id is None:
    if show_spinner:
      spinner = Spinner()
      spinner.update("registering device")

    # 读取公私钥
    with open(pubkey) as f1, open(privkey) as f2:
      public_key = f1.read()
      private_key = f2.read()

    # 固定 IMEI 与获取序列号
    serial = HARDWARE.get_serial()
    imei1 = "865420071781912"
    imei2 = "865420071781904"
    params.put("IMEI", imei1)
    params.put("HardwareSerial", serial)

    # 注册流程
    backoff = 0
    start_time = time.monotonic()
    while True:
      try:
        register_token = jwt.encode(
          {'register': True, 'exp': datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1)},
          private_key, algorithm='RS256'
        )

        cloudlog.info("getting pilotauth")
        resp = api_get("v2/pilotauth/", method='POST', timeout=15,
                       imei=imei1, imei2=imei2, serial=serial,
                       public_key=public_key, register_token=register_token)

        if resp.status_code in (402, 403):
          cloudlog.info(f"Unable to register device, got {resp.status_code}")
          dongle_id = UNREGISTERED_DONGLE_ID
        else:
          dongleauth = json.loads(resp.text)
          dongle_id = dongleauth["dongle_id"]
        break
      except Exception:
        cloudlog.exception("failed to authenticate")
        backoff = min(backoff + 1, 15)
        time.sleep(backoff)

      if time.monotonic() - start_time > 60 and show_spinner:
        spinner.update(f"registering device - serial: {serial}")
        return UNREGISTERED_DONGLE_ID

    if show_spinner:
      spinner.close()

  if dongle_id:
    params.put("DongleId", dongle_id)
    set_offroad_alert("Offroad_UnofficialHardware", (dongle_id == UNREGISTERED_DONGLE_ID) and not PC)
  return dongle_id


if __name__ == "__main__":
  print(register())
