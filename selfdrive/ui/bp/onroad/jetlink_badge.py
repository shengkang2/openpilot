"""
Jetlink 状态角标（onroad 右上角）—— 本机补丁 2026-10-31。

状态映射与纹理本来就在 bluepilot/ui/jetlink_ui.py 的 JetlinkIcons 里，
但整个仓库只有设置页的 Jetlink 面板引用它；onroad 界面从来没画过图标。
于是链在路上真的跑着大模型（modelDataV2SP.acceleratorState=running），
驾驶界面上却没有任何痕迹，用户只能怀疑「是不是根本没生效」。

这里按 jetlink_ui 的语义补一个角标：
  不画   = DISCONNECTED（口上没设备 / 设置关着）
  实心绿 = READY / ACTIVE（大模型就绪或在开）
  暗绿   = WAITING（就绪，只差一个没人接管的窗口）
  橙色   = FAILED / UNCOMPILED（跑不起来）
  呼吸   = LOADING（正在编译 / 加载）
"""
import pyray as rl

from openpilot.bluepilot.ui.jetlink_ui import JetlinkIcons, tint
from openpilot.selfdrive.ui.ui_state import JetlinkState, ui_state

ICON_SIZE = 64
MARGIN = 26


class JetlinkBadge:
  def __init__(self):
    self._icons = JetlinkIcons(ICON_SIZE, ICON_SIZE)

  def render(self, rect: rl.Rectangle) -> None:
    tex, opacity = self._icons.for_state(ui_state.jetlink_state)
    if tex is None or opacity <= 0.01:
      return

    x = int(rect.x + rect.width - ICON_SIZE - MARGIN)
    y = int(rect.y + MARGIN)
    rl.draw_texture(tex, x, y, tint(opacity))

    # ACTIVE 时在图标下方补一条短横线：绿色图标在强光/复杂背景里容易和别的
    # 绿色元素混在一起，加一条实心小条能一眼确认「大模型在开」。
    if ui_state.jetlink_state == JetlinkState.ACTIVE:
      bar_w = ICON_SIZE - 16
      rl.draw_rectangle_rounded(
        rl.Rectangle(x + 8, y + ICON_SIZE + 4, bar_w, 5), 1.0, 6, rl.Color(0, 200, 120, 235)
      )
