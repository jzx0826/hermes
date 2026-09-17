import time
from datetime import datetime
from playwright.sync_api import sync_playwright
from plyer import notification

# ========== 只改这里 ==========
LOGIN_URL = "https://newxk.urp.seu.edu.cn"
SELECT_PAGE_URL = "https://你的通选课列表页地址"   # 登录后进通选课工作台, F12 拿真实地址

USERNAME = "你的学号"
PASSWORD = ""   # 留空=自动读 WSL secrets 文件, 不硬编码

HEADLESS = True          # True=后台无窗(挂机用); False=看到浏览器调试
REFRESH_SEC = 20         # 盯梢节奏 15~30; 退课名额不会几秒就丢
RESUBMIT_COOLDOWN = 45   # 一次提交失败后冷却秒数, 防刷屏重试(也是最轻指纹)
MAX_ATTEMPTS = 3         # 每门课最多尝试提交次数, 到限就停, 防死循环空耗
MAX_RUN_SEC = 3 * 3600   # 最多盯3h, 到点自动退

# 每门课 dict:
#   name         通知标题
#   avail_sel    用来判断有没有名额的元素 (F12)
#   avail_type   "remain"=这里的数字>0 算有名额; "btn"=按钮未禁用 算有名额
#   submit_sel   真正要点的"选课"按钮
#   confirm_sel  可空: 点选课后弹出的"确定/确认"按钮
#   success_key  可空: 成功提示里的关键词, 如 "选课成功"; 留空用默认
#   done_sel     可空: 已选状态的标志元素 (出现即视为已选中, 不再提交)
COURSES = [
    {"name": "通选课A", "avail_type": "remain", "avail_sel": "#course-a .remain",
     "submit_sel": "#course-a .select-btn", "confirm_sel": "", "success_key": "选课成功", "done_sel": ""},
    {"name": "通选课B", "avail_type": "btn",   "avail_sel": "#course-b .select-btn",
     "submit_sel": "#course-b .select-btn", "confirm_sel": "", "success_key": "选课成功", "done_sel": ""},
]
# ==============================

DEFAULT_SUCCESS_KEY = "选课成功"

def load_password():
    if PASSWORD:
        return PASSWORD
    try:
        with open("/home/jzx20080826/.hermes/secrets/seu_xk.txt", "r") as f:
            for line in f:
                line = line.strip()
                if line.startswith("密码"):
                    return line.split(":", 1)[-1].strip()
        return ""
    except Exception:
        return ""

def notify(title, msg):
    try:
        notification.notify(title=title, message=msg, timeout=20)
    except Exception:
        pass

def get_avail(page, c):
    """有名额-> (True, desc) / 无->(False, desc) / 元素缺失->(False, 'no_elem')."""
    sel = c["avail_sel"]
    try:
        elem = page.query_selector(sel)
        if elem is None:
            return False, "no_elem"
        if c["avail_type"] == "remain":
            import re
            nums = re.findall(r"\d", elem.inner_text())
            num = int(''.join(nums)) if nums else 0
            return num > 0, f"剩余{num}"
        elif c["avail_type"] == "btn":
            disabled = elem.get_attribute("disabled")
            return disabled is None, f"disabled={disabled}"
        return False, "unknown_type"
    except Exception as e:
        return False, f"err:{e}"

def is_done(page, c):
    s = c.get("done_sel", "")
    if s and page.query_selector(s):
        return True
    return False

def submit(page, c):
    """点选课 + 确认 + 判定成功. 返回 True=成功."""
    try:
        btn = page.query_selector(c["submit_sel"])
        if btn is None:
            return False
        btn.click()
        page.wait_for_timeout(1500)
        cs = c.get("confirm_sel", "")
        if cs:
            cf = page.query_selector(cs)
            if cf:
                cf.click()
                page.wait_for_timeout(1000)
        # 判定成功: 优先关键词, 再兜底页面内容
        kw = c.get("success_key") or DEFAULT_SUCCESS_KEY
        page.wait_for_timeout(2500)   # 等异步POST返回
        if c.get("done_sel") and page.query_selector(c["done_sel"]):
            return True
        if kw in page.content():
            return True
        return False
    except Exception as e:
        return False

def main():
    password = load_password()
    if not password:
        print("未拿到密码: 填 PASSWORD 或检查 secrets 文件")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        page = browser.new_page()
        # 每门课: attempts(已提交尝试), cooldown_until(时间戳), done(已选中)
        st = {c["name"]: {"attempts": 0, "next_attempt": 0, "done": False} for c in COURSES}

        # 1. 登录
        print("登录中...")
        page.goto(LOGIN_URL)
        page.fill("#username", USERNAME)
        page.fill("#password", password)
        page.wait_for_timeout(1500)
        page.keyboard.press("Enter")          # 登录按钮文本常带空格"登 录", Enter 更稳
        page.wait_for_timeout(5000)           # 等统一认证跳转+前端渲染

        # 2. 进通选课工作台
        print("进通选课列表页...")
        page.goto(SELECT_PAGE_URL)
        page.wait_for_timeout(3000)           # 等表格渲染

        start = time.time()
        count = 0
        try:
            while True:
                if time.time() - start > MAX_RUN_SEC:
                    print("到点, 停止")
                    break
                count += 1
                now = datetime.now().strftime("%H:%M:%S")
                print(f"第{count}次 | {now}")

                for c in COURSES:
                    s = st[c["name"]]
                    if s["done"]:
                        continue                       # 已选定, 跳过
                    if time.time() < s["next_attempt"]:
                        continue                       # 冷却中
                    if is_done(page, c):
                        print(f"   {c['name']} 已选中, 停止")
                        s["done"] = True
                        notify("选课完成", f"{c['name']} 已选上")
                        continue

                    avail, desc = get_avail(page, c)
                    if not avail:
                        print(f"   {c['name']} 无名额 | {desc}")
                        s["next_attempt"] = 0          # 无名额不占用冷却
                        continue

                    if s["attempts"] >= MAX_ATTEMPTS:
                        print(f"   {c['name']} 有名额但超过尝试上限, 放弃自动提交")
                        notify("放弃自动提交", f"{c['name']} 仍有名额, 但已试{MAX_ATTEMPTS}次未成, 请手工!")
                        s["done"] = True               # 交给用户, 不再空耗
                        continue

                    print(f"   {c['name']} 有名额 | {desc}  -> 自动提交 (第{s['attempts']+1}次)")
                    ok = submit(page, c)
                    s["attempts"] += 1
                    if ok:
                        print(f"   >>> {c['name']} 选课成功!")
                        notify("选课成功", f"{c['name']} 已选上, 快去系统确认!")
                        s["done"] = True
                    else:
                        print(f"   {c['name']} 提交未确认, 冷却{RESUBMIT_COOLDOWN}s 再试")
                        notify("提交未确认", f"{c['name']} 自动提交未确认, 稍后再试")
                        s["next_attempt"] = time.time() + RESUBMIT_COOLDOWN

                time.sleep(REFRESH_SEC)
                page.reload()
                page.wait_for_timeout(2000)
        except KeyboardInterrupt:
            print("手动停止")

        input("按回车关闭浏览器...")
        browser.close()

if __name__ == "__main__":
    main()
