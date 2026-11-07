/**
 * Drive Stats Card Component
 * Shows aggregate drive statistics similar to Qt widget
 */

import { useEffect, useState } from 'react'
import './DriveStatsCard.css'

interface Stats {
  routes: number
  distance: number  // in meters
  distanceMiles: number  // in miles (from API)
  duration: number  // in seconds
  durationMinutes: number  // in minutes (from API)
  averageSpeed: number  // in m/s
}

interface DriveStatsResponse {
  success: boolean
  all: Stats
  week: Stats
  source?: string
  error?: string
  cloud_error?: string
}

export function DriveStatsCard() {
  const [data, setData] = useState<DriveStatsResponse | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchDriveStats()
  }, [])

  const fetchDriveStats = async () => {
    setLoading(true)
    try {
      const response = await fetch('/api/drive-stats')
      if (response.ok) {
        const responseData = await response.json()
        if (responseData.success) {
          setData(responseData)
        }
      }
    } catch (error) {
      console.error('Error fetching drive stats:', error)
    } finally {
      setLoading(false)
    }
  }

  if (loading) {
    return (
      <div className="drive-stats-card">
        <div className="stats-header">
          <h3>行车统计</h3>
        </div>
        <div className="drive-stats-loading">正在加载统计…</div>
      </div>
    )
  }

  if (!data) {
    return (
      <div className="drive-stats-card">
        <div className="stats-header">
          <h3>行车统计</h3>
        </div>
        <div className="drive-stats-empty">暂无行车数据</div>
      </div>
    )
  }

  const allHours = Math.round(data.all.duration / 3600)
  // distance is meters from backend; show kilometres for CN users
  const allKm = Math.round(data.all.distance / 1000)
  const weekHours = Math.round(data.week.duration / 3600)
  const weekKm = Math.round(data.week.distance / 1000)

  return (
    <div className="drive-stats-card">
      <div className="stats-header">
        <h3>行车统计</h3>
        {data.source === 'param_cache' && <span className="stats-badge cached">缓存</span>}
        {data.source === 'no_cache' && <span className="stats-badge info">无数据</span>}
        {data.cloud_error && <span className="stats-badge warning">云端错误</span>}
      </div>

      <div className="stats-grid">
        <div className="stat-item all-time">
          <span className="stat-label">总行程次数</span>
          <span className="stat-value">{data.all.routes}</span>
        </div>
        <div className="stat-item all-time">
          <span className="stat-label">总里程 (公里)</span>
          <span className="stat-value">{allKm}</span>
        </div>
        <div className="stat-item all-time">
          <span className="stat-label">总时长 (小时)</span>
          <span className="stat-value">{allHours}</span>
        </div>
        <div className="stat-item">
          <span className="stat-label">本周行程</span>
          <span className="stat-value">{data.week.routes}</span>
        </div>
        <div className="stat-item">
          <span className="stat-label">本周里程 (公里)</span>
          <span className="stat-value">{weekKm}</span>
        </div>
        <div className="stat-item">
          <span className="stat-label">本周时长 (小时)</span>
          <span className="stat-value">{weekHours}</span>
        </div>
      </div>
    </div>
  )
}
