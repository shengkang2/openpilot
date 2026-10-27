#!/usr/bin/env python3
import cereal.messaging as messaging
from openpilot.common.params import Params
from openpilot.common.realtime import config_realtime_process
from openpilot.selfdrive.monitoring.policy import DriverMonitoring


def dmonitoringd_thread():
  # This process is only started while driver monitoring is allowed to run
  # (process_config.dmonitoringd_enabled -> dm_availability). Turning DM off stops
  # it, and the consumers were taught to treat driverMonitoringState as
  # never-published. There is deliberately no "fake packet" path any more: keeping a
  # synthetic 20 Hz packet alive meant DM never really stopped, and its 1-2 s param
  # re-check is what used to surface a stale alert on spbp.
  config_realtime_process([0, 1, 2, 3], 5)

  params = Params()
  pm = messaging.PubMaster(['driverMonitoringState'])
  sm = messaging.SubMaster(['driverStateV2', 'liveCalibration', 'carState', 'selfdriveState', 'modelV2',
                            'carControl'], poll='driverStateV2')

  DM = DriverMonitoring(rhd_saved=params.get_bool("IsRhdDetected"), always_on=params.get_bool("AlwaysOnDM"))
  demo_mode = False

  # 20Hz <- dmonitoringmodeld
  while True:
    sm.update()
    if not sm.updated['driverStateV2']:
      # iterate when model has new output
      continue

    valid = sm.all_checks()
    if demo_mode and sm.valid['driverStateV2']:
      DM.run_step(sm, demo=True)
    elif valid:
      DM.run_step(sm, demo=demo_mode)

    # publish
    dat = DM.get_state_packet(valid=valid)
    pm.send('driverMonitoringState', dat)

    # load live always-on / driver view toggles. DriverModelEnable is NOT polled here
    # on purpose: manager owns that transition (it stops this process within a second),
    # so this process never has to second-guess the switch mid-drive.
    if sm['driverStateV2'].frameId % 40 == 1:
      DM.always_on = params.get_bool("AlwaysOnDM")
      demo_mode = params.get_bool("IsDriverViewEnabled")

    # save rhd virtual toggle every 5 mins
    if (sm['driverStateV2'].frameId % 6000 == 0 and not demo_mode and
     DM.wheelpos_offsetter.filtered_stat.n > DM.settings._WHEELPOS_FILTER_MIN_COUNT and
     DM.wheel_on_right == (DM.wheelpos_offsetter.filtered_stat.M > DM.settings._WHEELPOS_THRESHOLD)):
      params.put_bool("IsRhdDetected", DM.wheel_on_right)

def main():
  dmonitoringd_thread()


if __name__ == '__main__':
  main()
