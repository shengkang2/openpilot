import { useEffect, useMemo, useState } from 'react'
import { Button, LoadingSpinner, Modal, ToggleSwitch } from '@/components/common'
import { useParamsStore } from '@/stores/useParamsStore'
import type { Parameter } from '@/types'
import { formatParamValueForDisplay } from '@/utils/params'

type SortColumn = 'key' | 'value' | 'type' | 'category' | 'last_modified'
type SortDirection = 'asc' | 'desc'

const SORT_OPTIONS: { label: string; value: SortColumn }[] = [
  { label: '参数', value: 'key' },
  { label: '值', value: 'value' },
  { label: '类型', value: 'type' },
  { label: '分类', value: 'category' },
  { label: '最后修改', value: 'last_modified' },
]

const NUMERIC_TYPES = new Set(['number', 'int', 'float'])
const BOOLEAN_TYPES = new Set(['boolean', 'bool'])

const getSortValue = (param: Parameter, column: SortColumn): string | number | boolean | null | undefined => {
  switch (column) {
    case 'key':
      return param.key
    case 'value':
      return param.value
    case 'type':
      return param.type
    case 'category':
      return param.category ?? ''
    case 'last_modified':
      return param.last_modified ?? 0
    default:
      return ''
  }
}

export function DiagnosticsParameters() {
  const {
    params,
    loading,
    error,
    fetchParams,
    updateParam,
    searchQuery,
    setSearchQuery,
    getFilteredParams,
  } = useParamsStore()
  const [editingParam, setEditingParam] = useState<Parameter | null>(null)
  const [editValue, setEditValue] = useState('')
  const [editMode, setEditMode] = useState(false)
  const [sortColumn, setSortColumn] = useState<SortColumn>('key')
  const [sortDirection, setSortDirection] = useState<SortDirection>('asc')
  const [viewValueModal, setViewValueModal] = useState<Parameter | null>(null)

  useEffect(() => {
    fetchParams()
  }, [fetchParams])

  const formatLastModified = (timestamp?: number): string => {
    if (!timestamp) return '从未'

    const date = new Date(timestamp * 1000)
    const now = new Date()
    const diffMs = now.getTime() - date.getTime()
    const diffMins = Math.floor(diffMs / 60000)
    const diffHours = Math.floor(diffMs / 3600000)
    const diffDays = Math.floor(diffMs / 86400000)

    if (diffMins < 1) return '刚刚'
    if (diffMins < 60) return `${diffMins} 分钟前`
    if (diffHours < 24) return `${diffHours} 小时前`
    if (diffDays < 7) return `${diffDays} 天前`
    return date.toLocaleDateString('zh-CN')
  }

  const sortedParams = useMemo(() => {
    const filtered = getFilteredParams()
      .filter((param) => param.key && param.key !== 'null' && param.key !== 'undefined')

    return filtered.sort((a, b) => {
      let aVal = getSortValue(a, sortColumn)
      let bVal = getSortValue(b, sortColumn)

      if (aVal === undefined || aVal === null) aVal = ''
      if (bVal === undefined || bVal === null) bVal = ''

      if (typeof aVal === 'string') aVal = aVal.toLowerCase()
      if (typeof bVal === 'string') bVal = bVal.toLowerCase()

      if (aVal < bVal) return sortDirection === 'asc' ? -1 : 1
      if (aVal > bVal) return sortDirection === 'asc' ? 1 : -1
      return 0
    })
  }, [getFilteredParams, sortColumn, sortDirection])

  const toggleSortDirection = () => {
    setSortDirection((prev) => (prev === 'asc' ? 'desc' : 'asc'))
  }

  const handleEdit = (param: Parameter) => {
    setEditingParam(param)
    setEditValue(String(param.value))
  }

  const handleSave = async () => {
    if (!editingParam) return

    let value: string | number | boolean = editValue
    const type = editingParam.type?.toLowerCase()

    if (type && NUMERIC_TYPES.has(type)) {
      const parsed = Number(editValue)
      value = Number.isNaN(parsed) ? 0 : parsed
    } else if (type && BOOLEAN_TYPES.has(type)) {
      value = editValue === 'true'
    }

    await updateParam(editingParam.key, value)
    setEditingParam(null)
  }

  const handleViewValue = (param: Parameter) => {
    setViewValueModal(param)
  }

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text)
  }

  const handleManualRefresh = () => {
    fetchParams()
  }

  const formattedModalValue = viewValueModal ? formatParamValueForDisplay(viewValueModal) : null
  const modalValueDisplay = (() => {
    if (!formattedModalValue) return '—'
    if (formattedModalValue.isBinary) {
      if (formattedModalValue.decodedString) return formattedModalValue.decodedString
      if (viewValueModal?.raw_value) return viewValueModal.raw_value
    }
    return formattedModalValue.display || formattedModalValue.raw || '—'
  })()
  const modalCopyValue = formattedModalValue?.raw ?? modalValueDisplay

  return (
    <>
      <div className="diagnostics-controls">
        <div className="diagnostics-params-controls">
          <div className="search-container">
            <input
              type="text"
              className="search-input"
              placeholder="搜索参数…"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
            {searchQuery && (
              <button className="search-clear" onClick={() => setSearchQuery('')} aria-label="清除搜索">
                ✕
              </button>
            )}
          </div>
          <ToggleSwitch
            checked={editMode}
            onChange={(checked) => setEditMode(checked)}
            label="编辑模式"
            size="compact"
            className="diagnostics-toggle"
            title="启用参数编辑（谨慎使用）"
          />
          <div className="params-sort-controls">
            <label htmlFor="diagnostics-sort">排序</label>
            <select
              id="diagnostics-sort"
              value={sortColumn}
              onChange={(e) => setSortColumn(e.target.value as SortColumn)}
            >
              {SORT_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            <button
              type="button"
              className="sort-direction-btn"
              onClick={toggleSortDirection}
              title={`Switch to ${sortDirection === 'asc' ? 'descending' : 'ascending'} order`}
            >
              {sortDirection === 'asc' ? '↑ Asc' : '↓ Desc'}
            </button>
          </div>
        </div>
        <div className="control-buttons">
          <Button
            variant="primary"
            size="small"
            onClick={handleManualRefresh}
            className="diagnostics-refresh-btn"
            icon={<span aria-hidden="true">↻</span>}
          >
            刷新
          </Button>
        </div>
      </div>

      <div className="diagnostics-content">
        {loading && Object.keys(params).length === 0 ? (
          <LoadingSpinner message="正在加载参数…" />
        ) : error ? (
          <div className="diagnostics-error">
            <h2>参数加载失败</h2>
            <p>{error}</p>
          </div>
        ) : sortedParams.length === 0 ? (
          <div className="no-results">
            <p>未找到参数</p>
          </div>
        ) : (
          <div className="params-list">
            {sortedParams.map((param) => {
              const formattedValue = formatParamValueForDisplay(param)
              const trimmed = formattedValue.display.trim()
              const preview =
                trimmed.length > 260 ? `${trimmed.substring(0, 257).trimEnd()}…` : trimmed || '—'
              const formatBadge = formattedValue.formatLabel?.toUpperCase()
              const typeBadge = param.type ? param.type.toUpperCase() : null
              const categoryBadge = param.category ?? null

              return (
                <div className="param-row" key={param.key}>
                  <div className="param-row__header">
                    <div className="param-row__title-block">
                      <div className="param-row__title-line">
                        <span className="param-key" title={param.key}>
                          {param.key}
                        </span>
                        <div className="param-row__status-chips">
                          {param.readonly && <span className="param-badge readonly">readonly</span>}
                          {param.critical && <span className="param-badge critical">critical</span>}
                        </div>
                      </div>
                      <div className="param-last-modified">修改时间：{formatLastModified(param.last_modified)}</div>
                      {param.description && <div className="param-last-modified">{param.description}</div>}
                    </div>
                    <div className="param-row__actions">
                      {param.readonly ? (
                        <Button size="small" variant="ghost" className="param-edit-btn" disabled>
                          只读
                        </Button>
                      ) : (
                        <Button
                          size="small"
                          variant="primary"
                          className="param-edit-btn"
                          onClick={() => handleEdit(param)}
                          disabled={!editMode || param.type === 'bytes'}
                          title={param.type === 'bytes' ? 'Binary parameters are view-only' : undefined}
                        >
                          编辑
                        </Button>
                      )}
                    </div>
                  </div>
                  <div className="param-row__value" title="点击查看完整值" onClick={() => handleViewValue(param)}>
                    <div className="param-row__value-header">
                      <span className="value-label">值</span>
                      <div className="value-pill-group">
                        {typeBadge && <span className="value-pill value-pill--type">{typeBadge}</span>}
                        {categoryBadge && (
                          <span className="value-pill value-pill--category">{categoryBadge}</span>
                        )}
                        {formatBadge && formatBadge !== typeBadge && <span className="value-pill">{formatBadge}</span>}
                        {param.type === 'bytes' && param.byte_length !== undefined && (
                          <span className="value-pill value-pill--outline">{param.byte_length} bytes</span>
                        )}
                      </div>
                    </div>
                    <pre className="value-code-block">
                      <code>{preview}</code>
                    </pre>
                    <span className="value-footer-hint">点击查看完整值</span>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>

      <Modal
        isOpen={editingParam !== null}
        onClose={() => setEditingParam(null)}
        title={`Edit ${editingParam?.key}`}
        size="small"
      >
        <div className="edit-param-modal">
          <div className="param-info">
            <p><strong>类型：</strong> {editingParam?.type}</p>
            {editingParam?.description && <p><strong>说明：</strong> {editingParam.description}</p>}
          </div>
          {editingParam?.type && BOOLEAN_TYPES.has(editingParam.type.toLowerCase()) ? (
            <select value={editValue} onChange={(e) => setEditValue(e.target.value)} className="edit-input">
              <option value="true">true</option>
              <option value="false">false</option>
            </select>
          ) : (
            <input
              type={editingParam?.type && NUMERIC_TYPES.has(editingParam.type.toLowerCase()) ? 'number' : 'text'}
              value={editValue}
              onChange={(e) => setEditValue(e.target.value)}
              className="edit-input"
            />
          )}
          <div className="modal-actions">
            <Button variant="secondary" onClick={() => setEditingParam(null)}>
              取消
            </Button>
            <Button variant="primary" onClick={handleSave}>
              保存
            </Button>
          </div>
        </div>
      </Modal>

      <Modal
        isOpen={viewValueModal !== null}
        onClose={() => setViewValueModal(null)}
        title="参数详情"
        size="large"
      >
        {viewValueModal && (
          <div className="param-modal-simple">
            <div className="param-modal-simple__header">
              <span className="param-key-label">参数键名</span>
              <div className="param-key-value-wrapper">
                <code className="param-key-value">{viewValueModal.key}</code>
                <button className="icon-btn" onClick={() => copyToClipboard(viewValueModal.key)}>
                  📋
                </button>
              </div>
            </div>

            <div className="param-modal-simple__value">
              <div className="value-pill-group">
                {viewValueModal.type && (
                  <span className="value-pill value-pill--type">{viewValueModal.type.toUpperCase()}</span>
                )}
                {viewValueModal.category && (
                  <span className="value-pill value-pill--category">{viewValueModal.category}</span>
                )}
                {formattedModalValue?.formatLabel && (
                  <span className="value-pill">{formattedModalValue.formatLabel.toUpperCase()}</span>
                )}
                {viewValueModal.type === 'bytes' && viewValueModal.byte_length !== undefined && (
                  <span className="value-pill value-pill--outline">{viewValueModal.byte_length} bytes</span>
                )}
              </div>
              <pre
                className={`value-code-block value-code-block--modal ${
                  formattedModalValue?.isBinary ? 'binary-value' : 'text-value'
                }`}
              >
                <code>{modalValueDisplay}</code>
              </pre>
            </div>

            <div className="param-modal-simple__actions">
              <Button variant="secondary" onClick={() => copyToClipboard(modalCopyValue)}>
                复制值
              </Button>
              <Button variant="secondary" onClick={() => copyToClipboard(viewValueModal.key)}>
                复制键名
              </Button>
              <Button variant="primary" onClick={() => setViewValueModal(null)}>
                关闭
              </Button>
            </div>
          </div>
        )}
      </Modal>
    </>
  )
}
