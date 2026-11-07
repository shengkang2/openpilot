import { useEffect, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { Header } from '@/components/layout/Header'
import { Icon } from '@/components/common'
import { useSystemStore } from '@/stores/useSystemStore'
import { useRoutesStore } from '@/stores/useRoutesStore'
import { useParamsStore } from '@/stores/useParamsStore'
import type { DeviceStatus } from '@/types'
import './Home.css'

interface HomeProps {
  deviceStatus?: DeviceStatus
}

interface DriveStats {
  routes: number
  distance: number
  distanceMiles: number
  duration: number
  durationMinutes: number
  averageSpeed: number
}

interface DriveStatsResponse {
  success: boolean
  all: DriveStats
  week: DriveStats
  source?: string
  error?: string
  cloud_error?: string
}

interface LastErrorEntry {
  timestamp: string
  level: 'ERROR' | 'WARNING' | 'CRITICAL'
  message: string
  details?: string | null
  file_path?: string
  file_size?: number
  file_modified?: number
}

interface LastErrorResponse {
  success: boolean
  has_error: boolean
  message?: string
  error?: LastErrorEntry
}

export const Home = ({ deviceStatus = 'checking' }: HomeProps) => {
  const navigate = useNavigate()
  const { status, deviceInfo, metrics, diskSpace, fetchStatus, fetchDeviceInfo } = useSystemStore()
  const { fetchRoutes, routes } = useRoutesStore()
  const { params, fetchParams } = useParamsStore()
  const [driveStats, setDriveStats] = useState<DriveStatsResponse | null>(null)
  const [driveStatsLoading, setDriveStatsLoading] = useState(true)
  const [lastError, setLastError] = useState<LastErrorEntry | null>(null)

  const fetchDriveStats = useCallback(async () => {
    setDriveStatsLoading(true)
    try {
      const response = await fetch('/api/drive-stats')
      if (response.ok) {
        const responseData = await response.json()
        if (responseData.success) {
          setDriveStats(responseData)
        }
      }
    } catch (error) {
      console.error('Error fetching drive stats:', error)
    } finally {
      setDriveStatsLoading(false)
    }
  }, [])

  useEffect(() => {
    console.log('Home mounted, fetching data...')
    fetchStatus()
    fetchDeviceInfo()
    fetchRoutes(1)
    fetchParams()
    fetchDriveStats()
    fetchLastError()

    // Set up polling for drive stats (refresh every 60 seconds)
    const driveStatsInterval = setInterval(() => {
      fetchDriveStats()
    }, 60000)

    // Cleanup interval on unmount
    return () => {
      clearInterval(driveStatsInterval)
    }
  }, [fetchStatus, fetchDeviceInfo, fetchRoutes, fetchParams, fetchDriveStats])

  // Refresh drive stats when routes change (e.g., new route added, route deleted)
  useEffect(() => {
    // Only refresh if routes have been loaded (not on initial mount)
    if (routes.length > 0) {
      fetchDriveStats()
    }
  }, [routes.length, fetchDriveStats])

  const fetchLastError = async () => {
    try {
      const response = await fetch('/api/last-error')
      if (response.ok) {
        const data: LastErrorResponse = await response.json()
        if (data.success && data.has_error && data.error) {
          setLastError(data.error ?? null)
        } else {
          setLastError(null)
        }
      }
    } catch (error) {
      console.error('Error fetching last error:', error)
    }
  }

  const paramCount = Object.keys(params).length

  // Format uptime from seconds to "Xh Ym" format
  const getUptimeDisplay = () => {
    if (metrics?.uptime_seconds && metrics.uptime_seconds > 0) {
      const hours = Math.floor(metrics.uptime_seconds / 3600)
      const minutes = Math.floor((metrics.uptime_seconds % 3600) / 60)
      return `${hours}h ${minutes}m`
    }
    return 'N/A'
  }

  // Get color class for CPU temperature
  const getTempColorClass = (temp?: number): string => {
    if (!temp) return 'normal'
    if (temp >= 85) return 'critical'
    if (temp >= 70) return 'warning'
    return 'normal'
  }

  // Get color class for memory usage
  const getMemoryColorClass = (percent?: number): string => {
    if (!percent) return 'normal'
    if (percent >= 85) return 'critical'
    if (percent >= 70) return 'warning'
    return 'normal'
  }

  // Get color class for storage (based on percentage used - inverted logic)
  const getStorageColorClass = (): string => {
    if (!diskSpace?.total || !diskSpace?.free) return 'normal'
    const percentUsed = ((diskSpace.total - diskSpace.free) / diskSpace.total) * 100
    if (percentUsed >= 90) return 'critical'  // < 10% free
    if (percentUsed >= 80) return 'warning'   // < 20% free
    return 'normal'
  }

  // Format storage for display
  const getStorageDisplay = (): string => {
    if (!diskSpace?.free) return 'N/A'
    const gb = diskSpace.free / (1024 ** 3)
    if (gb >= 1) {
      return `${gb.toFixed(1)}GB`
    }
    return `${(diskSpace.free / (1024 ** 2)).toFixed(0)}MB`
  }

  return (
    <>
      <Header
        deviceStatus={deviceStatus}
        subtitle="设置、行程与诊断"
      />
      <div className="dashboard-page">
        <div className="dashboard-insights-grid">
          <section className="dashboard-status-panel">
            <div className="panel-heading">
              <h2>系统状态</h2>
            </div>
            <div className="status-pills-container">
              {/* System Metrics */}
              <div className="status-pills-row">
                <div className="status-pill" title="系统运行时长">
                  <Icon name="schedule" className="pill-icon" />
                  <span className="pill-label">运行时长</span>
                  <span className="pill-value">{getUptimeDisplay()}</span>
                </div>

                <div className={`status-pill ${getTempColorClass(metrics?.temperature)}`} title="CPU 温度">
                  <Icon name="thermostat" className="pill-icon" />
                  <span className="pill-label">CPU</span>
                  <span className="pill-value">
                    {metrics?.temperature ? `${metrics.temperature.toFixed(1)}°C` : 'N/A'}
                  </span>
                </div>

                <div className={`status-pill ${getMemoryColorClass(metrics?.memory_percent)}`} title="内存占用">
                  <Icon name="memory" className="pill-icon" />
                  <span className="pill-label">内存</span>
                  <span className="pill-value">
                    {metrics?.memory_percent ? `${metrics.memory_percent.toFixed(0)}%` : 'N/A'}
                  </span>
                </div>

                <div className={`status-pill ${getStorageColorClass()}`} title="剩余存储">
                  <Icon name="storage" className="pill-icon" />
                  <span className="pill-label">存储</span>
                  <span className="pill-value">{getStorageDisplay()}</span>
                </div>
              </div>

              {/* Device Info */}
              <div className="status-pills-row">
                <div className="status-pill">
                  <span className="pill-label">Dongle ID</span>
                  <span className="pill-value">{deviceInfo?.dongle_id || 'N/A'}</span>
                </div>
                <div className="status-pill">
                  <span className="pill-label">序列号</span>
                  <span className="pill-value">{deviceInfo?.serial || 'N/A'}</span>
                </div>
              </div>

              {/* Version Info */}
              <div className="status-pills-row">
                <div className="status-pill">
                  <span className="pill-label">BP 版本</span>
                  <span className="pill-value">{deviceInfo?.bp_version ? `v${deviceInfo.bp_version}` : 'N/A'}</span>
                </div>
                <div className="status-pill">
                  <span className="pill-label">SP 版本</span>
                  <span className="pill-value">{deviceInfo?.sp_version || 'N/A'}</span>
                </div>
                <div className="status-pill">
                  <span className="pill-label">OP 版本</span>
                  <span className="pill-value">{deviceInfo?.op_version || 'N/A'}</span>
                </div>
              </div>
            </div>
          </section>

          <section className="dashboard-drive-stats-panel">
            <div className="panel-heading">
              <h2>行车统计</h2>
            </div>
            {driveStatsLoading ? (
              <div className="drive-stats-loading">加载中…</div>
            ) : driveStats ? (
              <div className="drive-stats-content">
                <div className="drive-stats-group">
                  <h3 className="stats-period-title">全部时间</h3>
                  <div className="stats-cards-grid">
                    <div className="stat-card all-time">
                      <div className="stat-value">{driveStats.all.routes.toLocaleString()}</div>
                      <div className="stat-label">总行程</div>
                    </div>
                    <div className="stat-card all-time">
                      <div className="stat-value">{Math.round(driveStats.all.distance / 1000).toLocaleString()}</div>
                      <div className="stat-label">行驶里程</div>
                    </div>
                    <div className="stat-card all-time">
                      <div className="stat-value">{Math.round(driveStats.all.duration / 3600).toLocaleString()}</div>
                      <div className="stat-label">行驶时长</div>
                    </div>
                  </div>
                </div>
                <div className="drive-stats-group">
                  <h3 className="stats-period-title">本周</h3>
                  <div className="stats-cards-grid">
                    <div className="stat-card">
                      <div className="stat-value">{driveStats.week.routes}</div>
                      <div className="stat-label">行程</div>
                    </div>
                    <div className="stat-card">
                      <div className="stat-value">{Math.round(driveStats.week.distance / 1000)}</div>
                      <div className="stat-label">公里</div>
                    </div>
                    <div className="stat-card">
                      <div className="stat-value">{Math.round(driveStats.week.duration / 3600)}</div>
                      <div className="stat-label">小时</div>
                    </div>
                  </div>
                </div>
              </div>
            ) : (
              <div className="drive-stats-empty">暂无行车数据</div>
            )}
          </section>

          <section className="dashboard-quick-panel">
            <div className="panel-heading">
              <h2>快捷入口</h2>
            </div>
            <div className="quick-links-grid">
              <button
                className={`quick-link-card routes ${deviceStatus === 'onroad' ? 'disabled' : ''}`}
                onClick={() => deviceStatus !== 'onroad' && navigate('/routes')}
                disabled={deviceStatus === 'onroad'}
                title={deviceStatus === 'onroad' ? 'Routes unavailable while driving' : undefined}
              >
                <div className="quick-link-icon">
                  <Icon name="place" />
                </div>
                <div className="quick-link-copy">
                  <span className="label">行程</span>
                  <span className="subtext">{deviceStatus === 'onroad' ? '行驶中不可用' : '查看行车录像'}</span>
                </div>
                <span className="link-badge">{status?.routes_count || 0}</span>
              </button>
              <button className="quick-link-card parameters" onClick={() => navigate('/parameters')}>
                <div className="quick-link-icon">
                  <Icon name="tune" />
                </div>
                <div className="quick-link-copy">
                  <span className="label">参数</span>
                  <span className="subtext">管理系统参数</span>
                </div>
                <span className="link-badge">{paramCount}</span>
              </button>
              <button className="quick-link-card logs" onClick={() => navigate('/logs')}>
                <div className="quick-link-icon">
                  <Icon name="description" />
                </div>
                <div className="quick-link-copy">
                  <span className="label">系统日志</span>
                  <span className="subtext">查看实时系统日志</span>
                </div>
              </button>
            </div>
          </section>

          {lastError && (
            <section className="dashboard-error-panel">
              <div className="panel-heading">
                <h2>
                  <Icon name="error" className="error-icon" />
                  最近崩溃
                </h2>
              </div>
              <div className="error-card">
                <div className="error-header">
                  <span className={`error-level ${lastError.level.toLowerCase()}`}>
                    {lastError.level}
                  </span>
                  <span className="error-timestamp">
                    {new Date(lastError.timestamp).toLocaleString()}
                  </span>
                </div>
                <div className="error-message">{lastError.message}</div>
                {lastError.details && (
                  <div className="error-details">{lastError.details}</div>
                )}
                <button
                  type="button"
                  className="view-logs-button"
                  onClick={() => navigate('/logs')}
                >
                  查看完整日志
                </button>
              </div>
            </section>
          )}
        </div>
      </div>
    </>
  )
}
