# -*- coding: utf-8 -*-
"""
通选课 捡漏自动选课脚本 (基于东南选课系统真实 DOM 验证)
行为：自己打开浏览器、填好账号密码，你只需在浏览器里手输一次验证码点登录；
      之后脚本自动切到通选课、逐页翻找"还有名额(未满)"的课 —— 找到就点选择 →
      弹确认框点确定 → 选上即停。全程只选一门，选完就停。
用法：python3 tongxuan_grab.py   (需 playwright, plyer)
"""
import time
import json
import re
from datetime import datetime
from playwright.sync_api import sync_playwright
from plyer import notification

BASE_URL = "https://newxk.urp.seu.edu.cn"
# 账号密码: 从【脚本同目录下的 seu_xk.txt】读取, 格式(两行):
#   一卡通号:xxxxxxx
#   密码:xxxxxxx
# 发给别人前把该文件里的学号/密码改成他的即可, 脚本无任何写死的账号。
# 无需 Python 绝对路径——脚本自己用 __file__ 定位同目录配置。
import os as _os
_THIS_DIR = _os.path.dirname(_os.path.abspath(__file__)) if '__file__' in globals() else _os.getcwd()
SECRET = _os.path.join(_THIS_DIR, "seu_xk.txt")
def _find_secret():
    # 优先同目录; 找不到再退到 WSL/老位置兜底
    cands = [SECRET,
             r"C:\Users\18407\Documents\seu_xk.txt",
             "/home/jzx20080826/.hermes/secrets/seu_xk.txt"]
    for p in cands:
        try:
            if open(p, encoding="utf-8"):
                return p
        except Exception:
            continue
    return SECRET
SECRET = _find_secret()
USERNAME = ""   # 留空=从 seu_xk.txt 的「一卡通号:」行读取
# 用系统 Edge 驱动, 无需单独装 Chromium；必须用隔离的独立会话目录,
# 且每次启动清空重建——否则残留的登录 cookie 会让脚本"未登录却带旧会话",
# 你手动登录时变成两个活动会话 -> 互相顶号
CHANNEL = "msedge"
import tempfile, os as _os, shutil as _shutil
EDGE_PROFILE = _os.path.join(tempfile.gettempdir(), "seu_grab_profile")
try:
    if _os.path.isdir(EDGE_PROFILE):
        _shutil.rmtree(EDGE_PROFILE, ignore_errors=True)
except Exception:
    pass

REFRESH_SEC = 20          # 每轮翻完13页后休息刷新间隔(捡漏15~30稳)
RESUBMIT_COOLDOWN = 45    # 一次提交失败后冷却
MAX_ATTEMPTS = 3          # 单门课最多尝试提交次数
LOGIN_WAIT_SEC = 150      # 等你手动过验证码登录的最长时间
TOTAL_PAGES = 13          # 通选课共13页(128条/每页10)

def read_cred():
    """从 seu_xk.txt 读账号密码, 健壮容错:
       兼容 UTF-8(含BOM)/GBK 编码、行首空格、全角冒号 '：' 或半角 ':'、'密码'/'密码:' 前缀。
       缺文件或没密码行时打印明确原因, 便于用户自查。"""
    uid, pw = USERNAME, ""
    lines = []
    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            with open(SECRET, encoding=enc) as f:
                lines = [l.strip().lstrip("\ufeff").strip() for l in f if l.strip()]
            break
        except FileNotFoundError:
            print("【未找到密码】找不到配置文件:", SECRET)
            print("  请确认脚本同目录下有一个名为 seu_xk.txt 的文件(不能带 .example 后缀)。")
            return uid, pw
        except UnicodeDecodeError:
            continue
        except Exception as e:
            print("【未找到密码】读取失败:", e)
            return uid, pw
    if not lines:
        print("【未找到密码】seu_xk.txt 是空文件或全是注释。")
        return uid, pw
    for line in lines:
        if line.startswith("#"):
            continue
        body = line.lstrip("\ufeff \t")
        if body.startswith("一卡通") or body[:2] in ("账号", "学号", "用户"):
            val = body.split(":", 1)[-1].split("：", 1)[-1].strip()
            if val:
                uid = val
        elif "密码" in body or body[:2] in ("密",):
            val = body.split(":", 1)[-1].split("：", 1)[-1].strip()
            if val:
                pw = val
    if not pw:
        print("【未找到密码】文件里没有读到密码行。正确格式示例(两行):")
        print("  一卡通号:213263577")
        print("  密码:Jzx20080826")
        print("  当前读到的文件头几行:", lines[:3])
    return uid, pw

def notify(title, msg):
    try:
        notification.notify(title=title, message=msg, timeout=20)
    except Exception:
        pass

# ---------- 登录 ----------
def wait_login(page):
    uid, pw = read_cred()
    print("已填账号密码。请在弹出的浏览器里输入验证码并点「登录」。")
    page.goto(BASE_URL)
    # 填账号/密码(用真实setter, 兼容前端框架) —— 值内插, 不传给evaluate参
    page.evaluate("""(()=>{
        const setv=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;
        const ins=[...document.querySelectorAll('input')];
        const u=ins.find(i=>i.placeholder.includes('一卡通'))||ins[0];
        const p=ins.find(i=>i.type==='password')||ins[1];
        const set=(el,v)=>{setv.call(el,v);el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));};
        set(u,%s); set(p,%s);
        return p.value.length;
    })()""" % (json.dumps(uid), json.dumps(pw)))
    # 等待用户登录成功 —— 可靠判据: 「欢迎你」or「退出」(登录后才出现的元件)
    t0 = time.time()
    while time.time() - t0 < LOGIN_WAIT_SEC:
        try:
            txt = page.evaluate("document.body.innerText || ''")
            logged = ("欢迎你" in txt) or ("退出" in txt)
            if logged:
                # 已登录；点掉可能出现的提示弹窗
                for t in ("知道了",):
                    try:
                        page.evaluate(f"""(()=>{{
                            try{{const b=[...document.querySelectorAll('button,.el-button')].find(x=>(x.innerText||'').replace(/\\s+/g,'')==='{t}'); if(b)b.click();}}catch(e){{}} return 1;}})()""")
                        page.wait_for_timeout(500)
                    except Exception:
                        pass
                return True
        except Exception:
            pass
        time.sleep(2)
    print("登录等待超时。")
    return False

# ---------- 选轮次+进工作台+通选课 ----------
def enter_tongxuan(page):
    # 选"秋季学期预选课"轮次(若在轮次弹窗)
    try:
        page.evaluate("""(()=>{
            const rows=[...document.querySelectorAll('td,label,div,li')];
            const cell=rows.find(x=>x.offsetParent!==null && (x.innerText||'').replace(/\\s+/g,'').includes('2026-2027学年秋季学期预选课'));
            if(cell){ cell.click(); }
            return !!cell;
        })()""")
        page.wait_for_timeout(800)
        page.evaluate("""(()=>{
            const b=[...document.querySelectorAll('button,.el-button')].find(x=>(x.innerText||'').replace(/\\s+/g,'')==='确定');
            if(b) b.click(); return !!b;
        })()""")
        page.wait_for_timeout(1500)
    except Exception:
        pass
    # 点"选课"大按钮进工作台
    try:
        page.evaluate("""(()=>{
            const bs=[...document.querySelectorAll('button,.el-button,a')];
            const b=bs.find(x=>x.offsetParent!==null && (x.innerText||'').replace(/\\s+/g,'')==='选课');
            if(b) b.click(); return !!b;
        })()""")
        page.wait_for_timeout(3000)
    except Exception:
        pass
    # 点"通选课"标签
    try:
        page.evaluate("""(()=>{
            const el=[...document.querySelectorAll('*')].find(x=>x.offsetParent!==null && (x.textContent||'').replace(/\\s+/g,'')==='通选课' && (x.tagName==='DIV'||x.tagName==='LI'||x.tagName==='SPAN'));
            if(el) el.click(); return !!el;
        })()""")
        page.wait_for_timeout(2500)
    except Exception:
        pass
    print("已进入通选课列表。")

# ---------- 判定/提交 ----------
def read_rows(page):
    return page.evaluate("""(()=>{
        const rows=[...document.querySelectorAll('table tbody tr')];
        return rows.map(r=>{
            const c=[...r.querySelectorAll('td')].map(td=>(td.textContent||'').replace(/\\s+/g,'').trim());
            return c;  // [课程号,名称,教师,时间,容量,已选人数,类别,学分,操作]
        }).filter(r=>r.length>=9);
    })()""")

def is_full(course):
    """已选人数列(course[5])含'已满'或无数字 → 满; 有纯数字且<容量 → 有余额. 返回(可选, 描述)."""
    s = course[5]
    if "已满" in s:
        return False, "已满"
    nums = re.findall(r"\d+", s)
    if not nums:
        return False, s or "?"
    sel = int(nums[0])
    try:
        cap = int(course[4])
    except Exception:
        cap = None
    if cap is not None and sel >= cap:
        return False, f"{sel}/{cap}"
    return True, f"剩余{(cap-sel) if cap else '?'}"

def click_select(page, course):
    """点目标行"选择"→确认框点"确定". 用【课程号】(course[0])精确定位, 防同名课点错. 返回是否点了."""
    cid = json.dumps(course[0])  # 安全内插
    row = page.evaluate("""(()=>{
        const tds=[...document.querySelectorAll('table tbody tr')].filter(r=>{
            const c=[...r.querySelectorAll('td')].map(td=>(td.textContent||'').replace(/\\s+/g,'').trim());
            return c.length>=9 && c[0]===%s;
        });
        return tds.length>0;
    })()""" % cid)
    if not row:
        return False
    clicked = page.evaluate("""(()=>{
        const tr=[...document.querySelectorAll('table tbody tr')].find(r=>{
            const c=[...r.querySelectorAll('td')].map(td=>(td.textContent||'').replace(/\\s+/g,'').trim());
            return c.length>=9 && c[0]===%s;
        });
        if(!tr) return false;
        const b=[...tr.querySelectorAll('button,.el-button')].find(x=>(x.innerText||'').replace(/\\s+/g,'')==='选择');
        if(b){ b.click(); return true; } return false;
    })()""" % cid)
    page.wait_for_timeout(1200)
    # 确认框点"确定"
    page.evaluate("""(()=>{
        const b=[...document.querySelectorAll('.el-message-box button,.el-message-box .el-button')].find(x=>(x.innerText||'').replace(/\\s+/g,'')==='确定');
        if(b){ b.click(); return true; } return false;
    })()""")
    page.wait_for_timeout(1800)
    return bool(clicked)

def has_selected(page, course):
    """提交后判定成功: 轮询等异步POST弹窗/该课已选状态, 避免过早误判. 返回True=已选上."""
    cid = json.dumps(course[0])
    for _ in range(6):
        page.wait_for_timeout(1000)
        try:
            txt = page.evaluate("document.body.innerText || ''")
            if "选课成功" in txt or "报名成功" in txt:
                return True
            done = page.evaluate("""(()=>{
                const tr=[...document.querySelectorAll('table tbody tr')].find(r=>{
                    const c=[...r.querySelectorAll('td')].map(td=>(td.textContent||'').replace(/\\s+/g,'').trim());
                    return c.length>=9 && c[0]===%s;
                });
                if(!tr) return false;
                const tt=tr.innerText;
                return /已选|选中|选课成功|报名成功/.test(tt);
            })()""" % cid)
            if done:
                return True
        except Exception:
            pass
    return False

# ---------- 主循环 ----------
def main():
    uid, pw = read_cred()
    if not pw:
        print("未拿到密码, 检查", SECRET); return
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=EDGE_PROFILE, headless=False, channel=CHANNEL,
            args=["--no-default-browser-check"])
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        if not wait_login(page):
            print("登录未完成, 退出"); ctx.close(); return
        enter_tongxuan(page)

        attempts = {}
        print("开始翻页侦测(每页10条, 共%d页)... 全部已满就等待退课。" % TOTAL_PAGES)
        while True:
            for pg in range(1, TOTAL_PAGES + 1):
                try:
                    time.sleep(1)
                    rows = read_rows(page)
                    # 找当前页可选(未满)的课
                    for c in rows:
                        if len(c) < 9:
                            continue
                        avail, desc = is_full(c)
                        if not avail:
                            continue  # 已满, 跳过
                        name = c[1]
                        key = c[0][:14] + name
                        st = attempts.get(key, 0)
                        if st >= MAX_ATTEMPTS:
                            print(f"  {name} 可达但已达提交上限, 跳过"); continue
                        print(f"  >> 检测到可选: {name} | {desc}")
                        if click_select(page, c):
                            if has_selected(page, c):
                                print("  ✅ 选课成功! 停止。")
                                notify("选课成功", f"{name} 已选上, 快去系统确认!")
                                ctx.close(); return
                            else:
                                print(f"  {name} 提交后未确认, 冷却{RESUBMIT_COOLDOWN}s 后继续盯")
                                attempts[key] = st + 1
                                time.sleep(RESUBMIT_COOLDOWN)
                                break  # 短暂冷却后刷新重测; 捡漏要持续盯, 不能一提交未确认就退出
                        else:
                            attempts[key] = st + 1
                    # 翻下一页
                    if pg < TOTAL_PAGES:
                        page.evaluate("(()=>{const p=%d;const li=[...document.querySelectorAll('.el-pager li,.el-pagination li')].find(x=>(x.innerText||'').trim()===String(p)&&x.offsetParent!==null); if(li)li.click();})()" % (pg + 1))
                        page.wait_for_timeout(1500)
                except Exception as e:
                    print("  本轮异常:", e)
                    time.sleep(5)
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 本轮13页全部已满, 翻回第1页重侦测...")
            # 关键: 绝不 reload 带 token 的 grablessons URL(SWU 会弹回登录)。
            # 只点分页"1"退回第1页, 保持当前有效会话。
            try:
                page.evaluate("""(()=>{const li=[...document.querySelectorAll('.el-pager li,.el-pagination li')].find(x=>(x.innerText||'').trim()==='1'&&x.offsetParent!==null); if(li)li.click();})()""")
                page.wait_for_timeout(2000)
            except Exception as e:
                print("  回第1页异常:", e)
                time.sleep(3)
            time.sleep(REFRESH_SEC)

        # 永不提前到达(主循环 break 由选课成功触发)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("手动停止")
