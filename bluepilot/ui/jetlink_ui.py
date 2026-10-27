"""
jetlink: what the panels and the onroad icons show of the link.

Everything here reads ui_state.jetlink (the snapshot the 5 Hz params pass takes)
and ui_state.jetlink_state, never the link itself.

The icons are comma's chestnut icons, shipped as selfdrive/assets/icons/
jetlink*.png: the USB GPU and this accelerator are the same idea.
"""
import math
from typing import Union

import pyray as rl

from openpilot.selfdrive.ui.ui_state import ui_state, JetlinkState
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr  # __JETLINK_I18N__
from openpilot.bluepilot.jetlink_adapter import KEYS, MODES

LINK_MODES = MODES
LINK_PARAM = KEYS.link
LINK_MODE_TITLES = {"off": "Off", "usb": "USB", "ios": "iOS"}

ICON_DIR = "icons"

NONE_TEXT = "None"

# one short word per state, for the settings panel and the icons' tooltips
STATE_TEXT = {
  JetlinkState.DISCONNECTED: "No device",
  JetlinkState.UNCOMPILED: "Not built",
  JetlinkState.READY: "Ready",
  JetlinkState.LOADING: "Loading",
  JetlinkState.ACTIVE: "Big model",
  JetlinkState.FAILED: "Failed",
  JetlinkState.WAITING: "Re-engage",
}

GREEN = rl.Color(128, 216, 166, 255)
YELLOW = rl.Color(218, 202, 37, 255)
ORANGE = rl.Color(255, 140, 40, 255)
GREY = rl.Color(166, 166, 166, 255)

STATE_COLOR = {
  JetlinkState.DISCONNECTED: GREY,
  JetlinkState.UNCOMPILED: ORANGE,
  JetlinkState.READY: GREEN,
  JetlinkState.LOADING: YELLOW,
  JetlinkState.ACTIVE: GREEN,
  JetlinkState.FAILED: ORANGE,
  JetlinkState.WAITING: GREEN,
}


def link_mode() -> str:
  """The setting as stored, one of LINK_MODES: shown even when jetlink cannot
  run, so a link that will not start can be turned off."""
  try:
    index = int(ui_state.params.get(LINK_PARAM) or 0)
  except (TypeError, ValueError):
    index = 0
  return LINK_MODES[index] if 0 <= index < len(LINK_MODES) else "off"


def link_toggle_meaningful() -> bool:
  """Offered wherever jetlink is present, except beside a USB GPU, which runs
  the big model itself; and while the setting is on, whatever else."""
  if ui_state.usbgpu:
    return link_mode() != "off"
  return ui_state.jetlink is not None or link_mode() != "off"


def link_status() -> str:
  """One line: what is on the comma's USB-C port right now. jetlink knows a
  Jetson or a phone and the transport says which; below that only the CC pin
  speaks (a cable with a host behind it, not what the host is)."""
  jetlink = ui_state.jetlink
  if jetlink is None:
    return ""
  if jetlink.present:
    return tr("Jetlink connected: {}.").format(jetlink.transport)
  if jetlink.port is None:
    return ""
  return tr("Nothing on the USB-C port.") if jetlink.port == "empty" else tr("A device is on the USB-C port (not answering Jetlink yet).")


def progress() -> tuple[str, float, str] | None:
  """(stage, 0..1, message) while jetlink is working, else None. The message
  names the cable once jetlink counts enough link drops to blame it."""
  jetlink = ui_state.jetlink
  p = jetlink.progress if jetlink is not None else None
  if not p:
    return None
  stage = str(p.get('stage', ''))
  if stage in ('', 'ready'):
    return None
  msg = str(p.get('msg', ''))
  if drops := p.get('drops'):
    hint = tr("check the cable or the app") if jetlink.mode == 'ios' else tr("check the cable")
    msg = tr("{}, {} ({} drops)").format(msg, hint, drops)
  return stage, float(p.get('frac', 0.0)), msg


def status_note(model_name: str | None = None) -> str:
  """The failover story. `model_name`: the model that will drive when the caller
  knows better than the snapshot (following the far end, it is the far end's
  loaded model, not the comma's default)."""
  view = ui_state.jetlink
  if view is None:
    return ""
  big_name = (model_name if model_name and model_name != NONE_TEXT else None) or view.model or tr("the big model")
  state = ui_state.jetlink_state
  if state in (JetlinkState.FAILED, JetlinkState.UNCOMPILED):
    if view.reason:
      return tr("Big model unavailable: {}. The small model drives.").format(view.reason)
    return tr("Big model unavailable. The small model drives.")
  if state == JetlinkState.WAITING:
    return tr("{} is ready. It swaps in as soon as nothing is in control: cancel cruise, then re-engage.").format(big_name)
  if state == JetlinkState.LOADING:
    return tr("The small model drives until the big one is ready.")
  if not view.ready:
    if view.standin:
      return tr("{} drives until {} is ready.").format(view.standin, big_name)
    return tr("{} will drive once Jetlink is ready.").format(big_name)
  return tr("{} will drive; a lost link falls back to the small model and returns when it is back.").format(big_name)


class JetlinkIcons:
  """The three icon textures at one size, and how a state draws."""

  def __init__(self, width: int, height: int):
    self.green = gui_app.texture(f"{ICON_DIR}/jetlink_green.png", width, height)
    self.default = gui_app.texture(f"{ICON_DIR}/jetlink.png", width, height)
    self.orange = gui_app.texture(f"{ICON_DIR}/jetlink_orange.png", width, height)

  def for_state(self, state: JetlinkState) -> tuple[Union[rl.Texture, None], float]:
    """(texture, opacity) for a state; None while disconnected. Loading pulses,
    waiting is a steady dim green, failed is orange, ready/active solid green."""
    if state == JetlinkState.DISCONNECTED:
      return None, 0.0
    if state == JetlinkState.LOADING:
      return self.default, 0.35 + 0.65 * (0.5 - 0.5 * math.cos(rl.get_time() * 6.0))
    if state == JetlinkState.WAITING:
      return self.green, 0.5
    if state in (JetlinkState.UNCOMPILED, JetlinkState.FAILED):
      return self.orange, 1.0
    return self.green, 1.0


def tint(opacity: float) -> rl.Color:
  return rl.Color(255, 255, 255, int(255 * max(0.0, min(1.0, opacity))))
