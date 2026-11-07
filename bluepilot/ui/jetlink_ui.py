"""
jetlink: what the panels and the onroad icons show of the link.

Everything here reads ui_state.jetlink (the snapshot the 5 Hz params pass takes)
and ui_state.jetlink_state, never the link itself.

The icons are comma's chestnut icons, shipped as selfdrive/assets/icons/
jetlink*.png: the USB GPU and this accelerator are the same idea.
"""
import math
import re
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

# bp: GREEN is kept for ACTIVE alone, so a green word means the big model is
# driving and nothing else. Ready and waiting are neutral/yellow on purpose.
STATE_COLOR = {
  JetlinkState.DISCONNECTED: GREY,
  JetlinkState.UNCOMPILED: ORANGE,
  JetlinkState.READY: GREY,
  JetlinkState.LOADING: GREY,
  JetlinkState.ACTIVE: GREEN,
  JetlinkState.FAILED: ORANGE,
  JetlinkState.WAITING: GREY,
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


def msg_text(msg: str) -> str:
  """A line the join or the provisioning run wrote, in the panel's language.

  Those runs write English into the progress record, and the two that carry a
  number are built with an f-string there, so they are matched here and the
  template is the one translated."""
  if not msg:
    return msg
  for pattern, template in (
      (r'^downloading (\d+) of (\d+) MB$', "Downloading {} of {} MB"),
      (r'^download stalled, retrying in (\d+) s$', "Download stalled, retrying in {} s"),
  ):
    m = re.match(pattern, msg)
    if m:
      return tr(template).format(*m.groups())
  return tr(msg)


def reason_text(reason: str | None) -> str:
  """Why an enabled link cannot run, in the panel's language. A status failure
  is a sentence jetlink built around the error, so its head is the key."""
  if not reason:
    return ''
  head = 'jetlink status failed: '
  if reason.startswith(head):
    return tr('jetlink status failed: {}').format(reason[len(head):])
  return tr(reason)


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
  msg = msg_text(str(p.get('msg', '')))
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
      return tr("Big model unavailable: {}. The small model drives.").format(reason_text(view.reason))
    return tr("Big model unavailable. The small model drives.")
  if state == JetlinkState.WAITING:
    return tr("{} is ready. It swaps in when you stop, release the lane centering, or cancel cruise.").format(big_name)
  if state == JetlinkState.LOADING:
    return tr("The small model drives until the big one is ready.")
  if not view.ready:
    if view.standin:
      return tr("{} drives until {} is ready.").format(view.standin, big_name)
    return tr("{} will drive once Jetlink is ready.").format(big_name)
  return tr("{} will drive; a lost link falls back to the small model and returns once you stop or release control.").format(big_name)


class JetlinkIcons:
  """The three icon textures at one size, and how a state draws."""

  def __init__(self, width: int, height: int):
    self.green = gui_app.texture(f"{ICON_DIR}/jetlink_green.png", width, height)
    self.default = gui_app.texture(f"{ICON_DIR}/jetlink.png", width, height)
    self.orange = gui_app.texture(f"{ICON_DIR}/jetlink_orange.png", width, height)

  # the four the onroad icon shows, by the fork's own rule:
  #   nothing          no link
  #   grey, pulsing    connecting
  #   grey, steady     connected (a swap window still missing is included)
  #   green            the big model is driving, and only then
  # A link that cannot run stays orange, as before.
  GREY_OPACITY = 0.6

  def for_state(self, state: JetlinkState) -> tuple[Union[rl.Texture, None], float]:
    """(texture, opacity) for a state; None while disconnected."""
    if state == JetlinkState.DISCONNECTED:
      return None, 0.0
    if state == JetlinkState.LOADING:
      # a grey pulse, not a white flash: the peak stays the steady grey
      return self.default, 0.25 + (self.GREY_OPACITY - 0.25) * (0.5 - 0.5 * math.cos(rl.get_time() * 6.0))
    if state == JetlinkState.ACTIVE:
      return self.green, 1.0
    if state in (JetlinkState.UNCOMPILED, JetlinkState.FAILED):
      return self.orange, 1.0
    # ready, or waiting for the swap window: connected, nothing running yet
    return self.default, self.GREY_OPACITY


def tint(opacity: float) -> rl.Color:
  return rl.Color(255, 255, 255, int(255 * max(0.0, min(1.0, opacity))))
