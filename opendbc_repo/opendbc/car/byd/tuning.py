#!/usr/bin/env python3

class Tuning:
  #仅开启非线性模式，但又没有选NNFF时候才有效
  LAT_SIGLIN_TABLE = [4.867, 1.09, 0.243]

  #方向盘手动偏差
  STEERING_ANGLE_OFFSET = 0

  # modified stock long control 原车long控制的速度平滑百分比设定, 例如下面40米以内，则加速率是原来的70%，减速率是原来的100%
  K_ACCEL_BP       = [40,  50,  60,  70,  80]  # meters BP是离前车距离

  K_ACCEL_POS_4BAR = [0.8, 0.7, 0.7, 0.7, 0.7] # acceleration 加速的百分比
  K_ACCEL_NEG_4BAR = [1.0, 0.8, 0.7, 0.7, 0.7] # deceleration 减速的百分比

  K_ACCEL_POS_3BAR = [0.8, 0.7, 0.7, 0.7, 0.7] # acceleration 加速的百分比
  K_ACCEL_NEG_3BAR = [1.0, 0.9, 0.8, 0.7, 0.7] # deceleration 减速的百分比

  K_ACCEL_POS_2BAR = [0.8, 0.8, 0.7, 0.7, 0.7] # acceleration 加速的百分比
  K_ACCEL_NEG_2BAR = [1.0, 1.0, 0.9, 0.8, 0.7] # deceleration 减速的百分比

  K_ACCEL_POS_1BAR = [1.0, 1.0, 1.0, 0.9, 0.8] # acceleration 加速的百分比
  K_ACCEL_NEG_1BAR = [1.1, 1.0, 1.0, 1.0, 0.9] # deceleration 减速的百分比

  # 人为扭动方向盘的阈值，大于这个值才认为方向盘被故意扭动了，变道辅助涉及它
  STEER_PRESSED_THRESHOLD = 56

  # 解决某些D9或者唐车型，离手时间过久，EPS会退出问题。解决办法是特定周期退出控制再马上接管
  HANDSOFF_ANGLE =  [4, 11, 18] #方向盘旋转的角度，不分左右，这里都是正值
  HANDSOFF_PERIOD = [5, 10, 15] #方向盘放开的周期，单位s

  # 禁用EPS故障检查, 某些车有EPS固件比较奇怪报错的话，则可以设为True
  DISABLE_EPS_WARNING = False
  DISABLE_EPS_TEMPORARY_FAULT = False
  DISABLE_EPS_PERMANENT_FAULT = False

  EPS_ANGLE_EXCEED_WARNING_CNT = 3
  EPS_ANGLE_SPEED_WARNING_CNT = 3
  EPS_STATE_WARNING_CNT = 20

  # =========================================================================
  # 社区移植增强开关（opendbc/car/byd/enhance.py），默认全部关闭
  # 这些实现来自社区 mypilot 移植包的 byd源码/ 与 byd2/ 两套代码，
  # 参数为汉/宋/唐实车调校，本分支未做实车验证，请逐项开启验证。
  # =========================================================================

  # 横向：归一化力矩平滑管线（滑动均值+速度死区+直路锁定+低通+迟滞）
  # 仅在力矩模式（TORQUE_LAT_CAR）生效；角度模式不走这条路径。
  ENABLE_LAT_SMOOTHING = False

  # 横向：曲率前馈。社区原始写法把 curvature*v^2（横向加速度）直接叠加到
  # 归一化力矩上，量纲不一致，这里额外做了幅值钳制，开启前务必实测。
  ENABLE_CURVATURE_FF = False
  LAT_CURVATURE_FF_GAIN = 0.8
  LAT_CURVATURE_FF_LIMIT = 0.15   # 归一化力矩上的最大叠加量

  # 纵向：0 帧起步 + PI 跟车 + TTC 预测制动 + 加速度平滑
  # 仅在 openpilot 纵向（未启用 BydModifiedStockLong）且 CC.longActive 时生效。
  ENABLE_LONG_ENHANCE = False

  # 横向：驾驶员踩刹车时短暂抑制 LKAS，规避偶发 LKS 报错
  ENABLE_LKAS_BRAKE_INHIBIT = False

