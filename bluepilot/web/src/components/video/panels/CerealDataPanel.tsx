import { useState, useEffect } from 'react'
import { Icon } from '@/components/common'
import { useToastStore } from '@/stores/useToastStore'
import type { RouteDetails } from '@/types'
import './Panels.css'

interface CerealDataPanelProps {
  route: RouteDetails | null
  currentSegment: number
  videoCurrentTime?: number
}

interface CerealMessage {
  timestamp: number
  data: any
}

interface CerealResponse {
  success: boolean
  messages: CerealMessage[]
  message_type: string
  total_count: number
  start_time: number
  end_time: number
  error?: string
}

export const CerealDataPanel = ({ route, currentSegment, videoCurrentTime = 0 }: CerealDataPanelProps) => {
  const { addToast } = useToastStore()
  const [isOpen, setIsOpen] = useState(false)
  const [messageType, setMessageType] = useState('carState')
  const [loading, setLoading] = useState(false)
  const [messages, setMessages] = useState<CerealMessage[]>([])
  const [currentMessageIndex, setCurrentMessageIndex] = useState(0)
  const [messageCount, setMessageCount] = useState(0)
  const [lastUpdate, setLastUpdate] = useState('')
  const [timeRange, setTimeRange] = useState({ start: 0, end: 0 })

  // Sync cereal data to video playback time (always enabled)
  useEffect(() => {
    if (messages.length === 0) return

    // Calculate time relative to current segment (each segment is 60 seconds)
    const segmentOffset = currentSegment * 60
    const segmentRelativeTime = videoCurrentTime - segmentOffset
    const segmentStartTime = timeRange.start
    const targetTimestamp = segmentStartTime + segmentRelativeTime

    // Find the message closest to current video time
    let closestIndex = 0
    let closestDistance = Infinity

    messages.forEach((msg, index) => {
      const distance = Math.abs(msg.timestamp - targetTimestamp)
      if (distance < closestDistance) {
        closestDistance = distance
        closestIndex = index
      }
    })

    setCurrentMessageIndex(closestIndex)
  }, [videoCurrentTime, messages, currentSegment, timeRange.start])

  const loadCerealData = async () => {
    if (!route) {
      console.warn('No route selected')
      return
    }

    if (!messageType) {
      addToast('Please select a message type', 'info')
      return
    }

    setLoading(true)
    setIsOpen(true)

    try {
      const url = `${window.location.origin}/api/cereal/${route.baseName}/${currentSegment}/qlog/${messageType}`

      console.log('Loading cereal data from:', url)

      const response = await fetch(url)
      const data: CerealResponse = await response.json()

      setLoading(false)

      if (data.success) {
        setMessages(data.messages)
        setMessageCount(data.total_count)
        setTimeRange({
          start: data.start_time,
          end: data.end_time
        })
        setCurrentMessageIndex(0)
        setLastUpdate(new Date().toLocaleTimeString())
      } else {
        addToast(`Error loading cereal data: ${data.error}`, 'error')
        setMessages([])
      }
    } catch (error) {
      console.error('Error loading cereal data:', error)
      setLoading(false)
      addToast(`Failed to load cereal data: ${error}`, 'error')
      setMessages([])
    }
  }

  const stopCereal = () => {
    setMessages([])
    setMessageCount(0)
    setCurrentMessageIndex(0)
  }

  const flattenObject = (obj: any, prefix = ''): Record<string, any> => {
    const flattened: Record<string, any> = {}

    // Handle non-object types
    if (obj === null || obj === undefined) {
      return { [prefix || 'value']: obj }
    }

    if (typeof obj !== 'object' || obj instanceof Date) {
      return { [prefix || 'value']: obj }
    }

    // Handle arrays
    if (Array.isArray(obj)) {
      return { [prefix || 'value']: obj }
    }

    // Handle plain objects
    for (const key in obj) {
      if (obj.hasOwnProperty(key)) {
        const value = obj[key]
        const newKey = prefix ? `${prefix}.${key}` : key

        if (
          value !== null &&
          typeof value === 'object' &&
          !Array.isArray(value) &&
          !(value instanceof Date)
        ) {
          // Recursively flatten nested objects
          Object.assign(flattened, flattenObject(value, newKey))
        } else {
          flattened[newKey] = value
        }
      }
    }

    return flattened
  }

  const formatCerealValue = (value: any): string => {
    if (value === null || value === undefined) {
      return 'null'
    }

    if (Array.isArray(value)) {
      if (value.length === 0) return '[]'
      if (value.length > 10) return `[Array(${value.length})]`
      return JSON.stringify(value)
    }

    if (typeof value === 'object') {
      return JSON.stringify(value)
    }

    if (typeof value === 'boolean') {
      return value ? 'true' : 'false'
    }

    if (typeof value === 'number') {
      return value.toFixed(6)
    }

    return String(value)
  }

  const currentMessage = messages[currentMessageIndex]
  const flatData = currentMessage ? flattenObject(currentMessage.data) : {}

  return (
    <div className="bottom-panel" id="cereal-panel">
      <div
        className="panel-header"
        id="cereal-panel-header"
        onClick={() => setIsOpen(!isOpen)}
        style={{ cursor: 'pointer' }}
      >
        <div className="panel-title">
          <Icon name="data_usage" className="panel-icon" size={20} />
          <div className="panel-title-text">
            <span className="panel-title-label">Cereal 数据查看器</span>
            <span className="panel-title-subtitle">Cap'n Proto 消息浏览器</span>
          </div>
        </div>
        <div className="panel-header-actions">
          {messages.length > 0 ? (
            <button
              type="button"
              className="btn btn-sm btn-danger panel-action-btn"
              onClick={(e) => {
                e.stopPropagation()
                stopCereal()
              }}
            >
              停止
            </button>
          ) : (
            <button
              type="button"
              className="btn btn-sm btn-primary panel-action-btn"
              onClick={(e) => {
                e.stopPropagation()
                loadCerealData()
              }}
            >
              加载数据
            </button>
          )}
          <Icon
            name={isOpen ? "expand_more" : "chevron_right"}
            size={20}
            style={{ marginLeft: '8px', opacity: 0.7, cursor: 'pointer' }}
          />
        </div>
      </div>
      {isOpen && (
        <div className="panel-content" id="cereal-panel-content">
          {/* Cereal Controls */}
          <div className="cereal-controls cereal-controls-sticky">
            <div className="cereal-control-row">
              <label htmlFor="cereal-message-select">消息类型：</label>
              <select
                id="cereal-message-select"
                className="cereal-message-select"
                value={messageType}
                onChange={(e) => setMessageType(e.target.value)}
              >
                <optgroup label="车辆数据">
                  <option value="carState">carState - 车速、转向、踏板</option>
                  <option value="carControl">carControl - 执行器指令</option>
                  <option value="carOutput">carOutput - 实际输出</option>
                  <option value="carParams">carParams - 车辆配置</option>
                </optgroup>
                <optgroup label="规划与控制">
                  <option value="controlsState">controlsState - OP 状态</option>
                  <option value="longitudinalPlan">longitudinalPlan - 速度规划</option>
                  <option value="driverAssistance">driverAssistance - 辅助功能</option>
                </optgroup>
                <optgroup label="感知">
                  <option value="modelV2">modelV2 - 模型输出</option>
                  <option value="radarState">radarState - 雷达检测</option>
                  <option value="liveTracks">liveTracks - 跟踪目标</option>
                </optgroup>
                <optgroup label="定位">
                  <option value="liveCalibration">liveCalibration - 摄像头标定</option>
                  <option value="livePose">livePose - 车辆位姿</option>
                  <option value="gpsLocation">gpsLocation - GPS 数据</option>
                </optgroup>
                <optgroup label="驾驶员监控">
                  <option value="driverMonitoringState">driverMonitoringState - 面部/视线追踪</option>
                  <option value="driverStateV2">driverStateV2 - 驾驶员状态</option>
                </optgroup>
                <optgroup label="设备/系统">
                  <option value="deviceState">deviceState - 温度、电池、存储</option>
                  <option value="pandaStates">pandaStates - Panda 设备状态</option>
                  <option value="peripheralState">peripheralState - 风扇、USB</option>
                  <option value="managerState">managerState - 进程状态</option>
                </optgroup>
                <optgroup label="SunnyPilot/BluePilot">
                  <option value="selfdriveStateSP">selfdriveStateSP</option>
                  <option value="carStateSP">carStateSP</option>
                  <option value="carControlSP">carControlSP</option>
                  <option value="carStateBP">carStateBP</option>
                </optgroup>
              </select>
            </div>
            {messages.length > 0 && (
              <div className="cereal-status-row">
                <span id="cereal-last-update">Last updated: {lastUpdate}</span>
                <span id="cereal-message-count">
                  {messageCount} message{messageCount !== 1 ? 's' : ''}
                </span>
                <span style={{ marginLeft: 'auto', fontFamily: 'monospace', fontSize: '12px', opacity: 0.7 }}>
                  Msg #{currentMessageIndex + 1} | Video: {videoCurrentTime.toFixed(1)}s | Seg: {currentSegment}
                </span>
              </div>
            )}
          </div>

          {/* Cereal Data Table */}
          <div className="cereal-viewer-container">
            {loading ? (
              <div className="cereal-loading">
                <div className="spinner-small"></div>
                <span>正在加载 cereal 数据…</span>
              </div>
            ) : messages.length === 0 ? (
              <div className="cereal-viewer-empty">
                <p>点击“加载数据”查看 cereal 消息</p>
              </div>
            ) : (
              <table className="cereal-data-table">
                <thead>
                  <tr>
                    <th>字段</th>
                    <th>值</th>
                  </tr>
                </thead>
                <tbody id="cereal-data-body">
                  {Object.entries(flatData).map(([key, value]) => (
                    <tr key={key}>
                      <td className="cereal-field-name">{key}</td>
                      <td className="cereal-field-value">{formatCerealValue(value)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
