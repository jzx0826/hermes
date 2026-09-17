# Hermes

日常脚本 / 工具集

## 目录结构

| 目录 | 说明 |
|------|------|
| `seu-course/` | SEU 选课工具（通选课捡漏） |

## seu-course — SEU 选课工具

| 文件 | 说明 |
|------|------|
| `tongxuan_grab.py` | 通选课捡漏自动选课 — 打开浏览器，翻13页找有空位的课，找到就选，选完就停 |
| `tongxuan_pickup_monitor.py` | 通选课捡漏盯梢 — 后台挂机，有空位时弹窗通知你手动选 |
| `通选课捡漏.bat` | 双击启动 tongxuan_grab.py 的批处理 |

### 使用方法

1. 在 **脚本同目录** 下放 `seu_xk.txt`（两行）：
   ```
   一卡通号:213263577
   密码:你的密码
   ```
2. 双击 `通选课捡漏.bat` 或 `python3 tongxuan_grab.py`
3. 在弹出的浏览器里手输验证码登录，之后脚本自动工作

### 依赖

```bash
pip install playwright plyer
playwright install msedge
```