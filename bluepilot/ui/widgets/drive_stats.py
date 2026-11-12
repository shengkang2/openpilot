"""
BluePilot Drive Stats Widget
Displays all-time and past-week driving statistics (routes, distance, hours)
on the offroad home screen. Ported from the Qt DriveStats widget.
"""

import json
import requests
import threading
import time
import pyray as rl

from openpilot.common.api import api_get
from openpilot.common.constants import CV
from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive.ui.lib.api_helpers import get_token
from openpilot.selfdrive.ui.ui_state import ui_state, device
from openpilot.system.athena.registration import UNREGISTERED_DONGLE_ID
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget
from bluepilot.ui.lib.colors import BPColors


# Card styling colors (matching Qt gradient: #2c2c2c -> #1a1a1a)
CARD_BG = rl.Color(38, 38, 38, 255)
CARD_BORDER = rl.Color(255, 255, 255, 26)
STATS_CONTAINER_BG = rl.Color(255, 255, 255, 13)
STATS_CONTAINER_BORDER = rl.Color(255, 255, 255, 26)
UNIT_COLOR = rl.Color(176, 176, 176, 255)
NUMBER_COLOR = BPColors.ACCENT  # #18b4ff - matching Qt


class DriveStatsWidget(Widget):
  PARAM_KEY = "ApiCache_DriveStats"
  LOCAL_PARAM_KEY = "LocalDriveStats"  # 本机补丁（2026-10-30）：本地兜底数据源
  REQUIRED_KEYS = ("routes", "distance", "minutes")
  UPDATE_INTERVAL = 30  # seconds

  def __init__(self):
    super().__init__()
    self._params = Params()
    self._session = requests.Session()
    self._stats = self._get_stats()

    self._running = True
    self._update_thread = threading.Thread(target=self._update_loop, daemon=True)
    self._update_thread.start()

  def __del__(self):
    self._running = False
    try:
      if self._update_thread and self._update_thread.is_alive():
        self._update_thread.join(timeout=1.0)
    except Exception:
      pass

  @staticmethod
  def _as_dict(value):
    """本机补丁（2026-10-30）：把 Params 读到的值统一成 dict。

    ApiCache_DriveStats 是 JSON 类型（get 返回 dict），但 LocalDriveStats 在
    common/params_keys.h:255 注册为 STRING（get 返回 JSON 原文 str）。
    一律兼容 dict / JSON 字符串 / bytes，畸形值退化为空 dict。
    """
    if isinstance(value, dict):
      return value
    if isinstance(value, (str, bytes, bytearray)) and value:
      try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
      except Exception:
        return {}
    return {}

  @classmethod
  def _stats_ok(cls, data):
    """本机补丁：统计块是否完整（必须有次数/里程/时长三项）。

    旧格式或云端半截数据（只有 routes）判为无效，否则里程永远显示 0。
    """
    d = cls._as_dict(data)
    return bool(d) and all(d.get(k) is not None for k in cls.REQUIRED_KEYS)

  def _load_local_stats(self):
    """本机补丁：读本地统计（由设置页 trips.py 的后台扫描写入）。"""
    try:
      local = self._as_dict(self._params.get(self.LOCAL_PARAM_KEY))
      if self._stats_ok(local.get("all")):
        return local
    except Exception:
      cloudlog.exception("Failed to read LocalDriveStats")
    return {}

  def _get_stats(self):
    # 云端优先
    try:
      cloud = self._as_dict(self._params.get(self.PARAM_KEY))
      if self._stats_ok(cloud.get("all")):
        self._stats_source = "cloud"
        return cloud
    except Exception:
      cloudlog.exception("Failed to decode drive stats")

    # 云端不可用（本机 pilotauth 403，缓存恒空）-> 本地兜底
    local = self._load_local_stats()
    if local:
      self._stats_source = "local"
      return local

    self._stats_source = "none"
    return {}

  def _fetch_drive_stats(self):
    try:
      dongle_id = self._params.get("DongleId")
      if not dongle_id or dongle_id == UNREGISTERED_DONGLE_ID:
        return
      identity_token = get_token(dongle_id)
      response = api_get(f"v1.1/devices/{dongle_id}/stats", access_token=identity_token, session=self._session)
      if response.status_code == 200:
        data = response.json()
        self._stats = data
        self._stats_source = "cloud"
        self._params.put(self.PARAM_KEY, data)
    except Exception as e:
      cloudlog.error(f"Failed to fetch drive stats: {e}")

  def _update_loop(self):
    while self._running:
      if not ui_state.started and device._awake:
        self._fetch_drive_stats()
      # 本机补丁（2026-10-30）：当前用的是本地兜底数据时，每轮重读一次，
      # 让主页面跟上设置页的后台刷新（读 7.5KB 参数约 0.1ms，可忽略）。
      # 云端一旦可用会自动切回云端，不会被本地数据覆盖。
      if getattr(self, "_stats_source", "none") != "cloud":
        local = self._load_local_stats()
        if local:
          self._stats = local
          self._stats_source = "local"
      time.sleep(self.UPDATE_INTERVAL)

  def _render(self, rect: rl.Rectangle):
    is_metric = self._params.get_bool("IsMetric")

    all_time = self._as_dict(self._stats).get("all", {})
    week = self._as_dict(self._stats).get("week", {})
    all_time = all_time if isinstance(all_time, dict) else {}
    week = week if isinstance(week, dict) else {}

    # Calculate section heights
    spacing = 10
    section_height = (rect.height - spacing) / 2

    # Draw card background
    rl.draw_rectangle_rounded(rect, 0.03, 10, CARD_BG)
    rl.draw_rectangle_rounded_lines(rect, 0.03, 10, CARD_BORDER)

    # Render both stat sections
    top_rect = rl.Rectangle(rect.x, rect.y, rect.width, section_height)
    self._render_stat_section(top_rect, tr("ALL TIME"), all_time, is_metric)

    bottom_rect = rl.Rectangle(rect.x, rect.y + section_height + spacing, rect.width, section_height)
    self._render_stat_section(bottom_rect, tr("PAST WEEK"), week, is_metric)

  def _render_stat_section(self, rect, title, data, is_metric):
    # Calculate scale based on available height (base height: 275px per section)
    scale = min(1.0, max(0.35, rect.height / 275.0))

    padding_x = int(20 * scale)
    padding_top = int(15 * scale)

    title_size = int(max(34, min(50, 50 * scale)))
    number_size = int(max(42, min(66, 66 * scale)))
    unit_size = int(max(28, min(44, 44 * scale)))

    # Title
    title_font = gui_app.font(FontWeight.BOLD)
    title_pos = rl.Vector2(rect.x + padding_x, rect.y + padding_top)
    rl.draw_text_ex(title_font, title, title_pos, title_size, 0, rl.WHITE)

    # Stats container
    container_margin = int(10 * scale)
    container_top = rect.y + padding_top + title_size + int(8 * scale)
    container_height = rect.y + rect.height - container_top - container_margin
    container_rect = rl.Rectangle(
      rect.x + container_margin, container_top,
      rect.width - 2 * container_margin, container_height
    )
    rl.draw_rectangle_rounded(container_rect, 0.08, 10, STATS_CONTAINER_BG)
    rl.draw_rectangle_rounded_lines(container_rect, 0.08, 10, STATS_CONTAINER_BORDER)

    # Values
    routes = int(data.get("routes", 0))
    distance = data.get("distance", 0)
    distance_str = str(int(distance * CV.MPH_TO_KPH)) if is_metric else str(int(distance))
    # BP fix (2026-11-12): int(minutes/60) 把 163 和 144 分钟都截断成 2，
    # 表现为"小时数永远是 2、不随行程增长"。改为保留一位小数，让增长可见。
    _minutes = float(data.get("minutes", 0) or 0)
    _hours = _minutes / 60.0
    hours = f"{_hours:.1f}" if _hours < 100.0 else str(int(round(_hours)))
    dist_unit = tr("KM") if is_metric else tr("Miles")

    number_font = gui_app.font(FontWeight.BOLD)
    unit_font = gui_app.font(FontWeight.DISPLAY_REGULAR)

    col_width = container_rect.width / 3

    def draw_column(col_idx, value, unit):
      col_x = container_rect.x + col_width * col_idx
      center_x = col_x + col_width / 2

      # Value (centered)
      val_text = str(value)
      val_size = measure_text_cached(number_font, val_text, number_size)
      val_pos = rl.Vector2(center_x - val_size.x / 2, container_rect.y + container_rect.height * 0.2)
      rl.draw_text_ex(number_font, val_text, val_pos, number_size, 0, NUMBER_COLOR)

      # Unit (centered below value)
      unit_text_size = measure_text_cached(unit_font, unit, unit_size)
      unit_pos = rl.Vector2(center_x - unit_text_size.x / 2, container_rect.y + container_rect.height * 0.6)
      rl.draw_text_ex(unit_font, unit, unit_pos, unit_size, 0, UNIT_COLOR)

    draw_column(0, routes, tr("Drives"))
    draw_column(1, distance_str, dist_unit)
    draw_column(2, hours, tr("Hours"))
