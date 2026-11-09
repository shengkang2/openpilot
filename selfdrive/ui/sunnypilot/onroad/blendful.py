"""
Copyright (c) 2021-, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
from pathlib import Path

import numpy as np
import pyray as rl
from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.common.realtime import DT_MDL
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.selfdrive.ui.sunnypilot.ui_state import UIStateSP
from openpilot.sunnypilot.selfdrive.controls.lib.blendful import LANE_WIDTH_CLIP, LOOKAHEAD_TIME, MIN_LOOKAHEAD
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.shader_polygon import draw_polygon
from openpilot.system.ui.lib.text_measure import measure_text_cached

BLENDFUL_COLOR = (0, 200, 255)
FULL_BAR = 1.0
# the ribbon is always visible while Blendful is on, brighter the more it is trusted
BASE_ALPHA = 0.25
RIBBON_HALF_WIDTH = 0.22
PARAM_RELOAD_FRAMES = 60


class BlendfulRenderer:
  def __init__(self, readout: bool = True, rect_relative: bool = False):
    self._readout = readout
    self._rect_relative = rect_relative
    self._center_points = np.empty((0, 2), dtype=np.float32)
    self._trust = 0.0
    self._enabled = ui_state.params.get_bool("Blendful")
    self._frame = 0
    self._font = gui_app.font(FontWeight.BOLD)
    self._pull_display = FirstOrderFilter(0.0, 0.5, DT_MDL)
    self._trust_display = FirstOrderFilter(0.0, 0.5, DT_MDL)
    self._alpha = FirstOrderFilter(0.0, 0.3, DT_MDL)
    self._diag_n = 0
    self._update_calls = 0
    self._draw_calls = 0
    self._conf = 1.0

  def _clear(self, fade: bool = True) -> None:
    if fade:
      self._alpha.update(0.0)
    self._center_points = np.empty((0, 2), dtype=np.float32)

  def update(self, renderer, max_idx: int, *map_args) -> None:
    sm = ui_state.sm
    self._frame += 1
    self._update_calls += 1
    if self._frame % PARAM_RELOAD_FRAMES == 0:
      self._enabled = ui_state.params.get_bool("Blendful")

    if not sm.valid.get('modelDataV2SP', False):
      self._clear()
      return

    blendful = sm['modelDataV2SP']
    if sm.updated.get('modelDataV2SP', False):
      if blendful.blendfulTrust > 0.0:
        self._trust = blendful.blendfulTrust
      if self._readout:
        lookahead = max(sm['carState'].vEgo * LOOKAHEAD_TIME, MIN_LOOKAHEAD)
        self._pull_display.update(blendful.blendfulCurvature * lookahead ** 2 / 2)
        self._trust_display.update(self._trust)

    left, right = renderer._lane_lines[1].raw_points, renderer._lane_lines[2].raw_points
    stds = list(sm['modelV2'].laneLineStds)
    if not self._enabled or len(left) == 0 or len(right) != len(left) or len(stds) < 3:
      self._clear()
      return

    l_prob, r_prob = blendful.blendfulLeftProb, blendful.blendfulRightProb
    has_probs = l_prob + r_prob > 0.0
    if not has_probs:
      # modeld stops producing lane probs below MIN_SPEED (5 m/s) and while a
      # lane change is in progress. Keep a dim geometric-center guide instead
      # of dropping the ribbon altogether.
      self._trust = 0.0

    half_width = np.clip(right[:, 1] - left[:, 1], *LANE_WIDTH_CLIP) / 2 if l_prob * r_prob > 0.5 else blendful.blendfulLaneWidth / 2
    l_var = stds[1] ** 2 / max(l_prob, 1e-4)
    r_var = stds[2] ** 2 / max(r_prob, 1e-4)
    center = left.copy()
    if has_probs:
      center[:, 1] = (r_var * (left[:, 1] + half_width) + l_var * (right[:, 1] - half_width)) / (l_var + r_var)
    else:
      center[:, 1] = (left[:, 1] + right[:, 1]) / 2
    # Fade the ribbon with lane-fit confidence: on ambiguous markings the model's centre can sit
    # off the road (2026-11-09 road test), and a solid ribbon there actively misleads the driver.
    # Both line probs must be plausible and the geometry tight; below that the ribbon dims out.
    if has_probs:
      conf = float(np.clip(min(l_prob, r_prob) / 0.40, 0.0, 1.0))
      worst_std = float(max(stds[1], stds[2]))
      sharp = float(np.clip((0.80 - worst_std) / (0.80 - 0.25), 0.0, 1.0))
      self._conf = conf * sharp
    else:
      # no probs at all (low speed / lane change): keep the dim geometric-centre guide
      self._conf = 1.0
    self._center_points = renderer._map_line_to_polygon(center, RIBBON_HALF_WIDTH, 0.0, max_idx, *map_args)
    self._alpha.update(1.0 if self._conf > 0.05 else 0.0)

  def _diag_tick(self) -> None:
    self._diag_n += 1
    if self._diag_n % PARAM_RELOAD_FRAMES:
      return
    try:
      import json
      sm = ui_state.sm
      valid = bool(sm.valid.get('modelDataV2SP', False))
      sp = sm['modelDataV2SP'] if valid else None
      data = {
        'enabled': bool(self._enabled),
        'sp_valid': valid,
        'lateral_active': bool(UIStateSP.lateral_active(ui_state)),
        'l_prob': float(sp.blendfulLeftProb) if sp is not None else 0.0,
        'r_prob': float(sp.blendfulRightProb) if sp is not None else 0.0,
        'trust': float(self._trust),
        'alpha': float(self._alpha.x),
        'conf': float(self._conf),
        'center_points': int(self._center_points.shape[0]),
        'update_calls': int(self._update_calls),
        'draw_calls': int(self._draw_calls),
        'sp_seen': bool(sm.seen.get('modelDataV2SP', False)),
        'sp_alive': bool(sm.alive.get('modelDataV2SP', False)),
        'status': str(getattr(ui_state.status, 'value', ui_state.status)),
      }
      Path('/dev/shm/blendful_diag.json').write_text(json.dumps(data))
    except Exception:
      pass

  def _color(self, rgb, alpha: float) -> rl.Color:
    return rl.Color(*rgb, int(alpha * self._alpha.x))

  def draw(self, rect: rl.Rectangle) -> None:
    self._diag_tick()
    self._draw_calls += 1
    # the ribbon follows Blendful's own data, not whether ACC is engaged: the
    # upstream lateral_active gate hides it whenever the car is disengaged
    if self._center_points.size and self._alpha.x > 0.01:
      points = self._center_points + (rect.x, rect.y) if self._rect_relative else self._center_points
      # dim guide ribbon when the lane lines are weak, solid once Blendful trusts them
      alpha = (BASE_ALPHA + (1.0 - BASE_ALPHA) * float(np.clip(self._trust * 2.0, 0.0, 1.0))) * self._alpha.x * self._conf
      draw_polygon(rect, points, self._color(BLENDFUL_COLOR, alpha * 255))
    if self._center_points.size and self._readout and self._trust > 0.05:
      self._draw_readout(rect)

  def _draw_readout(self, rect: rl.Rectangle) -> None:
    pull, trust = self._pull_display.x, self._trust_display.x
    w, h = 190, 76
    x, y = rect.x + (rect.width - w) / 2, rect.y + 10
    cx, cy = x + w / 2, y + 30
    rl.draw_rectangle_rounded(rl.Rectangle(x, y, w, h), 0.5, 12, self._color((0, 0, 0), 170))

    text = f"{abs(pull) * 100:.0f}"
    text_w = measure_text_cached(self._font, text, 44, 0).x
    rl.draw_text_ex(self._font, text, rl.Vector2(cx - text_w / 2, cy - 24), 44, 0, self._color((255, 255, 255), 255))

    active = self._color(BLENDFUL_COLOR, np.clip(abs(pull) / 0.1, 0.0, 1.0) * 255)
    idle = self._color((255, 255, 255), 40)
    lx, rx = x + 18, x + w - 18
    rl.draw_triangle(rl.Vector2(lx, cy), rl.Vector2(lx + 16, cy + 12), rl.Vector2(lx + 16, cy - 12), active if pull < 0 else idle)
    rl.draw_triangle(rl.Vector2(rx - 16, cy - 12), rl.Vector2(rx - 16, cy + 12), rl.Vector2(rx, cy), active if pull > 0 else idle)

    bar = rl.Rectangle(x + 24, y + h - 16, w - 48, 6)
    rl.draw_rectangle_rounded(bar, 1.0, 6, self._color((255, 255, 255), 40))
    rl.draw_rectangle(int(cx - 1), int(bar.y - 2), 2, int(bar.height + 4), self._color((255, 255, 255), 120))
    fill = bar.width / 2 * float(np.sqrt(np.clip(abs(pull) / FULL_BAR, 0.0, 1.0)))
    if fill > 1:
      fill_x = cx if pull > 0 else cx - fill
      rl.draw_rectangle_rounded(rl.Rectangle(fill_x, bar.y, fill, bar.height), 1.0, 6,
                                self._color(BLENDFUL_COLOR, np.clip(0.3 + 0.7 * trust, 0.0, 1.0) * 255))
