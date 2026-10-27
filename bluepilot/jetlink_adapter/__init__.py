"""
jetlink adapter for BluePilot bp-7.0 on a comma three.

Ported from herizon1054's dragonpilot adapter
(dragonpilot/jetlink_adapter/__init__.py, itself ported from zoompilot's
openpilot/sunnypilot/jetlink_adapter/__init__.py; Copyright (c) 2026-, Zeph
Leggett, MIT License; see jetlink_repo/LICENSE).

jetlink (jetlink_repo, vendored) runs comma's large driving model on a computer
attached to the comma's USB-C port (Jetson / Linux PC / Mac over USB, iPhone
over the cable's network) and never imports openpilot. It declares what it
needs as jetlink.openpilot.interface.Openpilot; Adapter below implements it
over this fork. The hooks in manager, modeld, hardwared, selfdrived and the UI
call the functions at the bottom, which answer as if the link were off when
jetlink is not present or speaks another API.

manager imports this module to build the process list and runs it as
jetlinkd, the resident USB gadget owner (~10 MB). So the top level is the
standard library only; everything else is imported where it is used.

bp-7.0 (sunnypilot base) divergences from the dragonpilot port (search "bp:"):
  - MADS exists: in_control() is zoompilot's own rule again (openpilot enabled,
    or MADS enabled, which counts while paused), read off carControl and
    carControlSP. DragonPilot's ALKA substitute (lkasOn on carStateExt,
    SWAP_WHILE_PARKED) is gone, and so is the controlsd hold in
    ALKA_HOLD_SECONDS: MADS stays paused through bigModelLoading by itself.
  - modelDataV2SP exists: acceleratorState and bigModel ride on sunnypilot's
    own ModelDataV2SP, which modeld already publishes, instead of a new
    ModelExt struct. The onroad events stay native (EventName @100-@103,
    the next free ordinals: capnp wants them sequential).
  - model manager: sunnypilot's ModelManagerSP and Paths.model_root() exist,
    so the big-model catalog can be folded into sunnypilot's own list later
    (should_extend_catalog/extend_catalog below). For this version the pick
    and the catalog are this fork's own params, and with no pick the link
    FOLLOWS THE FAR END, so the phone's or Jetson's own model menu is the menu.
  - modeld: selfdrive/modeld/modeld.py on bp-7.0 is the same two-JIT modeld
    (warp_enqueue + run_policy, input_queues + npy, no state_pairs) that
    jetlink 0.8.7's prepare_reset already handles for dragonpilot, so the
    vendored jetlink is unmodified. build_warp.py is still needed: bp-7.0
    has no standalone driving_warp_*.pkl either.
  - USB GPU: bp-7.0 knows comma's chestnut (UsbGpuPresent/UsbGpuCompiled), and
    jetlinkd stands down for it.
"""
from __future__ import annotations

import functools
import os
import sys
import threading
from collections import namedtuple
from pathlib import Path

# the version of jetlink.openpilot's API this adapter is written to; any other
# is treated as jetlink being absent, with the reason as the offroad alert.
# 3 (jetlink 0.8.7): the joining model asks Adapter.in_control() before every
# frame; modeld no longer writes it. The warp is a driving-warp pickle dict
# ({'run', 'input_specs'}), built by build_warp.py, not by jetlink
API = 3

# the gadget owner, as manager names the process and selfdrived lists it
OWNER = 'jetlinkd'

# the Jetlink setting, stored as an index: jetlink.openpilot.MODES,
# written out so the panels build the setting without a jetlink checkout
MODES = ('off', 'usb', 'ios')

# the params jetlink reads and writes, all declared in common/params_keys.h.
# bp: the big-model slot ({ref, displayName}, unset = follow the far end) and
# the catalog ({bundles}) are this fork's own, beside sunnypilot's model list
_Keys = namedtuple('_Keys', 'link offroad progress spec pointers big_model catalog charge_phone')
KEYS = _Keys(link='JetlinkLink', offroad='IsOffroad', progress='AcceleratorProgress', spec='JetlinkSpec',
             pointers='JetlinkModelPointers', big_model='JetlinkBigModel', catalog='JetlinkCatalog',
             charge_phone=None)  # phone charging sealed (jetlink.comma.port.PHONE_CHARGING_SEALED): no param turns it on

# the selector version jetlink's registry filters catalogs by (jetlink.registry.catalog.REQUIRED_SELECTOR_VERSION)
CATALOG_SELECTOR = 19

# what the catalog param holds before the first refresh: jetlink's default big model
# alone, so a comma that never went online still has a model to name and provision
_DEFAULT_CATALOG = {'bundles': [{'ref': 'bf3e3631b3f91d92a1020a5e0dd4298b93ff4244', 'display_name': 'Cinque Terre V3 Model',
                                 'short_name': 'CTV3', 'index': 0, 'is_big': True,
                                 'minimum_selector_version': str(CATALOG_SELECTOR)}]}

# jetlink 0.8.7: the pins zoompilot's extra list (jetlink_repo/catalog/extra_big_models.json)
# carries, {ref: {'oid', 'size'}}: the ONNX jetlink runs for that commit whatever a lookup said.
# Mountain Dew Model (6f4c0faf) runs the retrained model comma shipped, not the earlier one
_PINNED_POINTERS = {
  '6f4c0faf1f85132734e94aa39c67143f823b9324': {
    'oid': '87fe86ca0813c099efddf9173ba503be2e40ea4c5362c36812a44141f4cb07d4', 'size': 792430559},
}

# comma's chestnut (USB GPU), running and in its ROM. The comma's USB-C port
# hosts one and is never held as a jetlink device beside it
CHESTNUT_IDS = frozenset({(0xADD1, 0x0001), (0x3801, 0x0001), (0xADD1, 0x0002), (0x174C, 0x2464), (0x174C, 0x2463)})

# where the build puts the warp for each camera (SConscript) and modeld loads
# it from: in the fork's tree, never in jetlink_repo
WARP_DIR = Path(__file__).resolve().parent / 'models'

OWNER_LOG = Path('/data/log/jetlink-owner.log')

_AGNOS = os.path.isfile('/AGNOS')

# what in_control() reads; modeld subscribes to all of them
IN_CONTROL = ('carControl', 'carControlSP')


def _params_dir() -> Path:
  """The params store's directory, by params.cc and hw.h's rule: PARAMS_ROOT,
  else /data/params on a device and ~/.comma<OPENPILOT_PREFIX>/params
  elsewhere, then /<OPENPILOT_PREFIX, or d>. Environment only, never raises."""
  prefix = os.environ.get('OPENPILOT_PREFIX', '')
  root = os.environ.get('PARAMS_ROOT')
  if root is None:
    root = '/data/params' if _AGNOS else os.path.join(os.environ.get('HOME', ''), '.comma' + prefix, 'params')
  return Path(root) / os.environ.get('OPENPILOT_PREFIX', 'd')


def _model_root() -> Path:
  """bp: sunnypilot's model root. jetlink keeps its ONNX downloads in
  <root>/jetlink, which the model manager's cache clear leaves alone."""
  from openpilot.system.hardware.hw import Paths
  return Path(Paths.model_root())


def warp_path(cam_w: int, cam_h: int, model_w: int, model_h: int) -> Path:
  """The warp for one geometry: the build's target and what modeld opens. jetlink
  0.8.7's format (openpilot's driving warp dict, build_warp.py) under a new name,
  so a 0.8.5-format pickle (a bare TinyJit) left by an older build is never opened."""
  return WARP_DIR / f'driving_warp_{cam_w}x{cam_h}_{model_w}x{model_h}_tinygrad.pkl'


def chestnut_present() -> bool:
  """A sysfs walk for any CHESTNUT_IDS device: sunnypilot's helpers.usbgpu_present
  only knows the running board's id, and the link must stand down for all of them."""
  for d in Path("/sys/bus/usb/devices").glob("*"):
    try:
      if (int((d / "idVendor").read_text(), 16), int((d / "idProduct").read_text(), 16)) in CHESTNUT_IDS:
        return True
    except Exception:
      pass
  return False


def owner_config():
  """What jetlinkd needs: data only, so the owner imports nothing heavy."""
  from jetlink.openpilot.interface import Keys, OwnerConfig

  from openpilot.common.basedir import BASEDIR
  # the provisioning run starts in the checkout with the checkout on its path,
  # where the tree links jetlink_repo/jetlink in as jetlink
  return OwnerConfig(params_dir=_params_dir(), keys=Keys(**KEYS._asdict()), chestnut_ids=CHESTNUT_IDS,
                     adapter=__name__, cwd=Path(BASEDIR), env={'PYTHONPATH': BASEDIR}, log_file=OWNER_LOG)


def main() -> None:
  """jetlinkd: hold the USB gadget until manager stops this process."""
  from jetlink.openpilot.owner import main as run_owner
  run_owner(owner_config())


def adapter() -> 'Adapter':
  """The adapter, for jetlink's entry points that run as their own process:
  the provisioning run and the warp build."""
  return Adapter()


def _modeld_module():
  """bp-7.0's modeld module. manager runs it as `selfdrive.modeld.modeld`;
  reuse that one inside modeld rather than importing a second copy under the
  `openpilot.` alias (it would re-run modeld's module level)."""
  mod = sys.modules.get('selfdrive.modeld.modeld') or sys.modules.get('openpilot.selfdrive.modeld.modeld')
  if mod is None:
    import importlib
    mod = importlib.import_module('openpilot.selfdrive.modeld.modeld')
  return mod


class SmallModel:
  """bp-7.0's ModelState as jetlink's joining model calls it.

  jetlink's 4th positional argument to run() is `after_enqueue`, a callable it
  calls once the frame is on the link; bp's is `prepare_only`, a bool that
  suppresses the policy. Passing None is harmless either way, passing the
  callable is not (a truthy prepare_only would skip every frame), so modeld
  hands jetlink this instead of the ModelState itself. Reads and writes go
  through to it, since the joining model forwards both.
  """

  def __init__(self, model):
    object.__setattr__(self, '_model', model)

  def run(self, bufs, transforms, inputs, after_enqueue=None):
    result = self._model.run(bufs, transforms, inputs, False)
    # bp has no chestnut to publish a state for mid-frame; the hook is kept
    # because jetlink passes it and calls it for its own telemetry
    if after_enqueue is not None:
      after_enqueue()
    return result

  def __getattr__(self, name):
    if name.startswith('_'):
      raise AttributeError(name)
    return getattr(self._model, name)

  def __setattr__(self, name, value):
    setattr(self._model, name, value)


def _small_model(model) -> SmallModel:
  return model if isinstance(model, SmallModel) else SmallModel(model)


class Adapter:
  """jetlink.openpilot.interface.Openpilot over BluePilot bp-7.0."""

  def __init__(self):
    from jetlink.openpilot.interface import Keys

    from openpilot.common.basedir import BASEDIR
    from openpilot.common.swaglog import cloudlog
    self.keys = Keys(**KEYS._asdict())
    self.log = cloudlog
    self.basedir = Path(BASEDIR)
    # one Params per store (a test or a bench runs under its own prefix)
    self._stores: dict[Path, object] = {}

  # -- params ---------------------------------------------------------------

  def params_dir(self) -> Path:
    return _params_dir()

  def _params(self):
    where = _params_dir()
    store = self._stores.get(where)
    if store is None:
      from openpilot.common.params import Params
      store = self._stores[where] = Params()
    return store

  def get(self, key: str):
    # read from hardwared's and the UI's threads: an unknown key must not take them down
    try:
      value = self._params().get(key)
    except Exception:
      value = None
    if key == KEYS.catalog and not (isinstance(value, dict) and value.get('bundles')):
      return _DEFAULT_CATALOG
    if key == KEYS.pointers:
      return {**(value if isinstance(value, dict) else {}), **_PINNED_POINTERS}
    return value

  def follow_far_end(self) -> bool:
    """No model picked on the comma: the far end's loaded model drives
    (jetlink.openpilot.link.open_link, provision.run)."""
    return follows_far_end(self.get(KEYS.big_model))

  def put(self, key: str, value, *, block: bool = False) -> None:
    self._params().put(key, value, block=block)

  def remove(self, key: str) -> None:
    self._params().remove(key)

  # -- the device -------------------------------------------------------------

  def chestnut_present(self) -> bool:
    return chestnut_present()

  def camera(self) -> tuple[int, int, int, int]:
    # the camera modeld runs on this device (modeld/SConscript builds both)
    from openpilot.system.hardware import HARDWARE
    from openpilot.common.transformations.camera import _ar_ox_fisheye, _os_fisheye
    from openpilot.common.transformations.model import MEDMODEL_INPUT_SIZE
    camera = _os_fisheye if HARDWARE.get_device_type() == "mici" else _ar_ox_fisheye
    return camera.width, camera.height, *MEDMODEL_INPUT_SIZE

  def warp_path(self, cam_w: int, cam_h: int, model_w: int, model_h: int) -> Path:
    return warp_path(cam_w, cam_h, model_w, model_h)

  def model_root(self) -> Path:
    return _model_root()

  # the big-model catalog's selector, as the phone apps list it
  catalog_selector = CATALOG_SELECTOR

  # -- modeld -----------------------------------------------------------------

  def model_face(self):
    """comma's large model's face, from bp-7.0's modeld: Parser, constants,
    smoothing and action function."""
    from jetlink.openpilot.interface import ModelFace

    from openpilot.selfdrive.modeld.constants import ModelConstants
    from openpilot.selfdrive.modeld.parse_model_outputs import Parser
    from openpilot.system.camerad.cameras.nv12_info import get_nv12_info
    modeld = _modeld_module()
    return ModelFace(parser=Parser, frame_size=lambda w, h: get_nv12_info(w, h)[3], desire_len=ModelConstants.DESIRE_LEN,
                     constants=ModelConstants, lat_smooth_seconds=modeld.LAT_SMOOTH_SECONDS,
                     long_smooth_seconds=modeld.LONG_SMOOTH_SECONDS, get_action_from_model=modeld.get_action_from_model)

  def event(self, name: str, **fields) -> None:
    self.log.event(name, **fields)

  # -- control ----------------------------------------------------------------

  def in_control(self) -> bool:
    """Is openpilot or MADS in control? jetlink API 3: the joining model asks on
    modeld's frame thread before every frame and swaps the large model in only
    while not. True when it cannot tell; never raises (module in_control is
    guarded). Reads modeld's SubMaster (use_submaster), updated just before
    run(); a SubMaster of the adapter's when modeld has not handed one over."""
    sm = _submaster
    if sm is None:
      try:
        sm = _own_submaster()
        sm.update(0)
      except Exception as e:
        _log_failure("in_control(): no SubMaster", e)
        return True
    return in_control(sm)


# -- bp: the model menu ---------------------------------------------------------
# The phone and Mac apps pick their model from the big-model catalog and report,
# in every hello, the sha256 of the model they have loaded and the ones they
# have built (kept by jetlinkd in /dev/shm/jetlink/server.json). The comma
# fetches the same catalog, resolves each model's sha256 once, and so can name
# the phone's models and offer them.

FOLLOW = 'follow'
SERVER_RECORD = Path('/dev/shm/jetlink/server.json')


def follows_far_end(slot) -> bool:
  """The slot is unset, or set to follow the far end."""
  return not (isinstance(slot, dict) and isinstance(slot.get('ref'), str) and slot.get('ref') and slot.get('ref') != FOLLOW)


def far_end_models() -> tuple[str | None, list[str]]:
  """(loaded sha256 or None, built sha256s) from the far end's last hello."""
  import json
  try:
    heard = json.loads(SERVER_RECORD.read_text())
  except (OSError, ValueError):
    return None, []
  if not isinstance(heard, dict):
    return None, []
  loaded = heard.get('loaded') if isinstance(heard.get('loaded'), str) and heard.get('loaded') else None
  built = [s for s in (heard.get('cached_models') or []) if isinstance(s, str)]
  return loaded, built


def model_menu(params=None) -> list[dict]:
  """Every catalog model, newest first: {ref, name, sha256 or None, size or None,
  loaded (on the far end now), built (on the far end), downloaded (on the comma)}."""
  from openpilot.common.params import Params
  params = params or Params()
  catalog = params.get(KEYS.catalog)
  bundles = catalog.get('bundles') if isinstance(catalog, dict) and catalog.get('bundles') else _DEFAULT_CATALOG['bundles']
  pointers = params.get(KEYS.pointers)
  pointers = {**(pointers if isinstance(pointers, dict) else {}), **_PINNED_POINTERS}
  loaded, built = far_end_models()
  root = _model_root() / 'jetlink'
  rows = []
  for b in sorted((b for b in bundles if isinstance(b, dict) and b.get('ref')), key=lambda b: int(b.get('index', 0)), reverse=True):
    p = pointers.get(b['ref']) or {}
    sha, size = p.get('oid'), p.get('size')
    try:
      downloaded = bool(sha) and (root / f"{sha[:16]}.onnx").stat().st_size == int(size)
    except (OSError, TypeError, ValueError):
      downloaded = False
    rows.append({'ref': b['ref'], 'name': str(b.get('display_name') or b['ref'][:10]), 'sha256': sha, 'size': size,
                 'loaded': bool(sha) and sha == loaded, 'built': bool(sha) and sha in built, 'downloaded': downloaded})
  return rows


def model_name(sha256: str | None, params=None) -> str | None:
  """The catalog's name for a sha256 the far end reported, else its first 16 characters."""
  if not sha256:
    return None
  for row in model_menu(params):
    if row['sha256'] == sha256:
      return row['name']
  return sha256[:16]


def pick_model(ref: str | None, params=None) -> None:
  """Pick a catalog model on the comma, or None to follow the far end."""
  from openpilot.common.params import Params
  params = params or Params()
  if not ref or ref == FOLLOW:
    params.remove(KEYS.big_model)
    return
  name = next((r['name'] for r in model_menu(params) if r['ref'] == ref), ref[:10])
  params.put(KEYS.big_model, {'ref': ref, 'displayName': name})


def refresh_catalog(params=None, resolve: bool = True) -> int:
  """Fetch the big-model catalogs (the pinned one, every newer one and
  zoompilot's extras, as the phone apps do), keep its big models, and resolve
  each one's sha256 and size from comma's LFS pointer once. Network, seconds to
  a minute: run it off the UI thread. Returns the number of models listed."""
  from jetlink.registry.catalog import fetch_catalogs, REQUIRED_SELECTOR_VERSION
  from jetlink.registry.lfs import fetch_pointer
  from openpilot.common.params import Params
  params = params or Params()
  merged = fetch_catalogs()
  # jetlink 0.8.7: zoompilot's extra list pins some commits to the ONNX jetlink runs for them
  # (catalog.pinned_pointers), written over whatever a lookup found, as models.keep_pins does
  pins = {**_PINNED_POINTERS, **(merged.pop('pointers', None) or {})}
  bundles = [b for b in merged.get('bundles', []) if isinstance(b, dict) and b.get('is_big')
             and str(b.get('minimum_selector_version')) == str(REQUIRED_SELECTOR_VERSION)]
  if not bundles:
    raise RuntimeError("the catalog lists no big model")
  params.put(KEYS.catalog, {'bundles': bundles})
  # a model the catalog withdrew is no longer a pick; the comma follows the far
  # end again, whose 0.8.7 app switches it to Cinque Terre V3
  slot = params.get(KEYS.big_model)
  if not follows_far_end(slot) and slot['ref'] not in {b['ref'] for b in bundles}:
    params.remove(KEYS.big_model)
    _log_failure(f"the picked model {slot['ref'][:10]} is no longer listed; following the far end", None)
  pointers = params.get(KEYS.pointers)
  pointers = dict(pointers) if isinstance(pointers, dict) else {}
  if pins:
    pointers.update(pins)
    params.put(KEYS.pointers, pointers, block=True)
  if resolve:
    for b in bundles:
      if b['ref'] in pointers:
        continue
      try:
        p = fetch_pointer(b['ref'], timeout=10.0)
        pointers[b['ref']] = {'oid': p.oid, 'size': p.size}
      except Exception as e:
        _log_failure(f"could not resolve {b['ref'][:10]}: {e}", None)
    params.put(KEYS.pointers, pointers, block=True)
  return len(bundles)


# -- what the hooks call ------------------------------------------------------

class _Absent:
  """jetlink's answers when it cannot run here: not present (why is None), or
  a package this build cannot use (why says so, as the offroad alert, to
  someone who turned the link on)."""

  def __init__(self, why: str | None):
    self.why = why

  def enabled(self) -> bool:
    return False

  def status(self):
    return None

  def reason(self) -> str | None:
    if self.why is None:
      return None
    try:
      on = 0 < int((_params_dir() / KEYS.link).read_bytes()) < len(MODES)
    except (OSError, ValueError):
      on = False
    return self.why if on else None

  def prepare(self) -> bool:
    return False

  def attach(self, small, cam_w: int, cam_h: int):
    return None

  def request_shutdown(self, reason: str = '') -> bool:
    return False

  def shutdown_pending(self) -> bool:
    return False

  def should_extend_catalog(self) -> bool:
    return False

  def extend_catalog(self, catalog: dict) -> dict:
    return catalog

  def model_state(self, ref: str) -> str | None:
    return None


_bound = None
_binding = threading.Lock()


def _api():
  """jetlink for this process, bound to the adapter on first use. One per
  process: prepare() and attach() have to reach the same one."""
  global _bound
  if _bound is None:
    with _binding:
      if _bound is None:
        _bound = _bind()
  return _bound


def _bind():
  try:
    import jetlink
    if getattr(jetlink, '__file__', None) is None:
      return _Absent(None)   # an empty jetlink_repo, which Python takes for a namespace package
    import jetlink.openpilot as jl
  except ModuleNotFoundError as e:
    if e.name == 'jetlink':
      return _Absent(None)   # not in this tree: the link does not exist on this device
    if (e.name or '').startswith('jetlink.'):
      return _unusable("jetlink package too old for this build", e)
    return _unusable(f"jetlink failed to load: {e}", e)
  except Exception as e:
    return _unusable(f"jetlink failed to load: {type(e).__name__}: {e}", e)
  api = getattr(jl, 'API', None)
  if api != API:
    return _unusable(f"jetlink package API {api}, this build expects {API}")
  try:
    return jl.bind(Adapter())
  except Exception as e:
    return _unusable(f"jetlink failed to start: {type(e).__name__}: {e}", e)


def _unusable(why: str, error: Exception | None = None) -> _Absent:
  _log_failure(why, error)
  return _Absent(why)


# Hook -> the failure last logged for it, cleared by a call that works
_failed_hooks: dict[str, str] = {}


def _log_failure(what: str, error: Exception | None) -> None:
  try:
    from openpilot.common.swaglog import cloudlog
    cloudlog.error("jetlink: %s", what, exc_info=error)
  except Exception:
    pass


def _guarded(default):
  """Whatever jetlink does wrong turns the link off and is logged, and never
  takes manager, hardwared, modeld or the UI down."""
  def wrap(hook):
    @functools.wraps(hook)
    def call(*args, **kwargs):
      try:
        result = hook(*args, **kwargs)
      except Exception as e:
        error = f"{type(e).__name__}: {e}"
        if _failed_hooks.get(hook.__name__) != error:
          _failed_hooks[hook.__name__] = error
          _log_failure(f"{hook.__name__}() failed", e)
        return default(*args, **kwargs) if callable(default) else default
      _failed_hooks.pop(hook.__name__, None)
      return result
    return call
  return wrap


@_guarded(False)
def should_run(started: bool, params, CP) -> bool:
  """manager's rule for jetlinkd: the link is on and no chestnut is fitted.
  jetlinkd runs onroad too: a gadget whose owner exits leaves the bus."""
  # Reserve the USB port for an enabled USB GPU even while it is enumerating.
  if params.get_bool("UsbGpuPresent"):
    return False
  return _api().enabled()


@_guarded(None)
def status():
  """One snapshot for the UI (jetlink.openpilot.Status), or None without jetlink."""
  return _api().status()


@_guarded(None)
def reason() -> str | None:
  """Why the link the user turned on cannot run: hardwared's offroad alert."""
  return _api().reason()


@_guarded(False)
def prepare() -> bool:
  """modeld, before config_realtime_process: will the link join this modeld?"""
  return _api().prepare()


_submaster = None
_own = None


def use_submaster(sm) -> None:
  """modeld, once: the SubMaster it updates before every frame, which subscribes
  to IN_CONTROL. Adapter.in_control() reads it."""
  global _submaster
  _submaster = sm


def _own_submaster():
  global _own
  if _own is None:
    from cereal import messaging
    _own = messaging.SubMaster(list(IN_CONTROL))
  return _own


@_guarded(True)
def in_control(sm) -> bool:
  """modeld, before every frame, onto the model: is openpilot or MADS in
  control? jetlink's large model swaps in only while it is not.

  bp: zoompilot's rule, unchanged. openpilot enabled or steering, or MADS
  enabled, which counts while paused (gear, door, seatbelt, brake hold, park
  brake, stock LKAS off: it steers again on its own) and is released by ACC
  main off or its button. A service late or invalid counts as in control, so a
  swap can never happen on no information."""
  if not (sm.all_alive(IN_CONTROL) and sm.all_valid(IN_CONTROL)):
    return True
  if sm['carControl'].enabled or sm['carControl'].latActive:
    return True
  mads = sm['carControlSP'].mads
  return bool(mads.enabled or mads.active)


@_guarded(None)
def attach(small, cam_w: int, cam_h: int):
  """modeld, once the camera is up and `small` is built: the model to run,
  `small` driving until the link has joined; None unless prepare() said yes."""
  return _api().attach(_small_model(small), cam_w, cam_h)


@_guarded(False)
def request_shutdown(reason: str = '') -> bool:
  """hardwared, once, when the comma is about to power off for good: ask for
  the far end to go down with it."""
  return _api().request_shutdown(reason)


@_guarded(False)
def shutdown_pending() -> bool:
  """hardwared, every loop after request_shutdown(), until it puts DoShutdown."""
  return _api().shutdown_pending()


@_guarded(None)
def model_state(ref: str) -> str | None:
  return _api().model_state(ref)
