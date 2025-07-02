#!/usr/bin/env python3
import time
import json
import jwt
from pathlib import Path
from datetime import datetime, timedelta
from openpilot.common.api import api_get
from openpilot.common.params import Params
from openpilot.common.spinner import Spinner
from openpilot.selfdrive.selfdrived.alertmanager import set_offroad_alert
from openpilot.system.hardware import HARDWARE, PC
from openpilot.system.hardware.hw import Paths
from openpilot.common.swaglog import cloudlog


UNREGISTERED_DONGLE_ID = "UnregisteredDevice"
MAX_REGISTRATION_TIME_S = 120  # 增加超时，避免 2244 卡住


def is_registered_device() -> bool:
    """
    Check if the device is registered by verifying the DongleId.
    """
    dongle = Params().get("DongleId", encoding='utf-8')
    return dongle not in (None, UNREGISTERED_DONGLE_ID)


def register(show_spinner=False) -> str | None:
    """
    Attempt to register the device. Returns the DongleId or None if registration fails.
    """
    params = Params()

    dongle_id: str | None = params.get("DongleId", encoding='utf8')
    if dongle_id is None and Path(Paths.persist_root() + "/comma/dongle_id").is_file():
        with open(Paths.persist_root() + "/comma/dongle_id") as f:
            dongle_id = f.read().strip()

    # 检查公钥和私钥文件
    pubkey_path = Path(Paths.persist_root() + "/comma/id_rsa.pub")
    privkey_path = Path(Paths.persist_root() + "/comma/id_rsa")

    if not pubkey_path.is_file() or not privkey_path.is_file():
        cloudlog.warning(f"Missing key files: {pubkey_path} or {privkey_path}")
        dongle_id = UNREGISTERED_DONGLE_ID
        params.put("DongleId", dongle_id)
        return dongle_id

    # 如果设备已经注册，直接返回DongleId
    if dongle_id is not None:
        return dongle_id

    # 启动时显示spinner
    if show_spinner:
        spinner = Spinner()
        spinner.update("registering device")

    try:
        # 读取密钥
        with open(pubkey_path) as f1, open(privkey_path) as f2:
            public_key = f1.read()
            private_key = f2.read()

        # 强制使用固定 IMEI 和获取 serial
        serial = HARDWARE.get_serial()
        cloudlog.info(f"Hardware serial: {serial}")

        if not serial:
            cloudlog.warning("Serial not available. Registration may fail.")

        # 固定 IMEI
        imei1 = "865420071781912"
        imei2 = "865420071781904"
        cloudlog.info(f"IMEI1: {imei1}, IMEI2: {imei2}, Serial: {serial}")

        params.put("IMEI", imei1)
        params.put("HardwareSerial", serial)

        # 生成 JWT Token
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

        # 向服务端发送注册请求
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

            # 如果超时，退出
            if time.monotonic() - start_time > MAX_REGISTRATION_TIME_S:
                cloudlog.warning("Registration timed out")
                dongle_id = UNREGISTERED_DONGLE_ID
                break

            if show_spinner:
                spinner.update(f"registering device - IMEI: {imei1}, Serial: {serial}")

    finally:
        if show_spinner:
            spinner.close()

    # 保存注册结果
    params.put("DongleId", dongle_id)

    # 设置 offroad 警告
    set_offroad_alert("Offroad_UnofficialHardware", (dongle_id == UNREGISTERED_DONGLE_ID) and not PC)

    return dongle_id


if __name__ == "__main__":
    # 执行注册函数并打印结果
    print(register())
