"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
import io
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
from openpilot.system.ui.lib.application import gui_app, FontWeight, FONT_SCALE
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget


class TripsLayout(Widget):
  PARAM_KEY = "ApiCache_DriveStats"
  PARAM_LOCAL = "LocalDriveStats"  # BP_LOCAL_STATS
  UPDATE_INTERVAL = 30  # seconds

  # 本机补丁（2026-10-30）：本地统计缓存配置
  # 每个 realdata 目录算出的里程/时长按目录 mtime 落盘缓存，只重算变化的目录，
  # 避免每次刷新都全量读 111 个 qlog.zst（实测 36.5 秒）。
  LOCAL_CACHE_PATH = "/data/bp_local_drive_stats.json"
  LOCAL_CACHE_VER = 2
  LOCAL_REFRESH_S = 3600  # 本地数据超过 1 小时就在后台增量刷新一次
  REQUIRED_KEYS = ("routes", "distance", "minutes")

  def __init__(self):
    super().__init__()
    self._params = Params()
    self._session = requests.Session()
    self._stats = self._get_stats()
    self._local_scanning = False   # 本机补丁：本地扫描是否在后台进行中
    self._local_scan_result = {}   # 本机补丁：后台扫描结果缓存

    self._icon_distance = gui_app.texture("icons/road.png", 100, 100, keep_aspect_ratio=True)
    self._icon_drives = gui_app.texture("icons_mici/wheel.png", 80, 80, keep_aspect_ratio=True)
    self._icon_hours = gui_app.texture("../../sunnypilot/selfdrive/assets/icons/clock.png", 80, 80, keep_aspect_ratio=True)

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

    LocalDriveStats 在 common/params_keys.h:255 注册为 STRING，params.get() 返回
    JSON 原文（str）而非 dict；历史上游代码却按 dict 调用 .get()，导致
    进入设置页「行程」面板时整个 UI 抛 AttributeError 崩溃重启。
    这里兼容 dict / JSON 字符串 / bytes，任何畸形值都退化为空 dict。
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
  def _stats_valid(cls, data):
    """本机补丁（2026-10-30）：统计块是否完整可用。

    早期版本往 LocalDriveStats 里只写了 {"all": {"routes": N}}，没有 distance / minutes。
    那种陈旧结构必须判为无效，否则里程永远显示 0。
    """
    d = cls._as_dict(data)
    return bool(d) and all(d.get(k) is not None for k in cls.REQUIRED_KEYS)

  @classmethod
  def _local_ok(cls, result):
    """本机补丁：本地统计整体结果是否可用（校验其中的 all 块）。"""
    return cls._stats_valid(cls._as_dict(result).get("all"))

  @classmethod
  def _local_fresh(cls, result):
    """本机补丁：本地统计整体结果是否新鲜（_ts 在顶层）。"""
    return cls._stats_fresh(result)

  @classmethod
  def _stats_fresh(cls, data):
    """本机补丁：数据是否还在刷新窗口内（_ts 为秒级时间戳）。"""
    d = cls._as_dict(data)
    ts = d.get("_ts")
    if not isinstance(ts, (int, float)) or ts <= 0:
      return False
    return (time.time() - ts) < cls.LOCAL_REFRESH_S

  def _load_seg_cache(self):
    """本机补丁：读取分段结果缓存 {目录名: {m: mtime, d: 里程米, s: 秒}}。"""
    import os
    try:
      if os.path.exists(self.LOCAL_CACHE_PATH):
        with io.open(self.LOCAL_CACHE_PATH, encoding="utf-8") as f:
          c = json.load(f)
        if isinstance(c, dict) and c.get("v") == self.LOCAL_CACHE_VER and isinstance(c.get("dirs"), dict):
          return c["dirs"]
    except Exception:
      pass
    return {}

  def _save_seg_cache(self, dirs):
    """本机补丁：原子写入分段结果缓存。"""
    import os
    try:
      tmp = self.LOCAL_CACHE_PATH + ".tmp"
      with io.open(tmp, "w", encoding="utf-8") as f:
        json.dump({"v": self.LOCAL_CACHE_VER, "ts": int(time.time()), "dirs": dirs}, f)
      os.replace(tmp, self.LOCAL_CACHE_PATH)
    except Exception:
      pass

  def _get_stats(self):
    stats = self._params.get(self.PARAM_KEY)
    if not stats:
      return {}
    ret = self._as_dict(stats)
    if not ret:
      cloudlog.error(f"Failed to decode drive stats: type={type(stats).__name__}")
    return ret

  def _local_stats(self):
    """从本地 realdata 目录统计行程数/时长/里程（云端不可用时兜底）。

    本机补丁（2026-10-30）：分段结果按目录 mtime 缓存，只重算变化的目录；
    时长改为累加真实 segment 时长（原先每个目录固定 +1 分钟，实际每段约 72 秒）。
    """
    import glob
    import os

    now = time.time()
    dist_m = 0.0
    routes = 0
    total_sec = 0.0
    week_dist_m = 0.0
    week_routes = 0
    week_sec = 0.0
    seen = set()

    try:
      from openpilot.tools.lib.logreader import LogReader
    except Exception:
      LogReader = None

    seg_cache = self._load_seg_cache()
    new_cache = {}

    for d in sorted(glob.glob("/data/media/0/realdata/*")):
      if not os.path.isdir(d):
        continue
      name = os.path.basename(d)
      if "--" not in name:
        continue
      route = name.rsplit("--", 1)[0]
      try:
        mtime = int(os.path.getmtime(d))
      except OSError:
        continue

      in_week = (now - mtime) < 7 * 86400
      seg_dist = 0.0
      seg_sec = 0.0

      hit = seg_cache.get(name)
      if isinstance(hit, dict) and hit.get("m") == mtime and isinstance(hit.get("d"), (int, float)):
        seg_dist = float(hit["d"])
        seg_sec = float(hit.get("s") or 0.0)
        new_cache[name] = hit
      else:
        q = os.path.join(d, "qlog.zst")
        scanned = False
        if LogReader is not None and os.path.exists(q):
          try:
            last_t = None
            first_t = None
            for m in LogReader(q):
              if m.which() != "carState":
                continue
              t = m.logMonoTime / 1e9
              if first_t is None:
                first_t = t
              if last_t is not None:
                dt = t - last_t
                if 0 < dt <= 0.6:
                  seg_dist += max(0.0, m.carState.vEgo) * dt
              last_t = t
            if first_t is not None and last_t is not None:
              seg_sec = max(0.0, last_t - first_t)
              scanned = True
          except Exception:
            scanned = False
        # 只有真正读到 carState 才写缓存。文件缺失（loggerd 正在写/已回收）
        # 或读取异常时不写，留待下次重算，避免把 0 里程永久固化。
        if scanned:
          new_cache[name] = {"m": mtime, "d": round(seg_dist, 2), "s": round(seg_sec, 1)}

      dist_m += seg_dist
      total_sec += seg_sec
      if route not in seen:
        seen.add(route)
        routes += 1
        if in_week:
          week_routes += 1
      if in_week:
        week_dist_m += seg_dist
        week_sec += seg_sec

    # 只写回当前仍存在的目录，已被回收的旧条目自动清理，缓存不会无限膨胀
    if new_cache and new_cache != seg_cache:
      self._save_seg_cache(new_cache)

    return {
      "all": {"routes": routes, "distance": dist_m / 1609.344, "minutes": int(total_sec / 60)},
      "week": {"routes": week_routes, "distance": week_dist_m / 1609.344, "minutes": int(week_sec / 60)},
      "_v": self.LOCAL_CACHE_VER,
      "_ts": int(time.time()),
    }

  def _get_local_stats_cached(self):
    """本机补丁（2026-10-30）：取本地统计，绝不在渲染线程做重活。

    顺序：内存结果 -> 参数缓存 -> 触发后台扫描。
    参数里若是旧格式（缺 distance/minutes）或已过期，先返回现有数据用于显示，
    同时触发后台重扫，界面不会出现突然全 0。
    """
    mem = getattr(self, "_local_scan_result", None)
    if self._local_ok(mem):
      # 本机补丁：命中内存就不再读参数。过期时触发后台增量刷新，
      # 本帧继续用旧值，界面不会归零。
      if not self._local_fresh(mem):
        self._trigger_local_scan()
      return mem

    try:
      param_local = self._as_dict(self._params.get(self.PARAM_LOCAL))
    except Exception:
      param_local = {}

    if self._local_ok(param_local):
      # 关键：读到的参数值必须放进内存缓存。这个方法每帧都会被 _render 调用，
      # 若不缓存就等于 60FPS 下每秒读 60 次 7.5KB 参数文件 + 解析 JSON。
      self._local_scan_result = param_local
      if not self._local_fresh(param_local):
        self._trigger_local_scan()
      return param_local

    # 参数里是旧格式（缺 distance/minutes）或为空 -> 必须重扫；
    # 先把现有值返回去显示，避免界面突然归零。
    self._trigger_local_scan()
    return param_local

  def _trigger_local_scan(self):
    """本机补丁（2026-10-30）：本地扫描放后台线程，绝不阻塞渲染线程。

    _local_stats() 要逐个读 realdata 下的 qlog.zst，实测 111 个目录耗时 36.65 秒。
    原先在 _render() 里同步调用，参数为空时会卡死 UI 几十秒，随后被看门狗杀掉重启。
    """
    if getattr(self, "_local_scanning", False):
      return
    self._local_scanning = True

    def _worker():
      try:
        result = self._local_stats()
        self._local_scan_result = result
        # 本机补丁：不再写 self._stats，避免本地结果覆盖云端数据，
        # 渲染时按「云端优先、本地兜底」取值。
        try:
          # PARAM_LOCAL 是 STRING 类型，显式写 JSON 文本
          self._params.put(self.PARAM_LOCAL, json.dumps(result))
        except Exception:
          pass
      except Exception:
        cloudlog.exception("local drive stats scan failed")
      finally:
        self._local_scanning = False

    threading.Thread(target=_worker, daemon=True).start()

  def _fetch_drive_stats(self):
    try:
      dongle_id = self._params.get("DongleId")
      if not dongle_id or dongle_id == UNREGISTERED_DONGLE_ID:
        return
      identity_token = get_token(dongle_id)
      response = api_get(f"v1.1/devices/{dongle_id}/stats", access_token=identity_token, session=self._session)
      if response.status_code == 200:
        data = self._as_dict(response.json())
        self._stats = data
        self._params.put(self.PARAM_KEY, data)
    except Exception as e:
      cloudlog.error(f"Failed to fetch drive stats: {e}")

  def _update_loop(self):
    while self._running:
      if not ui_state.started and device._awake:
        self._fetch_drive_stats()
        # 本机补丁（2026-10-30）：云端统计不可用（本机 pilotauth 403），
        # 本地统计需要定期增量刷新，里程才会随新记录增长。
        try:
          cached = self._as_dict(self._params.get(self.PARAM_LOCAL))
          if not self._local_ok(cached) or not self._local_fresh(cached):
            self._trigger_local_scan()
        except Exception:
          pass
      time.sleep(self.UPDATE_INTERVAL)

  def _render_stat_group(self, x, y, width, height, title, data, is_metric):
    data = self._as_dict(data)
    # Card Background
    rl.draw_rectangle_rounded(rl.Rectangle(x, y, width, height), 0.05, 10, rl.Color(30, 30, 30, 255))

    # Title
    title_font = gui_app.font(FontWeight.BOLD)
    rl.draw_text_ex(title_font, title, rl.Vector2(x + 60, y + 30), 50 * FONT_SCALE, 0, rl.Color(200, 200, 200, 255))

    # Internal content area
    # Center the content block (Icon + Value + Unit) vertically
    content_y = y + (height / 2) - (140 * FONT_SCALE)
    col_width = width / 3

    # Values
    number_font = gui_app.font(FontWeight.BOLD)
    unit_font = gui_app.font(FontWeight.NORMAL)
    number_base_size = 92
    unit_base_size = 55
    number_size = number_base_size * FONT_SCALE
    unit_size = unit_base_size * FONT_SCALE
    color_unit = rl.Color(160, 160, 160, 255)

    routes = int(data.get("routes", 0))
    distance = data.get("distance", 0)
    distance_str = str(int(distance * CV.MPH_TO_KPH)) if is_metric else str(int(distance))
    hours = int(data.get("minutes", 0) / 60)

    dist_unit = tr("KM") if is_metric else tr("Miles")

    def draw_col(col_idx, icon, value, unit):
      col_x = x + (col_width * col_idx)
      center_x = col_x + (col_width / 2)

      # Icon
      icon_x = center_x - (icon.width / 2)
      icon_y = content_y + 60
      rl.draw_texture_ex(icon, rl.Vector2(icon_x, icon_y), 0.0, 1.0, rl.WHITE)

      # Value
      val_size = measure_text_cached(number_font, value, number_base_size)
      rl.draw_text_ex(number_font, value, rl.Vector2(center_x - val_size.x / 1.65, content_y + 145 * FONT_SCALE), number_size, 0, rl.WHITE)

      # Unit
      unit_size_vec = measure_text_cached(unit_font, unit, unit_base_size)
      rl.draw_text_ex(unit_font, unit, rl.Vector2(center_x - unit_size_vec.x / 1.65, content_y + 255 * FONT_SCALE), unit_size, 0, color_unit)

    draw_col(0, self._icon_drives, str(routes), tr("Drives"))
    draw_col(1, self._icon_distance, distance_str, dist_unit)
    draw_col(2, self._icon_hours, str(hours), tr("Hours"))

    return y + height

  def _render(self, rect: rl.Rectangle):
    x = rect.x
    y = rect.y
    w = rect.width

    spacing = 30
    available_h = rect.height - 30
    card_height = available_h / 2

    is_metric = self._params.get_bool("IsMetric")

    cloud = self._as_dict(self._stats)
    all_time = self._as_dict(cloud.get("all"))
    week = self._as_dict(cloud.get("week"))

    if not self._stats_valid(all_time):
      # BP_LOCAL_STATS: 云端统计不可用时，用本地行车记录兜底。
      # 本机补丁（2026-10-30）：显式校验 routes/distance/minutes 三项齐全，
      # 早期只写 routes 的陈旧缓存会被判无效并触发重扫，里程才会真正出现。
      local = self._as_dict(self._get_local_stats_cached())
      all_time = self._as_dict(local.get("all"))
      week = self._as_dict(local.get("week"))

    y = self._render_stat_group(x, y, w, card_height, tr("ALL TIME"), all_time, is_metric)
    y += spacing
    y = self._render_stat_group(x, y, w, card_height, tr("PAST WEEK"), week, is_metric)
