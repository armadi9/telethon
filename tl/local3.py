from quart import Quart, jsonify, request, Response
import asyncio, base64, logging, httpx, os, time
from urllib.parse import urlparse
from typing import Optional
from rich.progress import Progress
import zendriver
from zendriver.cdp import fetch, network
from zendriver.cdp.fetch import RequestPattern
from zendriver.core.element import Element
from zendriver.cdp.emulation import UserAgentBrandVersion, UserAgentMetadata
from selenium_authenticated_proxy import SeleniumAuthenticatedProxy
import websockets
import random
from colorama import Fore, Style, init

# ----------------------------
# Initialize colorama
# ----------------------------
init(autoreset=True)

# ----------------------------
# Colors
# ----------------------------
colors = [
    Fore.RED, Fore.GREEN, Fore.YELLOW, Fore.BLUE, Fore.MAGENTA, Fore.CYAN,
    Fore.LIGHTRED_EX, Fore.LIGHTGREEN_EX, Fore.LIGHTYELLOW_EX,
    Fore.LIGHTBLUE_EX, Fore.LIGHTMAGENTA_EX, Fore.LIGHTCYAN_EX
]

# ----------------------------
# Logging disable
# ----------------------------
logging.getLogger("hypercorn.access").disabled = True
logging.getLogger("hypercorn.error").disabled = True

# ----------------------------
# Global Progress
# ----------------------------
global_progress = Progress()
global_progress.start()

app = Quart(__name__)

# ----------------------------
# Global browser
# ----------------------------
browser = None
browser_lock = asyncio.Lock()

# small bookkeeping
limit_done = 2000
opened_tabs_count = 0
closed_tabs_count = 0
tab_error = 0

# ----------------------------
# Limit jumlah window (maksimal 4 sekaligus)
# ----------------------------
window_limit = asyncio.Semaphore(4)

# ----------------------------
# Active requests mapping
# key: tab_id (id(tab))
# value: asyncio.Future that will be completed with:
#   - quart.Response(...) if cleanup closes the tab (HTTP 500)
#   - or other value (cf_clearance string) when solve completes
# ----------------------------
active_requests: dict[int, asyncio.Future] = {}

# ----------------------------
# Helper: get_browser
# ----------------------------
async def get_browser():
    global browser
    async with browser_lock:
        if browser is None:
            config = zendriver.Config(headless=True)
            config.add_argument("--disable-background-timer-throttling")
            config.add_argument("--disable-backgrounding-occluded-windows")
            config.add_argument("--disable-renderer-backgrounding")
            config.add_argument(
                "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36"
            )

            host_rules = [
                "MAP challenges.cloudflare.com challenges.cloudflare.com",
                "MAP * ~NOTFOUND"
            ]

            config._default_browser_args.extend([f'--host-rules={",".join(host_rules)}'])

            # sample IP list (kept as in original)
            ip_list = [
                # "43.228.238.102","43.228.238.105","43.228.238.107","43.228.238.111","43.228.238.112","43.228.238.116","43.228.238.124","43.228.238.126","43.228.238.127","43.228.238.130","43.228.238.14","43.228.238.142","43.228.238.149","43.228.238.152","43.228.238.155","43.228.238.157","43.228.238.160","43.228.238.168","43.228.238.169","43.228.238.177","43.225.188.124","43.225.188.171","43.225.188.232","43.225.188.247","43.225.188.249","43.225.188.41","43.225.188.75","43.228.238.74","43.228.238.5","43.228.238.180","43.228.239.222","43.228.239.148","43.228.238.7","43.228.239.216","43.228.239.149","43.228.239.208","43.228.239.51","43.228.239.58","43.228.238.191","43.228.238.27","43.225.188.11","43.225.188.110","43.225.188.133","43.225.188.139","43.225.188.156","43.225.188.180","43.228.239.87","43.228.239.82","43.228.238.31","43.228.239.169","43.228.238.80","43.228.238.96","43.228.238.166","43.228.239.229","43.228.239.126","43.228.239.5","43.228.239.214","43.228.239.134","43.228.238.100","43.228.238.36","43.228.238.46","43.228.239.6","43.228.239.9","43.228.238.125","43.228.238.21","43.225.188.94","103.84.120.209","103.84.120.157","43.228.239.160","43.228.239.161","103.84.120.17","43.228.238.205","43.228.239.26","43.228.238.237","43.228.239.27","43.228.238.156","43.228.239.10","43.225.188.112","103.84.121.1","43.228.239.220","43.225.188.159","43.225.188.243","43.228.239.122","43.228.239.240","43.228.238.10","43.228.239.190","43.228.239.243","43.228.239.144","43.228.238.227","43.228.238.229","43.228.238.73","43.228.238.82","43.228.238.193","43.228.238.123","43.228.238.70","43.228.239.16","43.228.239.65","43.228.238.114","43.228.238.17","43.228.238.91","43.228.239.207","43.228.239.2","43.228.239.141","43.228.239.188","43.228.239.236","43.228.238.98","43.228.239.143","43.228.239.140","43.225.188.132","43.228.238.53","43.228.238.28","43.228.238.174","80.240.122.204","80.240.119.205","80.240.118.40","89.184.196.254","80.240.119.151","80.240.123.2","89.184.199.230","31.14.219.200","89.184.193.4","89.184.209.105","89.184.206.217","89.44.245.142","89.184.220.29","212.70.22.118","78.138.30.179","121.91.185.212","121.91.182.180","121.91.184.1","103.204.212.110","103.204.214.238","121.91.176.218","119.13.231.58","119.13.230.16","119.13.237.80","119.13.224.217","119.13.224.115","119.13.228.124","94.177.53.38","185.243.110.99","185.225.106.195","89.32.129.178","31.14.236.33","89.184.217.126","119.13.230.207","121.91.186.113","121.91.180.137","103.204.215.213","188.241.146.204","77.95.118.168","94.177.55.20","31.14.237.100","89.184.215.80","89.44.115.13","89.184.219.183","89.184.210.172","119.13.230.249","119.13.236.150","89.184.213.187","94.177.53.245","77.95.116.30","150.107.226.47","119.13.225.145","121.91.189.160","121.91.190.184","119.13.235.209","121.91.187.60","119.13.229.251","119.13.227.89","119.13.232.129","89.184.200.15","121.91.189.196","119.13.233.198","119.13.238.105","119.13.230.191","119.13.226.237","119.13.234.247","119.13.228.31","119.13.227.188","43.228.239.43","43.228.239.117","89.184.219.182","121.91.179.231","121.91.189.106","121.91.189.29","185.225.105.76","119.13.236.21","89.184.218.188","119.13.235.234","185.225.104.219","121.91.185.97","121.91.186.8","212.70.16.146","121.91.176.45","185.101.68.59","94.177.52.240","43.228.239.88","43.228.238.223","89.34.7.119","185.221.221.22","43.225.188.179","119.13.226.173","43.225.188.228","119.13.229.244","121.91.189.154","43.228.238.146","43.228.239.110","43.228.239.64","212.70.21.115","212.70.27.51","89.184.217.219","185.225.106.11","212.70.4.247","89.184.209.210","43.228.239.29","43.228.239.218","43.228.238.15","43.228.239.244","43.228.239.37","43.228.239.246","185.101.69.57","212.70.25.245","119.13.233.81","119.13.238.173","119.13.232.1","212.70.1.76","94.177.55.14","89.184.208.50","119.13.239.19","119.13.226.4","119.13.236.158","94.139.41.18","94.139.45.201","185.101.68.202","89.184.195.187","119.13.230.21","119.13.238.90","212.70.26.254","121.91.185.252","121.91.184.223","188.68.3.61","77.95.117.5","119.13.233.58","188.68.3.248","185.223.58.47","80.240.123.188","89.184.193.106","188.68.3.158","43.228.239.79","43.228.239.225","43.228.239.50","43.228.238.225","43.228.238.137","43.228.239.120","43.228.239.104","43.228.239.177","43.228.238.189","43.228.238.198","43.228.238.45","188.68.3.13","119.13.231.144","89.184.220.203","188.68.3.109","121.91.188.251","121.91.187.193","43.228.238.226","43.228.239.224","119.13.226.156","119.13.228.137","121.91.189.75","212.70.31.22","89.184.193.162","89.184.222.134","212.70.5.134","119.13.232.53","119.13.229.25","43.228.239.170","89.44.115.180","161.123.56.217","43.228.238.118","89.184.206.251","121.91.188.94","188.68.3.154","119.13.239.103","89.44.115.147","185.101.71.4","121.91.186.60","212.70.31.211","89.184.211.93","89.184.221.113","43.228.239.198","212.70.22.141","119.13.228.103","89.184.207.29","119.13.239.221","43.228.238.16","43.228.239.248","43.228.239.101","212.70.7.140","89.184.214.217","43.228.238.99","89.184.197.133","103.84.120.6","43.228.239.152","43.228.238.93","43.228.239.173","43.228.239.156","119.13.231.88","89.184.194.219","119.13.228.181","103.84.120.165","119.13.225.121","119.13.237.138","161.123.94.178","119.13.236.38","161.123.217.14","161.123.217.187","161.123.194.107","161.123.194.18","161.123.217.135","161.123.217.62","119.13.233.220","212.70.4.26","188.68.3.77","161.123.212.169","94.139.41.175","185.221.221.183","43.228.239.72","43.228.239.90","43.228.239.24","43.228.239.80","43.228.238.97","43.228.239.46","43.228.238.170","43.228.238.55","119.13.225.29","188.68.3.163","161.123.217.37","161.123.210.111","161.123.210.86","43.228.238.192","43.228.239.85","119.13.235.232","161.123.217.252","43.228.238.203","43.228.238.213","92.118.68.190","161.123.149.178","119.13.233.30","121.91.177.211","119.13.227.137","103.252.110.15","94.176.218.66","161.123.142.89","161.123.119.123","161.123.118.226","161.123.141.129","92.118.68.55","212.70.7.138","43.228.238.94","89.184.196.138","66.118.56.207","161.123.94.144","43.228.239.209","43.228.239.172","92.118.68.39","161.123.210.196","119.13.237.40","119.13.225.239","121.91.180.148","43.228.239.250","43.228.238.117","77.95.119.17","121.91.185.204","43.228.239.109","43.228.239.142","43.228.239.226","43.228.239.239","185.243.109.155","31.14.236.250","161.123.140.148","43.228.239.56","43.228.239.197","43.228.238.135","119.13.239.143","212.70.7.140","89.184.214.217","43.228.238.99","89.184.197.133","103.84.120.6","43.228.239.152","43.228.238.93","43.228.239.173","43.228.239.156","119.13.231.88","89.184.194.219","119.13.228.181","103.84.120.165","119.13.225.121","119.13.237.138","161.123.94.178","119.13.236.38","161.123.217.14","161.123.217.187","161.123.194.107","161.123.194.18","161.123.217.135","161.123.217.62","119.13.233.220","212.70.4.26","188.68.3.77","161.123.212.169","94.139.41.175","185.221.221.183","43.228.239.72","43.228.239.90","43.228.239.24","43.228.239.80","43.228.238.97","43.228.239.46","43.228.238.170","43.228.238.55","119.13.225.29","188.68.3.163","161.123.217.37","161.123.210.111","161.123.210.86","43.228.238.192","43.228.239.85","119.13.235.232","161.123.217.252","43.228.238.203","43.228.238.213","92.118.68.190","161.123.149.178","119.13.233.30","121.91.177.211","119.13.227.137","103.252.110.15","94.176.218.66","161.123.142.89","161.123.119.123","161.123.118.226","161.123.141.129","92.118.68.55","212.70.7.138","43.228.238.94","89.184.196.138","66.118.56.207","161.123.94.144","43.228.239.209","43.228.239.172","92.118.68.39","161.123.210.196","119.13.237.40","119.13.225.239","121.91.180.148","43.228.239.250","43.228.238.117","77.95.119.17","121.91.185.204","43.228.239.109","43.228.239.142","43.228.239.226","43.228.239.239","185.243.109.155","31.14.236.250","161.123.140.148","43.228.239.56","43.228.239.197","43.228.238.135","119.13.239.143","103.119.111.46"
                "43.228.238.124", "43.228.239.29", "43.228.238.99", "43.228.239.248", "43.228.239.106", "43.228.238.181"
            ]

            random_ip = random.choice(ip_list)
            print(f'BROWSER INSTANCE AT IP {random_ip}')
            auth_proxy = SeleniumAuthenticatedProxy(
                f"http://brd-customer-hl_51d61a6d-zone-datacenter_proxy2-ip-{random_ip}:i5ugcf52lxuw@brd.superproxy.io:33335"
            )
            
            auth_proxy.enrich_chrome_options(config)
            browser = zendriver.Browser(config)
            try:
                await browser.start()
            except Exception as e:
                print(f"[ERROR] Failed to start zendriver browser: {e}")
                browser = None
                raise
    return browser

# ----------------------------
# Startup / Shutdown
# ----------------------------
@app.before_serving
async def startup():
    global opened_tabs_count
    global closed_tabs_count
    global tab_error

    print("Starting browser on server startup...")
    try:
        os.system('clear')
        await get_browser()
        # start cleanup background task: runs cleanup pass repeatedly
        asyncio.create_task(cleanup_loop())
        opened_tabs_count = 0
        closed_tabs_count = 0
        tab_error = 0
        print("Browser initialized successfully")
    except Exception as e:
        print(f"Error initializing browser: {e}")

@app.after_serving
async def shutdown():
    global browser
    if browser:
        print("Closing browser...")
        try:
            await browser.stop()
            browser = None
            print("Browser closed successfully")
        except Exception as e:
            print(f"Error closing browser: {e}")

# ----------------------------
# Turnstile helper
# ----------------------------
class Turnstile:
    def __init__(self, url: str, tab_id: int = None):
        self.token = None
        self.config = None
        self.loading = 0
        self.cf_cookie: Optional[str] = None
        self.color = random.choice(colors)
        self.future: asyncio.Future | None = None
        self.url = url
        self.tab_id = tab_id or random.randint(1000, 9999)
        self.task_id = global_progress.add_task(f"[cyan][{self.tab_id}] {url}", total=100)

    def update_progress(self, step=25):
        try:
            global_progress.update(self.task_id, advance=step)
        except Exception:
            pass

    def set_cookie(self, cf_clearace: str):
        self.cf_cookie = cf_clearace
        self.stop_progress()
        if self.cf_cookie:
            print(f"\033[38;5;{random.randint(1, 256)}m{self.cf_cookie[:60]}: \033[0m{self.url}")

    def mark_failed(self):
        self.stop_progress()
        print(f"\033[38;5;196mFailed to solve: \033[0m{self.url}")

    def stop_progress(self):
        try:
            global_progress.update(self.task_id, completed=100)
            global_progress.remove_task(self.task_id)
        except KeyError:
            pass
        except Exception:
            pass

# ----------------------------
# Tab wrapper
# ----------------------------
class TurnstileSolver:
    def __init__(self, browser, url, proxy=None, turnstile: Turnstile = None):
        self.browser = browser
        self.url = url
        self.proxy = proxy
        self.turnstile = turnstile
        self.tab = None
        self.cf_cookie = None
        self._opened_time = None

    async def __aenter__(self):
        global opened_tabs_count
        await window_limit.acquire()  # tunggu slot kosong kalau sudah 4
        try:
            self.tab = await self.browser.get(new_window=True)
            await self.tab.send(zendriver.cdp.page.bring_to_front())

            # mark last_used immediately
            try:
                setattr(self.tab, "created_at", time.time())
                setattr(self.tab, "last_used", time.time())
            except Exception:
                pass

            self._opened_time = time.time()
            opened_tabs_count += 1
            print(f"[DEBUG] Opened tab {id(self.tab)} for {self.url} (opened_count={opened_tabs_count})")

            # Assign tab_id ke Turnstile dan update progress bar
            if self.turnstile:
                self.turnstile.tab_id = id(self.tab)
                global_progress.update(
                    self.turnstile.task_id,
                    description=f"[cyan][{self.turnstile.tab_id}] {self.url}"
                )

            # bring to front (safe)
            try:
                await self.tab.send(zendriver.cdp.page.bring_to_front())
            except Exception:
                pass

            return self
        except Exception as e:
            # on failure to open tab, release semaphore immediately
            window_limit.release()
            print(f"[ERROR] Failed to open tab for {self.url}: {e}")
            raise

    async def __aexit__(self, exc_type, exc, tb):
        try:
            await self.safe_close()
        finally:
            try:
                window_limit.release()  # bebaskan slot
            except Exception:
                pass

    async def safe_close(self):
        """
        Safe close a tab (idempotent). Will not raise if tab already closed or None.
        Also tries to remove fetch handler if possible.
        """
        global closed_tabs_count
        try:
            if self.tab:
                # try to remove handler reference (best-effort)
                try:
                    handler = getattr(self.tab, "_fetch_handler", None)
                    if handler and hasattr(self.tab, "remove_handler"):
                        try:
                            self.tab.remove_handler(fetch.RequestPaused, handler)
                        except Exception:
                            pass
                except Exception:
                    pass

                # some tab objects might have 'closed' attribute, some might raise on access
                is_closed = False
                try:
                    is_closed = getattr(self.tab, "closed", False)
                except Exception:
                    is_closed = False

                if not is_closed:
                    try:
                        await self.tab.close()
                        closed_tabs_count += 1
                        print(f"[DEBUG] Closed tab {id(self.tab)} for {self.url} (closed_count={closed_tabs_count})")
                    except websockets.exceptions.ConnectionClosedError:
                        print(f"[DEBUG] Tab {id(self.tab)} already closed (WebSocket lost)")
                    except Exception as e:
                        print(f"[DEBUG] Error closing tab {id(self.tab)}: {e}")
                else:
                    print(f"[DEBUG] Tab {id(self.tab)} already marked closed for {self.url}")
        except Exception as e:
            print(f"[DEBUG] Unexpected error in safe_close for {self.url}: {e}")
        finally:
            if self.turnstile:
                try:
                    self.turnstile.stop_progress()
                except Exception:
                    pass

    async def solve(self):
        await setup_full_fetch_interception(
            self.tab, target_domain=[urlparse(self.url).netloc], proxy=self.proxy, turnstile=self.turnstile
        )
        await set_user_agent_metadata(self.tab)

        # open the page and mark tab as used
        await self.tab.get(self.url)
        try:
            setattr(self.tab, "last_used", time.time())
        except Exception:
            pass

        self.cf_cookie = await solve_challenge(self.tab, self.turnstile)

        # update last_used after challenge
        try:
            setattr(self.tab, "last_used", time.time())
        except Exception:
            pass

        return self.cf_cookie

# ----------------------------
# Fetch interception
# ----------------------------
async def setup_full_fetch_interception(tab, target_domain, proxy=None, turnstile: Turnstile = None):
    async def fetch_request_handler(event: fetch.RequestPaused):
        global tab_error
        req = event.request
        url = req.url
        host = (urlparse(url).hostname or "").lower()
        method = req.method
        headers = req.headers or {}
        post_data = req.post_data

        # mark tab activity
        try:
            setattr(tab, "last_used", time.time())
        except Exception:
            pass

        # if a cookie already set to empty string => mean fail; continue or fail accordingly
        if turnstile and turnstile.cf_cookie is not None:
            if turnstile.cf_cookie == "":
                await tab.send(fetch.continue_request(request_id=event.request_id))
                turnstile.update_progress(100)
                return
            else:
                await tab.send(fetch.fail_request(
                    request_id=event.request_id,
                    error_reason=network.ErrorReason.FAILED
                ))
                turnstile.update_progress(100)
                return

        if any(host.endswith(d) for d in target_domain):
            pass
        elif 'cloudflare' in str(host):
            await tab.send(fetch.continue_request(request_id=event.request_id))
            return
        else:
            await tab.send(fetch.fail_request(
                request_id=event.request_id,
                error_reason=network.ErrorReason.FAILED
            ))
            return

        url_ignore = [".ico", '.png', '.jpg', '.css', 'detected', '/jsd/', 'google', 'googleapis.com']
        if any(sub in url for sub in url_ignore):
            await tab.send(fetch.fail_request(
                request_id=event.request_id,
                error_reason=network.ErrorReason.FAILED
            ))
            return

        max_retries = 3
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=10, proxy=proxy, verify=False) as client:
                    resp = await client.request(method=method, url=url, headers=headers, data=post_data)

                if resp.status_code == 200:
                    if turnstile:
                        turnstile.loading += 25
                        turnstile.update_progress(25)

                try:
                    if resp.headers.get("set-cookie"):
                        turnstile.cf_cookie = (resp.cookies.get("cf_clearance") or client.cookies.get("cf_clearance"))
                        resp.headers.pop('set-cookie', None)
                        if 'bitcotasks.com' in url:
                                tab_error = 0
                
                except Exception:
                    pass

                body_b64 = base64.b64encode(resp.content).decode("utf-8")
                binary_headers = "\0".join(f"{k}: {v}" for k, v in resp.headers.items() if k.lower() != "set-cookie")
                binary_headers_b64 = base64.b64encode(binary_headers.encode()).decode()

                await tab.send(fetch.fulfill_request(
                    request_id=event.request_id,
                    response_code=resp.status_code,
                    binary_response_headers=binary_headers_b64,
                    body=body_b64
                ))
                # mark activity after successful fulfill
                try:
                    setattr(tab, "last_used", time.time())
                except Exception:
                    pass
                return

            except Exception as e:
                # retry logic
                if attempt < max_retries - 1:
                    await asyncio.sleep(0.2)
                    continue
                else:
                    # mark as failed and allow the solver to handle it
                    if turnstile:
                        turnstile.cf_cookie = ""
                        if turnstile.future and not turnstile.future.done():
                            try:
                                # set empty string result so solver loop can proceed
                                turnstile.future.set_result(turnstile.cf_cookie)
                            except Exception:
                                pass

                    try:
                        await tab.send(fetch.continue_request(request_id=event.request_id))
                        return
                    except Exception:
                        return

    try:
        await tab.send(fetch.enable(
            patterns=[RequestPattern(url_pattern="*")],
            handle_auth_requests=True
        ))
        tab.add_handler(fetch.RequestPaused, fetch_request_handler)
        # store handler reference on tab (best-effort) so we can try to remove it later
        try:
            setattr(tab, "_fetch_handler", fetch_request_handler)
        except Exception:
            pass
    except Exception as e:
        print(f"[ERROR] Failed to enable fetch interception: {e}")
        raise

# ----------------------------
# Solve challenge
# ----------------------------
async def solve_challenge(tab, turnstile: Turnstile):
    try:
        while (turnstile.cf_cookie is None):
            try:
                widget_input = await tab.find("input")
            except Exception:
                await asyncio.sleep(0.25)
                continue

            if widget_input is None:
                await asyncio.sleep(0.25)
                continue

            if widget_input.parent is None or not getattr(widget_input.parent, "shadow_roots", []):
                await asyncio.sleep(0.25)
                continue

            challenge = Element(
                widget_input.parent.shadow_roots[0],
                tab,
                widget_input.parent.tree,
            )

            challenge = challenge.children[0]

            if (
                isinstance(challenge, Element)
                and "display: none;" not in (challenge.attrs.get("style", "") if hasattr(challenge, "attrs") else "")
            ):
                await asyncio.sleep(1)

                try:
                    await challenge.get_position()
                except Exception:
                    continue

                try:
                    await challenge.mouse_click()
                except Exception:
                    # sometimes click fails, loop again
                    continue
    except Exception:
        # swallow - we'll return whatever cf_cookie is (maybe None)
        pass

    return turnstile.cf_cookie

# ----------------------------
# User agent metadata
# ----------------------------
async def set_user_agent_metadata(tab) -> None:
    metadata = UserAgentMetadata(
        architecture="x86",
        bitness="64",
        brands=[
            UserAgentBrandVersion(brand="Not)A;Brand", version="8"),
            UserAgentBrandVersion(brand="Chromium", version=str(139)),
            UserAgentBrandVersion(brand="Google Chrome", version=str(139)),
        ],
        full_version_list=[
            UserAgentBrandVersion(brand="Not)A;Brand", version="8"),
            UserAgentBrandVersion(brand="Chromium", version=str(139)),
            UserAgentBrandVersion(brand="Google Chrome", version=str(139)),
        ],
        mobile=False,
        model="",
        platform='Windows',
        platform_version="10",
        full_version='135.0.0',
        wow64=False,
    )

    try:
        tab.feed_cdp(
            network.set_user_agent_override(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36",
                user_agent_metadata=metadata
            )
        )
    except Exception:
        pass

# ----------------------------
# Utils: semaphore status & cleanup
# ----------------------------
def get_semaphore_status():
    """
    Returns: total_slots, in_use, waiting
    Note: uses internal _value and _waiters of asyncio.Semaphore
    """
    try:
        available = window_limit._value
        waiting = len(getattr(window_limit, "_waiters", []))
        total = available + waiting
        in_use = total - available
        return {
            "total_slots": total,
            "available": available,
            "in_use": in_use,
            "waiting": waiting
        }
    except Exception:
        # fallback: assume configured size 4
        return {"total_slots": 4, "available": None, "in_use": None, "waiting": None}

async def cleanup_tabs():
    """
    Single-pass cleanup. If it closes a tab that has an active request future,
    fulfill that future with a HTTP 500 Response so the client receives 500.
    """
    global closed_tabs_count
    global tab_error
    global active_requests
    try:
        if browser:
            now = time.time()
            # iterate over a copy of tabs/pages
            for t in list(browser.tabs):
                created_at = getattr(t, "created_at", None)
                last_used = getattr(t, "last_used", None)
                tab_id = id(t)

                # Tutup tab kalau sudah hidup >60 detik
                if created_at and (now - created_at > 60):
                    try:
                        await t.close()
                    except Exception:
                        pass
                    print(f"{Fore.YELLOW}[CLEANUP] Closed expire tab {tab_id} error tab={tab_error}{Style.RESET_ALL}")
                    tab_error += 1
                    closed_tabs_count += 1

                    # If there is an active future for this tab -> set 500
                    fut = active_requests.pop(tab_id, None)
                    if fut and not fut.done():
                        try:
                            fut.set_result(Response("Internal Server Error (tab closed by cleanup)", status=500))
                        except Exception:
                            pass
                    continue

                # Tutup tab kalau idle >60 detik
                if last_used and (now - last_used > 60):
                    try:
                        await t.close()
                    except Exception:
                        pass
                    tab_error += 1
                    closed_tabs_count += 1
                    print(f"{Fore.YELLOW}[CLEANUP] Closed idle tab {tab_id} error tab={tab_error} {Style.RESET_ALL}")

                    fut = active_requests.pop(tab_id, None)
                    if fut and not fut.done():
                        try:
                            fut.set_result(Response("Internal Server Error (tab closed by cleanup)", status=500))
                        except Exception:
                            pass

    except Exception as e:
        print(f"[CLEANUP ERROR] {e}")

async def cleanup_loop():
    """
    Background loop to perform periodic cleanup. Runs forever.
    """
    while True:
        try:
            await cleanup_tabs()
        except Exception as e:
            print(f"[CLEANUP LOOP ERROR] {e}")
        await asyncio.sleep(5)  # adjust interval as needed

# ----------------------------
# Solve endpoint
# ----------------------------
@app.route("/solve")
async def solve():
    # run a quick cleanup pass before handling (keeps behavior similar to original)
    await cleanup_tabs()

    global opened_tabs_count
    global closed_tabs_count
    global limit_done
    global tab_error
    global active_requests
    global browser
    open_tabs_len = len(list(getattr(browser, "tabs", [])))

    
    url = request.args.get("url")
    proxy = request.args.get("proxy")
    if not url:
        return jsonify({"error": "Missing url parameter"}), 400

    stats = get_semaphore_status()
    waiting = stats.get("waiting")

    # throttle logic (kept from original)
    if tab_error > 2 or browser is None:
        if open_tabs_len == 1:
            await shutdown()
            await startup()
        return Response("Internal Server Error", status=429)

    if open_tabs_len > 4:
        return Response("Internal Server Error", status=429)

    if opened_tabs_count >= limit_done and closed_tabs_count >= limit_done:
        return Response("Internal Server Error", status=429)

    turnstile = Turnstile(url)

    browser_instance = await get_browser()
    solver = TurnstileSolver(browser_instance, url, proxy, turnstile)

    # Create a future that cleanup or fetch handler can complete
    loop = asyncio.get_event_loop()
    request_future = loop.create_future()

    try:
        # use async context manager to automatically acquire/release semaphore
        async with solver:
            # register future based on tab id
            try:
                tab_id = id(solver.tab)
                active_requests[tab_id] = request_future
                turnstile.future = request_future
            except Exception:
                pass

            # Run solver.solve() as a task so we can race it against cleanup (via request_future)
            solve_task = asyncio.create_task(solver.solve())

            # wait for first to complete: either solver finished, cleanup set request_future, or timeout
            done, pending = await asyncio.wait(
                {solve_task, request_future},
                return_when=asyncio.FIRST_COMPLETED,
                timeout=90
            )

            # if request_future completed first (likely from cleanup) -> return its value
            if request_future in done:
                try:
                    result = request_future.result()
                except Exception as e:
                    # future completed with exception
                    print(f"[DEBUG] request_future exception: {e}")
                    # ensure solve task cancelled
                    if not solve_task.done():
                        solve_task.cancel()
                    if (waiting == 0 or waiting is None) and open_tabs_len == 1:
                        print("[INFO] Restarting browser after heavy usage...")
                        try:
                            await shutdown()
                            await startup()
                        except Exception as e:
                            print(f"[WARN] Error stopping/starting browser: {e}")
                    
                    return Response("Internal Server Error", status=500)

                # if the future result is a Response object (we set it that way in cleanup)
                if isinstance(result, Response):
                    # cancel solver if still running
                    if not solve_task.done():
                        solve_task.cancel()
                    return result
                else:
                    # future might contain plain cf_clearance (string)
                    cf_clearance = result
                    if cf_clearance and len(str(cf_clearance)) > 0:
                        return Response(str(cf_clearance), content_type="text/plain; charset=utf-8")
                    else:
                        return Response('', content_type="text/plain; charset=utf-8")

            # else if solve_task completed first -> gather its result
            if solve_task in done:
                try:
                    cf_clearance = await solve_task
                except asyncio.CancelledError:
                    return Response("Internal Server Error", status=500)
                except Exception as e:
                    print(f"[DEBUG] Exception in solve_task: {e}")
                    turnstile.mark_failed()
                    return Response('', content_type="text/plain; charset=utf-8")

                domain = urlparse(url).netloc

                # set the future result for completeness (if not already done)
                try:
                    if request_future and not request_future.done():
                        request_future.set_result(cf_clearance)
                except Exception:
                    pass

                if cf_clearance and len(str(cf_clearance)) > 100:
                    print(f"\033[38;5;{random.randint(1, 256)}m{cf_clearance[:60]}: \033[0m{domain}")
                    return Response(cf_clearance, content_type="text/plain; charset=utf-8")
                else:
                    turnstile.mark_failed()
                    return Response('', content_type="text/plain; charset=utf-8")

            # if neither completed (timeout)
            # cancel solve task if still running
            try:
                if not solve_task.done():
                    solve_task.cancel()
            except Exception:
                pass
            print("[DEBUG] Request timed out waiting for solve or cleanup")
            turnstile.mark_failed()
            return Response('', content_type="text/plain; charset=utf-8")

    except asyncio.TimeoutError:
        print("[DEBUG] Client timeout")
        turnstile.mark_failed()
        return Response('', content_type="text/plain; charset=utf-8")

    except Exception as e:
        print(f"[DEBUG] Exception: {e}")
        turnstile.mark_failed()
        return Response('', content_type="text/plain; charset=utf-8")

    finally:
        # pastikan tab selalu ditutup walau terjadi timeout atau error
        try:
            await solver.safe_close()
        except Exception:
            pass
        # pastikan progress task dihapus
        try:
            turnstile.stop_progress()
            get_semaphore = get_semaphore_status()
            waiting = get_semaphore.get("waiting")
            # jika sudah banyak buka/tutup dan tidak ada waiting, restart browser (best-effort)
            try:
                open_tabs_len = len(list(getattr(browser, "tabs", [])))
            except Exception:
                try:
                    open_tabs_len = len(list(getattr(browser, "_pages", [])))
                except Exception:
                    open_tabs_len = None

            if opened_tabs_count >= limit_done and closed_tabs_count >= limit_done and (waiting == 0 or waiting is None) and open_tabs_len == 1:
                print("[INFO] Restarting browser after heavy usage...")
                try:
                    await shutdown()
                    await startup()
                except Exception as e:
                    print(f"[WARN] Error stopping/starting browser: {e}")

            elif open_tabs_len == 1 and (waiting == 0 or waiting is None) and tab_error > 9:
                print("[INFO] Restarting browser after heavy usage...")
                try:
                    await shutdown()
                    await startup()
                except Exception as e:
                    print(f"[WARN] Error stopping/starting browser: {e}")

            # cleanup active_requests mapping for this tab if still present
            try:
                tab_id = None
                try:
                    tab_id = id(solver.tab)
                except Exception:
                    tab_id = None
                if tab_id and tab_id in active_requests:
                    # If future still exists and not done, set to generic 500 to avoid leaking
                    fut = active_requests.pop(tab_id, None)
                    if fut and not fut.done():
                        try:
                            fut.set_result(Response("Internal Server Error (final cleanup)", status=500))
                        except Exception:
                            pass
            
            except Exception:
                pass
        except Exception:
            # defensive fallback
            pass

# ----------------------------
# Status endpoint
# ----------------------------
@app.route("/status")
async def status():
    stat = get_semaphore_status()
    # try to get number of open tabs if possible
    open_tabs = None
    try:
        if browser:
            try:
                open_tabs = len(list(getattr(browser, "tabs", [])))
            except Exception:
                try:
                    open_tabs = len(list(getattr(browser, "_pages", [])))
                except Exception:
                    open_tabs = None
    except Exception:
        open_tabs = None

    return jsonify({
        "total_slots": stat.get("total_slots"),
        "available": stat.get("available"),
        "in_use": stat.get("in_use"),
        "waiting": stat.get("waiting"),
        "open_tabs": open_tabs,
        "opened_tabs_count": opened_tabs_count,
        "closed_tabs_count": closed_tabs_count,
        "tab_error": tab_error
    })

# ----------------------------
# Run server
# ----------------------------
if __name__ == "__main__":
    # Use hypercorn/uvloop as you prefer in production; here use Quart builtin runner for simplicity
    app.run(host="0.0.0.0", port=8090)





















