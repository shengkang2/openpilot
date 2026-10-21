"""
Single source of truth for "is driver monitoring allowed to run on this unit?".

Two independent things can make DM unavailable:

  * the user switched it off (`DriverModelEnable`, historical name -- True means
    *disabled*), or
  * the unit has no driver-facing camera at all (e.g. 3XL).

When DM is unavailable nothing DM-related may run: dmonitoringmodeld,
dmonitoringd and the driver camera pipeline inside camerad are all stopped, so
the SoC gets the time back. Consumers must therefore treat
`driverMonitoringState` / `driverCameraState` as *never published* rather than
stale -- SubMaster keeps returning the last received packet forever once a
service goes quiet, which is how a stale `alertLevel == 3` used to freeze
`forceDecel` on.

Keeping the decision in one place is what makes the manager, selfdrived,
controlsd, modeld and the UI agree with each other.
"""

import glob

DM_DISABLE_PARAM = "DriverModelEnable"  # True == DM disabled
DRIVER_CAM_SUBDEV_PREFIX = "cam-sensor-driver"

# wide road (0), road (1), driver (2) -- see system/camerad/cameras/hw.h. The driver
# camera is camera_num 2, so camerad's open_v4l_by_name_and_index() needs at least
# three sensor subdevices for it to exist.
CAM_SENSOR_COUNT = 3

_driver_cam_present: bool | None = None


def has_driver_camera() -> bool:
  """Detect the driver camera exactly the way camerad does.

  camerad picks the camera_num'th entry (2) among the v4l subdevices whose sysfs
  name starts with `cam-sensor-driver` (open_v4l_by_name_and_index()). If this
  unit exposes fewer sensor subdevices than CAM_SENSOR_COUNT, there is no driver
  camera to drive, so DM can never produce anything useful.

  Zero matches means we are not on a comma device (PC, CI, ...), so keep the old
  behaviour and report the camera as present.
  """
  global _driver_cam_present
  if _driver_cam_present is None:
    count = 0
    for path in glob.glob("/sys/class/video4linux/v4l-subdev*/name"):
      try:
        with open(path) as f:
          if f.read().strip().startswith(DRIVER_CAM_SUBDEV_PREFIX):
            count += 1
      except OSError:
        pass
    _driver_cam_present = count == 0 or count >= CAM_SENSOR_COUNT
  return _driver_cam_present


def driver_monitoring_disabled(params) -> bool:
  """True when no DM code should run at all."""
  return params.get_bool(DM_DISABLE_PARAM) or not has_driver_camera()
