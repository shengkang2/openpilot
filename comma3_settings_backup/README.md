# comma3 设置备份（2026-10-21）

来源设备：comma3（局域网 192.168.0.7，主机名 comma-7ac6f53c，AGNOS aarch64）

## 内容

| 文件 | 说明 |
|---|---|
| `params_backup_20261021.tar.gz` | `/data/params/d` 全量参数打包（187 项），已排除敏感项 `GithubSshKeys`、`SshEnabled` |
| `device_state_20261021.txt` | 导出时的设备状态摘要（时间、内核、分支、HEAD、git status、磁盘） |

## 设备当时状态

- openpilot 分支：`spbp260825` @ `935d868`（含 3 条设备本地提交，此前未推送到 GitHub）
- 本分支 `spbp20261021` 基于 `935d868` 创建，即完整保留了设备的 3 条本地提交：
  - `935d868` fix(portal): json-safe /api/params for CarParams bytes; sunnylink PEM pubkey registration; panda prebuilt refresh
  - `8c148db` fix(drive-stats): fallback route timestamp from segment dir mtime for week stats
  - `7939191` ui: zh-CHS font subset + translation updates (BSM/rainbow desc)

## 恢复方法（设备端）

```bash
cd /data/params/d
tar xzf /path/to/params_backup_20261021.tar.gz
# 恢复后重启 openpilot 生效
```

注意：`GithubSshKeys`、`SshEnabled` 未包含在备份中，需按需单独恢复。
