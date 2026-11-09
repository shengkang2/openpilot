from types import SimpleNamespace

from opendbc.sunnypilot.car.ford.lateral_angle_ext import LateralAngleExt


def _cs(left_blinker=False, right_blinker=False):
  return SimpleNamespace(out=SimpleNamespace(leftBlinker=left_blinker, rightBlinker=right_blinker))


def _ext(curvature=0.002, trust=0.8, enabled=True, lane_change=False,
         lprob=0.9, rprob=0.9, lstd=0.1, rstd=0.1):
  ext = LateralAngleExt()
  ext.blendful_curvature = curvature
  ext.blendful_trust = trust
  ext.blendful_enabled = enabled
  ext.lane_change = lane_change
  ext.blendful_lprob = lprob
  ext.blendful_rprob = rprob
  ext.blendful_lstd = lstd
  ext.blendful_rstd = rstd
  return ext


def test_applies_nudge_when_enabled_and_trusted():
  # a 0.002 request is clamped to the guard-rail cap
  assert abs(_ext().blendful_delta(_cs()) - 0.0005) < 1e-9


def test_zero_when_toggle_off():
  assert _ext(enabled=False).blendful_delta(_cs()) == 0.0


def test_zero_when_trust_low():
  assert _ext(trust=0.05).blendful_delta(_cs()) == 0.0
  assert _ext(trust=0.0).blendful_delta(_cs()) == 0.0


def test_zero_while_model_changes_lanes():
  assert _ext(lane_change=True).blendful_delta(_cs()) == 0.0


def test_zero_while_signalling():
  assert _ext().blendful_delta(_cs(left_blinker=True)) == 0.0
  assert _ext().blendful_delta(_cs(right_blinker=True)) == 0.0


def test_zero_when_one_lane_line_missing():
  # ambiguous markings: model may have locked onto the wrong line -> no nudge
  assert _ext(lprob=0.0).blendful_delta(_cs()) == 0.0
  assert _ext(rprob=0.05).blendful_delta(_cs()) == 0.0


def test_zero_when_lane_geometry_is_sloppy():
  assert _ext(lstd=1.2).blendful_delta(_cs()) == 0.0


def test_nudge_is_capped():
  assert abs(_ext(curvature=-0.0017).blendful_delta(_cs())) <= 0.0005


def test_zero_when_opposing_planner_hard():
  # pushing right through a left-hand curve is exactly the 2026-11-09 failure
  assert _ext(curvature=-0.0017).blendful_delta(_cs(), requested_curvature=0.0025) == 0.0


def test_allows_small_opposing_correction():
  # a small counter-nudge within tolerance is legitimate centering, not a bad fit
  assert _ext(curvature=-0.0002).blendful_delta(_cs(), requested_curvature=0.0005) != 0.0


def test_allows_same_direction_assist():
  assert _ext(curvature=-0.0012).blendful_delta(_cs(), requested_curvature=-0.0030) != 0.0
