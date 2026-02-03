import os
import re
import sys
import time
import logging
import html
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException
import requests
from datetime import datetime

# 在GitHub Actions或Docker环境中使用webdriver-manager
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def _ensure_utf8_output():
    try:
        if sys.platform == 'win32':
            import ctypes
            try:
                kernel32 = ctypes.windll.kernel32
                kernel32.SetConsoleOutputCP(65001)
            except Exception:
                pass
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

_ensure_utf8_output()

class LeaflowAutoCheckin:
    def __init__(self, email, password):
        self.email = email
        self.password = password
        self.telegram_bot_token = os.getenv('TELEGRAM_BOT_TOKEN', '')
        self.telegram_chat_id = os.getenv('TELEGRAM_CHAT_ID', '')
        self.checkin_urls = self._load_checkin_urls()
        
        if not self.email or not self.password:
            raise ValueError("邮箱和密码不能为空")
        
        self.driver = None
        self.setup_driver()

    def setup_driver(self):
        """设置Chrome驱动选项"""
        logger.info(f"Checking environment: GITHUB_ACTIONS={os.getenv('GITHUB_ACTIONS')}, RUNNING_IN_DOCKER={os.getenv('RUNNING_IN_DOCKER')}")
        
        chrome_options = Options()
        chrome_options.page_load_strategy = "eager"
        chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        chrome_options.add_argument('--lang=zh-CN')
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        
        if os.getenv('GITHUB_ACTIONS') or os.getenv('RUNNING_IN_DOCKER'):
            logger.info("Running in headless mode (CI/Docker)")
            chrome_options.add_argument('--headless=new')
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            chrome_options.add_argument('--disable-gpu')
            chrome_options.add_argument('--window-size=1920,1080')
            
            try:
                system_chromedriver = os.getenv('CHROMEDRIVER_PATH')
                system_chrome_bin = os.getenv('CHROME_BIN')

                if system_chrome_bin:
                    logger.info(f"Setting Chrome binary location: {system_chrome_bin}")
                    chrome_options.binary_location = system_chrome_bin

                if system_chromedriver and os.path.exists(system_chromedriver):
                    logger.info(f"Using system chromedriver at {system_chromedriver}")
                    service = Service(system_chromedriver)
                else:
                    logger.info("Using webdriver-manager to download chromedriver...")
                    service = Service(ChromeDriverManager().install())
                
                self.driver = webdriver.Chrome(service=service, options=chrome_options)
                logger.info("ChromeDriver initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize ChromeDriver: {e}")
                raise
        else:
            # 兼容沙盒环境，即使是非CI/Docker环境也使用headless和no-sandbox
            chrome_options.add_argument('--headless=new')
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            chrome_options.add_argument('--disable-gpu')
            chrome_options.add_argument('--window-size=1920,1080')
            
            try:
                self.driver = webdriver.Chrome(options=chrome_options)
            except Exception:
                logger.info("Direct ChromeDriver init failed, trying webdriver-manager...")
                try:
                    service = Service(ChromeDriverManager().install())
                    self.driver = webdriver.Chrome(service=service, options=chrome_options)
                except Exception as e:
                    logger.error(f"Failed to initialize ChromeDriver: {e}")
                    raise
        
        try:
            self.driver.set_page_load_timeout(60)
            self.driver.set_script_timeout(30)
        except Exception:
            pass

        self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
    def _load_checkin_urls(self):
        """Load check-in URLs from env, fallback to default."""
        urls = []
        raw_urls = os.getenv('LEAFLOW_CHECKIN_URLS', '').strip()
        raw_url = os.getenv('LEAFLOW_CHECKIN_URL', '').strip()

        if raw_urls:
            urls.extend([u.strip() for u in raw_urls.split(',') if u.strip()])
        if raw_url:
            urls.append(raw_url)

        if not urls:
            urls = ["https://checkin.leaflow.net"]

        deduped = []
        seen = set()
        for url in urls:
            if url not in seen:
                deduped.append(url)
                seen.add(url)
        return deduped

    def _switch_to_new_window(self, old_handles, timeout=10):
        """Switch to new window if one appears."""
        end_time = time.time() + timeout
        while time.time() < end_time:
            handles = self.driver.window_handles
            if len(handles) > len(old_handles):
                new_handles = [h for h in handles if h not in old_handles]
                if new_handles:
                    self.driver.switch_to.window(new_handles[-1])
                    return True
            time.sleep(0.5)
        return False

    def _switch_to_iframe_with_keywords(self, keywords, timeout=10):
        """Switch into iframe that contains any keyword text."""
        end_time = time.time() + timeout
        while time.time() < end_time:
            iframes = self.driver.find_elements(By.TAG_NAME, "iframe")
            for iframe in iframes:
                matched = False
                try:
                    self.driver.switch_to.frame(iframe)
                    body_text = ""
                    try:
                        body_text = self.driver.find_element(By.TAG_NAME, "body").text
                    except Exception:
                        pass
                    if any(keyword in body_text for keyword in keywords):
                        matched = True
                        return True
                except Exception:
                    pass
                finally:
                    if not matched:
                        self.driver.switch_to.default_content()
            time.sleep(0.5)
        return False

    def _click_element(self, element):
        try:
            try:
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
            except Exception:
                pass
            element.click()
            return True
        except Exception:
            try:
                self.driver.execute_script("arguments[0].click();", element)
                return True
            except Exception:
                return False

    def _js_click_by_text(self, texts, timeout=10):
        """Find element by text (including shadow DOM) and click via JS."""
        script = """
        const texts = arguments[0] || [];
        function isVisible(el) {
          if (!el || !el.getBoundingClientRect) return false;
          const rect = el.getBoundingClientRect();
          if (rect.width === 0 || rect.height === 0) return false;
          const style = window.getComputedStyle(el);
          if (!style) return false;
          return style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0';
        }
        function isClickable(el) {
          if (!el) return false;
          const tag = (el.tagName || '').toLowerCase();
          if (tag === 'button' || tag === 'a') return true;
          const role = el.getAttribute && el.getAttribute('role');
          if (role === 'button') return true;
          if (el.onclick || el.getAttribute('onclick')) return true;
          return false;
        }
        function closestClickable(el) {
          let cur = el;
          while (cur && cur !== document.body) {
            if (isClickable(cur)) return cur;
            cur = cur.parentElement;
          }
          return el;
        }
        function iterNodes(root) {
          const out = [];
          const queue = [root];
          while (queue.length) {
            const node = queue.shift();
            if (!node) continue;
            if (node.nodeType === 1) { // ELEMENT_NODE
              out.push(node);
              if (node.shadowRoot) queue.push(node.shadowRoot);
              if (node.tagName && node.tagName.toLowerCase() === 'iframe') {
                try {
                  if (node.contentDocument) queue.push(node.contentDocument);
                } catch (e) {}
              }
              if (node.children) {
                for (const child of node.children) queue.push(child);
              }
            } else if (node.nodeType === 11) { // DOCUMENT_FRAGMENT
              if (node.children) {
                for (const child of node.children) queue.push(child);
              }
            } else if (node.nodeType === 9) { // DOCUMENT
              if (node.body) queue.push(node.body);
            }
          }
          return out;
        }
        function tryClick(doc) {
          const nodes = iterNodes(doc);
          for (const el of nodes) {
            if (!isVisible(el)) continue;
            const text = (el.innerText || el.textContent || '').trim();
            if (!text) continue;
            for (const t of texts) {
              if (text === t || (text.includes(t) && text.length < t.length + 10)) {
                const target = closestClickable(el);
                try { target.scrollIntoView({block: 'center'}); } catch (e) {}
                try { target.click(); } catch (e) {
                  target.dispatchEvent(new MouseEvent('click', {bubbles: true}));
                }
                return true;
              }
            }
          }
          return false;
        }
        return tryClick(document);
        """
        end_time = time.time() + timeout
        while time.time() < end_time:
            try:
                if self.driver.execute_script(script, texts):
                    return True
            except Exception:
                pass
            time.sleep(1)
        return False

    def open_checkin_from_workspaces(self):
        """Open check-in modal from workspaces page."""
        try:
            current_url = ""
            try:
                current_url = self.driver.current_url or ""
            except Exception:
                current_url = ""

            if "https://leaflow.net/workspaces" not in current_url:
                self.safe_get("https://leaflow.net/workspaces", max_retries=2, wait_between=3)
            WebDriverWait(self.driver, 20).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            time.sleep(2)

            # 点击“签到试用”按钮
            click_selectors = [
                "//button[contains(., '签到试用')]",
                "//*[contains(text(), '签到试用')]",
                "//*[contains(normalize-space(.), '签到试用')]",
                "//button[contains(., '签到')]",
                "//*[contains(text(), '签到')]"
            ]

            target_btn = None
            end_time = time.time() + 15
            while time.time() < end_time and not target_btn:
                for selector in click_selectors:
                    try:
                        elements = self.driver.find_elements(By.XPATH, selector)
                        for element in elements:
                            if element.is_displayed():
                                target_btn = element
                                break
                        if target_btn:
                            break
                    except Exception:
                        continue
                if not target_btn:
                    time.sleep(0.5)

            if not target_btn:
                logger.warning("未找到工作空间中的签到入口按钮，尝试使用 JS 模糊搜索...")
                fallback_texts = ["签到试用", "每日签到", "立即签到"] 
                if self._js_click_by_text(fallback_texts, timeout=8):
                    target_btn = True

            if not target_btn:
                logger.warning("无法找到任何签到入口按钮")
                return False

            old_handles = set(self.driver.window_handles)
            if target_btn is not True:
                logger.info(f"点击签到入口: {target_btn.text if hasattr(target_btn, 'text') else 'Unknown'}")
                if not self._click_element(target_btn):
                    logger.warning("签到入口按钮点击失败，尝试 JS 点击")
                    try:
                        self.driver.execute_script("arguments[0].click();", target_btn)
                    except:
                        pass

            # 点击后，等待“立即签到”按钮出现作为成功标志
            logger.info("已点击签到入口，等待签到弹窗...")
            
            if self._switch_to_new_window(old_handles, timeout=5):
                logger.info("检测到新窗口")
                return True

            checkin_btn_keywords = ["立即签到", "签到"]
            end_time = time.time() + 10
            while time.time() < end_time:
                for keyword in checkin_btn_keywords:
                    try:
                        xpath = f"//button[contains(., '{keyword}')] | //*[contains(text(), '{keyword}') and @role='button']"
                        btns = self.driver.find_elements(By.XPATH, xpath)
                        for btn in btns:
                            if btn.is_displayed():
                                logger.info(f"在当前页面找到签到按钮: {keyword}")
                                return True
                    except:
                        pass
                
                if self._switch_to_iframe_with_keywords(checkin_btn_keywords, timeout=1):
                    logger.info("在 iframe 中找到签到弹窗")
                    return True
                
                time.sleep(1)

            logger.warning("点击签到入口后，未在限定时间内检测到签到弹窗或按钮")
            return False
        except Exception as e:
            logger.warning(f"打开工作空间签到入口失败: {e}")
            return False

    def _stop_page_load(self):
        try:
            self.driver.execute_script("window.stop();")
        except Exception:
            pass

    def _is_driver_timeout(self, message):
        if not message:
            return False
        return ("HTTPConnectionPool" in message or "Read timed out" in message or "read timeout" in message)

    def restart_driver(self):
        try:
            if self.driver:
                self.driver.quit()
        except Exception:
            pass
        self.driver = None
        self.setup_driver()

    def safe_get(self, url, max_retries=2, wait_between=3):
        last_error = None
        for attempt in range(max_retries + 1):
            try:
                self.driver.get(url)
                return True
            except TimeoutException as e:
                last_error = f"TimeoutException: {e}"
                logger.warning(f"Page load timeout for {url} ({attempt + 1}/{max_retries + 1}).")
                self._stop_page_load()
            except WebDriverException as e:
                last_error = str(e)
                logger.warning(f"WebDriver error loading {url} ({attempt + 1}/{max_retries + 1}): {e}")
                self._stop_page_load()
            except Exception as e:
                last_error = str(e)
                logger.warning(f"Page load error for {url} ({attempt + 1}/{max_retries + 1}): {e}")
                self._stop_page_load()

            if attempt < max_retries:
                time.sleep(wait_between)

        raise Exception(f"Failed to load page: {url}. Last error: {last_error}")

    def close_popup(self):
        """关闭初始弹窗"""
        try:
            logger.info("尝试关闭初始弹窗...")
            time.sleep(3)  # 等待弹窗加载
            
            try:
                actions = ActionChains(self.driver)
                actions.move_by_offset(10, 10).click().perform()
                logger.info("已成功关闭弹窗")
                time.sleep(2)
                return True
            except:
                pass
            return False
            
        except Exception as e:
            logger.warning(f"关闭弹窗时出错: {e}")
            return False
    
    def wait_for_element_clickable(self, by, value, timeout=10):
        """等待元素可点击"""
        return WebDriverWait(self.driver, timeout).until(
            EC.element_to_be_clickable((by, value))
        )
    
    def wait_for_element_present(self, by, value, timeout=10):
        """等待元素出现"""
        return WebDriverWait(self.driver, timeout).until(
            EC.presence_of_element_located((by, value))
        )
    
    def login(self):
        """执行登录流程，支持重试机制"""
        cookie_str = os.getenv('LEAFLOW_COOKIE')
        if cookie_str:
            try:
                logger.info("检测到 LEAFLOW_COOKIE，尝试通过 Cookie 登录...")
                self.driver.get("https://leaflow.net")
                time.sleep(2)
                
                for item in cookie_str.split(';'):
                    if '=' in item:
                        name, value = item.strip().split('=', 1)
                        self.driver.add_cookie({'name': name, 'value': value})
                
                self.driver.refresh()
                time.sleep(5)
                
                if "dashboard" in self.driver.current_url or "workspaces" in self.driver.current_url or "login" not in self.driver.current_url:
                    logger.info("Cookie 登录成功")
                    return True
                else:
                    logger.warning("Cookie 登录失败，回退到常规登录")
            except Exception as e:
                logger.warning(f"Cookie 登录出错: {e}")

        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                logger.info(f"开始登录流程，第 {attempt + 1}/{max_retries} 次尝试...")
                
                self.driver.get("https://leaflow.net/login")
                
                WebDriverWait(self.driver, 40).until(
                    EC.presence_of_element_located((By.TAG_NAME, "body"))
                )
                
                time.sleep(5)
        
                self.close_popup()
                
                try:
                    logger.info("查找邮箱输入框...")
                    time.sleep(2)
                    email_selectors = [
                        "input[type='text']",
                        "input[type='email']", 
                        "input[placeholder*='邮箱']",
                        "input[placeholder*='邮件']",
                        "input[placeholder*='email']",
                        "input[name='email']",
                        "input[name='username']"
                    ]
                    
                    email_input = None
                    for selector in email_selectors:
                        try:
                            email_input = self.wait_for_element_clickable(By.CSS_SELECTOR, selector, 5)
                            logger.info(f"找到邮箱输入框")
                            break
                        except:
                            continue
                    
                    if not email_input:
                        raise Exception("找不到邮箱输入框")
                    
                    email_input.clear()
                    email_input.send_keys(self.email)
                    logger.info("邮箱输入完成")
                    time.sleep(2)
                    
                except Exception as e:
                    logger.error(f"输入邮箱时出错: {e}")
                    try:
                        self.driver.execute_script(f"document.querySelector('input[type=\"text\"], input[type=\"email\"]').value = '{self.email}';")
                        logger.info("通过JavaScript设置邮箱")
                        time.sleep(2)
                    except:
                        raise Exception(f"无法输入邮箱: {e}")
                
                try:
                    logger.info("查找密码输入框...")
                    password_input = self.wait_for_element_clickable(
                        By.CSS_SELECTOR, "input[type='password']", 10
                    )
                    
                    password_input.clear()
                    password_input.send_keys(self.password)
                    logger.info("密码输入完成")
                    time.sleep(1)
                    
                except TimeoutException:
                    raise Exception("找不到密码输入框")
                
                # 检查 reCAPTCHA 徽标是否存在
                try:
                    WebDriverWait(self.driver, 5).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, ".grecaptcha-badge"))
                    )
                    logger.info("检测到 reCAPTCHA 徽标，等待其处理...")
                    time.sleep(5) # 给 reCAPTCHA 留出处理时间
                except TimeoutException:
                    logger.info("未检测到 reCAPTCHA 徽标")
                except Exception as e:
                    logger.warning(f"检查 reCAPTCHA 徽标时出错: {e}")

                try:
                    logger.info("查找登录按钮...")
                    login_btn_selectors = [
                        "//button[contains(text(), '登录')]",
                        "//button[contains(text(), 'Login')]",
                        "//button[@type='submit']",
                        "//input[@type='submit']",
                        "button[type='submit']"
                    ]
                    
                    login_btn = None
                    for selector in login_btn_selectors:
                        try:
                            if selector.startswith("//"):
                                login_btn = self.wait_for_element_clickable(By.XPATH, selector, 5)
                            else:
                                login_btn = self.wait_for_element_clickable(By.CSS_SELECTOR, selector, 5)
                            logger.info(f"找到登录按钮")
                            break
                        except:
                            continue
                    
                    if not login_btn:
                        raise Exception("找不到登录按钮")
                    
                    login_btn.click()
                    logger.info("已点击登录按钮")
                    
                except Exception as e:
                    logger.error(f"点击登录按钮失败: {e}")
                    raise Exception(f"点击登录按钮失败: {e}")
                
                try:
                    WebDriverWait(self.driver, 40).until(
                        lambda driver: "dashboard" in driver.current_url or "workspaces" in driver.current_url or "login" not in driver.current_url
                    )
                    
                    current_url = self.driver.current_url
                    if "dashboard" in current_url or "workspaces" in current_url or "login" not in current_url:
                        logger.info(f"登录成功，当前URL: {current_url}")
                        return True
                    else:
                        raise Exception("登录后未跳转到正确页面")
                        
                except TimeoutException:
                    try:
                        error_selectors = [".error", ".alert-danger", "[class*='error']", "[class*='danger']", ".ant-notification-notice-message"]
                        for selector in error_selectors:
                            try:
                                error_msg_element = self.driver.find_element(By.CSS_SELECTOR, selector)
                                if error_msg_element.is_displayed():
                                    error_text = error_msg_element.text
                                    if error_text:
                                        raise Exception(f"登录失败: {error_text}")
                            except:
                                continue
                        # 尝试从页面源码中查找错误信息
                        page_source = self.driver.page_source
                        if "账号或密码错误" in page_source or "无效的凭据" in page_source:
                            raise Exception("登录失败: 账号或密码错误/无效凭据")
                        if "验证码" in page_source:
                            raise Exception("登录失败: 遇到验证码")
                        raise Exception("登录超时，无法确认登录状态")
                    except Exception as e:
                        raise e
                
            except Exception as e:
                logger.warning(f"第 {attempt + 1} 次登录尝试失败: {e}")
                
                if attempt < max_retries - 1:
                    logger.info(f"正在进行第 {attempt + 2} 次重试...")
                    self.driver.refresh()
                    time.sleep(5)
                    continue
                else:
                    raise Exception(f"登录失败，已尝试 {max_retries} 次: {e}")
        
        return False
    
    def get_balance(self):
        """获取当前账号的总余额"""
        try:
            logger.info("获取账号余额...")
            
            self.driver.get("https://leaflow.net/dashboard")
            time.sleep(3)
            
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            
            balance_selectors = [
                "//div[contains(@class, 'flex') and contains(., '余额')]//span",
                "//*[contains(@class, 'balance')]",
                "//*[contains(text(), '¥') or contains(text(), '￥') or contains(text(), '元')]",
                "//button[contains(., '余额')]//span",
                "//span[contains(@class, 'font-medium')]"
            ]
            
            for selector in balance_selectors:
                try:
                    elements = self.driver.find_elements(By.XPATH, selector)
                    for element in elements:
                        text = element.text.strip()
                        if any(char.isdigit() for char in text) and ('¥' in text or '￥' in text or '元' in text):
                            # 提取数字，支持带逗号的千分位
                            clean_text = text.replace(',', '')
                            numbers = re.findall(r'\d+\.?\d*', clean_text)
                            if numbers:
                                balance = numbers[0]
                                logger.info(f"找到余额: {balance}元")
                                return f"{balance}元"
                except:
                    continue
            
            logger.warning("未找到余额信息")
            return "未知"
            
        except Exception as e:
            logger.warning(f"获取余额时出错: {e}")
            return "未知"
    
    def wait_for_checkin_page_loaded(self, max_retries=3, wait_time=20):
        """等待签到页面完全加载，支持重试"""
        for attempt in range(max_retries):
            logger.info(f"等待签到页面加载，尝试 {attempt + 1}/{max_retries}，等待 {wait_time} 秒...")
            time.sleep(wait_time)
            
            try:
                checkin_indicators = [
                    "button.checkin-btn",
                    "//button[contains(text(), '立即签到')]",
                    "//button[contains(text(), '已签到')]",
                    "//button[contains(text(), '已完成')]",
                    "//*[contains(text(), '今日已签到')]",
                    "//*[contains(text(), '每日签到')]",
                    "//*[contains(text(), '签到')]"
                ]
                
                for indicator in checkin_indicators:
                    try:
                        if indicator.startswith("//"):
                            element = WebDriverWait(self.driver, 10).until(
                                EC.presence_of_element_located((By.XPATH, indicator))
                            )
                        else:
                            element = WebDriverWait(self.driver, 10).until(
                                EC.presence_of_element_located((By.CSS_SELECTOR, indicator))
                            )
                        
                        if element.is_displayed():
                            logger.info(f"找到签到页面元素")
                            return True
                    except:
                        continue
                
                logger.warning(f"第 {attempt + 1} 次尝试未找到签到按钮，继续等待...")
                
            except Exception as e:
                logger.warning(f"第 {attempt + 1} 次检查签到页面时出错: {e}")
        
        return False
    
    def find_and_click_checkin_button(self):
        """查找并点击签到按钮 - 处理已签到状态"""
        logger.info("正在查找并点击'立即签到'按钮...")
        
        try:
            time.sleep(2)

            # 0. 优先检查是否已经签到（检查文本"今日已签到"或"已完成"按钮）
            try:
                success_indicators = [
                    "//*[contains(text(), '今日已签到')]",
                    "//button[contains(., '已完成')]",
                    "//div[contains(., '已完成')]"
                ]
                for indicator in success_indicators:
                    elements = self.driver.find_elements(By.XPATH, indicator)
                    for el in elements:
                        if el.is_displayed():
                            logger.info(f"检测到已签到状态 (Indicator: {indicator})")
                            return "already_checked_in"
            except:
                pass
            
            # 尝试处理 iframe 情况
            iframes = self.driver.find_elements(By.TAG_NAME, "iframe")
            if iframes:
                logger.info(f"检测到 {len(iframes)} 个 iframe，尝试在 iframe 中查找按钮")
                
                # 临时降低超时时间，防止在某些 iframe 上卡住太久
                original_timeout = 60
                try:
                    self.driver.set_page_load_timeout(10)
                except:
                    pass

                for i, frame in enumerate(iframes):
                    try:
                        self.driver.switch_to.frame(frame)
                        logger.info(f"已切换到第 {i+1} 个 iframe")
                        # 在 iframe 中尝试物理点击 + JS 混合模式
                        logger.info("尝试在 iframe 中定位'立即签到'按钮...")
                        try:
                            # 1. 尝试 JS 智能定位
                            script = """
                            const texts = ['立即签到', '签到'];
                            const checked_texts = ['已签到', '已完成', '今日已签到'];
                            const nodes = document.querySelectorAll('button, div[role="button"], a[role="button"], .ant-btn');
                            
                            for (const el of nodes) {
                                const text = (el.innerText || '').trim();
                                if (checked_texts.some(t => text.includes(t))) return 'ALREADY_CHECKED_IN';
                                if (texts.some(t => text.includes(t))) return el;
                            }
                            return null;
                            """
                            btn = self.driver.execute_script(script)
                            
                            if btn == 'ALREADY_CHECKED_IN':
                                logger.info("在 iframe 内部检测到已签到状态")
                                self.driver.switch_to.default_content()
                                return "already_checked_in"

                            if btn:
                                logger.info("在 iframe 内部找到按钮，开始物理轰炸...")
                                # 执行 ActionChains 物理点击
                                actions = ActionChains(self.driver)
                                actions.move_to_element(btn).click().perform()
                                time.sleep(0.5)
                                # 补一个 JS 点击
                                self.driver.execute_script("arguments[0].click();", btn)
                                logger.info("iframe 内部物理+JS点击指令已发出")
                                self.driver.switch_to.default_content()
                                return True
                        except Exception as fe:
                            logger.warning(f"iframe 内部点击尝试失败: {fe}")
                        
                        self.driver.switch_to.default_content()
                    except Exception as e:
                        logger.warning(f"处理 iframe {i+1} 时出错: {e}")
                        self.driver.switch_to.default_content()

                # 恢复默认超时
                try:
                    self.driver.set_page_load_timeout(original_timeout)
                except:
                    pass

            priority_selectors = [
                "//button[contains(., '立即签到')]",
                "//div[@role='button' and contains(., '立即签到')]",
                "//*[contains(@class, 'ant-btn') and contains(., '立即签到')]",
                "//*[contains(text(), '立即签到')]",
            ]
            
            secondary_selectors = [
                "button.checkin-btn",
                "//button[contains(., '签到')]",
                "//*[contains(@class, 'ant-btn') and contains(., '签到')]",
                "//*[contains(@class, 'el-button') and contains(., '签到')]",
                "//*[contains(@class, 'MuiButton') and contains(., '签到')]",
                "//div[@role='button' and contains(., '签到')]",
                "//a[@role='button' and contains(., '签到')]",
                "//*[text()='签到']"
            ]
            
            checkin_selectors = priority_selectors + secondary_selectors
            
            for selector in checkin_selectors:
                try:
                    if selector.startswith("//"):
                        elements = self.driver.find_elements(By.XPATH, selector)
                    else:
                        elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    
                    for checkin_btn in elements:
                        if checkin_btn.is_displayed() and checkin_btn.is_enabled():
                            btn_text = checkin_btn.text.strip()
                            try:
                                btn_html = checkin_btn.get_attribute('outerHTML')
                                if len(btn_html) > 100:
                                    btn_html = btn_html[:100] + "..."
                            except:
                                btn_html = "N/A"
                                
                            if "已签到" in btn_text or "已完成" in btn_text:
                                logger.info(f"检测到按钮文本包含'已签到' ({btn_text})，跳过点击")
                                return "already_checked_in"
                            
                            if "试用" in btn_text:
                                logger.info(f"跳过疑似菜单项: {btn_text}")
                                continue

                            logger.info(f"找到签到按钮 (Text: {btn_text}, Selector: {selector})，尝试点击...")
                            
                            try:
                                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", checkin_btn)
                                time.sleep(1)
                            except:
                                pass
                            
                            # 点击前截图
                            self.driver.save_screenshot("before_click.png")
                            logger.info("已保存点击前截图: before_click.png")

                            try:
                                # 获取元素位置和大小
                                location = checkin_btn.location
                                size = checkin_btn.size
                                logger.info(f"按钮物理位置: {location}, 大小: {size}")
                                
                                # 方案 A: 物理中心点点击
                                actions = ActionChains(self.driver)
                                actions.move_to_element(checkin_btn).click().perform()
                                logger.info("已执行中心点物理模拟点击")
                                time.sleep(1)
                                
                                # 方案 B: 多点偏移轰炸 (针对可能的遮挡或特殊监听)
                                offsets = [(0, 0), (5, 5), (-5, -5), (10, 0), (0, 10)]
                                for ox, oy in offsets:
                                    try:
                                        actions = ActionChains(self.driver)
                                        actions.move_to_element_with_offset(checkin_btn, ox, oy).click().perform()
                                        logger.info(f"已执行偏移点击: ({ox}, {oy})")
                                        time.sleep(0.5)
                                    except:
                                        continue
                                        
                                # 方案 C: 强制 JS 派发事件
                                self.driver.execute_script("""
                                    var el = arguments[0];
                                    ['mousedown', 'mouseup', 'click'].forEach(type => {
                                        var ev = new MouseEvent(type, {
                                            view: window,
                                            bubbles: true,
                                            cancelable: true,
                                            buttons: 1
                                        });
                                        el.dispatchEvent(ev);
                                    });
                                """, checkin_btn)
                                logger.info("已执行全套 JS 事件派发")
                                
                            except Exception as e:
                                logger.warning(f"综合点击尝试出错: {e}")
                                try:
                                    self.driver.execute_script("arguments[0].click();", checkin_btn)
                                except:
                                    pass
                            
                            # 点击瞬间截图
                            time.sleep(0.5)
                            self.driver.save_screenshot("after_click_instant.png")
                            logger.info("已保存点击瞬间截图: after_click_instant.png")

                             # 验证点击结果 - 增加循环检查奖励弹窗
                            logger.info("循环检查奖励领取弹窗...")
                            for _ in range(5):
                                reward_btn_texts = ["领取", "确定", "我知道了", "收下", "Confirm", "OK"]
                                if self._js_click_by_text(reward_btn_texts, timeout=2):
                                    logger.info("成功点击奖励领取/确认按钮")
                                    break
                                time.sleep(1)
                            
                            time.sleep(2)
                            
                            # 尝试处理可能出现的“领取”或“确定”按钮
                            logger.info("检查是否有奖励领取弹窗...")
                            reward_btn_texts = ["领取", "确定", "我知道了", "收下", "Confirm", "OK"]
                            if self._js_click_by_text(reward_btn_texts, timeout=5):
                                logger.info("已点击奖励领取/确认按钮")
                                time.sleep(2)
                            
                            try:
                                if not checkin_btn.is_displayed():
                                    logger.info("点击后签到按钮消失，判定为点击成功")
                                    return True
                                
                                new_text = checkin_btn.text.strip()
                                if new_text != btn_text or "已" in new_text or "完成" in new_text:
                                    logger.info(f"点击后按钮文本变为: {new_text}，判定为点击成功")
                                    return True
                                if not checkin_btn.is_enabled():
                                    logger.info("点击后按钮已禁用，判定为点击成功")
                                    return True
                            except Exception:
                                logger.info("点击后元素状态改变，判定为点击成功")
                                return True
                                
                            logger.warning("点击后未检测到按钮状态变化，判定点击未生效")
                            continue
                except Exception as e:
                    # 捕获异常并继续，防止因单个 iframe 错误导致整个循环中断
                    # logger.debug(f"遍历 iframe 时忽略异常: {e}")
                    continue
            
            # 恢复默认超时
            try:
                self.driver.set_page_load_timeout(original_timeout)
            except:
                pass

            logger.info("常规选择器未找到，尝试 JS 智能搜索点击...")
            js_fallback_texts = ["立即签到", "签到"]
            if self._js_click_by_text(js_fallback_texts, timeout=8):
                logger.info("JS 点击成功")
                return True

            logger.error("在当前页面/弹窗中找不到可点击的签到按钮")
            return False
                    
        except Exception as e:
            logger.error(f"查找签到按钮时出错: {e}")
            return False
    
    def _get_balance_value(self):
        """辅助方法：获取数值型余额"""
        try:
            balance_str = self.get_balance()
            if balance_str and balance_str != "未知":
                import re
                match = re.search(r'(\d+\.?\d*)', balance_str)
                if match:
                    return float(match.group(1))
        except Exception:
            pass
        return None

    def checkin(self):
        """执行签到流程"""
        logger.info("开始签到流程...")
        
        # 记录初始余额
        start_balance = self._get_balance_value()
        logger.info(f"签到前余额: {start_balance}")

        logger.info("尝试方案1：主站工作空间弹窗签到")
        if self.open_checkin_from_workspaces():
            logger.info("成功打开签到弹窗，准备点击'立即签到'...")
            checkin_result = self.find_and_click_checkin_button()
            if checkin_result:
                if checkin_result == "already_checked_in":
                    return "今日已签到"
                
                result_msg = self.get_checkin_result()
                
                # 如果未提取到具体金额，尝试通过余额变化计算
                if "获得" not in result_msg and start_balance is not None:
                    # 等待余额更新
                    logger.info("未从弹窗获取到金额，尝试计算余额差值...")
                    time.sleep(3)
                    self.driver.refresh() # 刷新页面以确保余额更新
                    time.sleep(5)
                    
                    end_balance = self._get_balance_value()
                    logger.info(f"签到后余额: {end_balance}")
                    
                    if end_balance is not None and end_balance > start_balance:
                        diff = round(end_balance - start_balance, 2)
                        if diff > 0:
                            return f"签到成功！您获得了 {diff} 元奖励！"
                    else:
                        logger.warning(f"余额未增加: start={start_balance}, end={end_balance}")
                
                if result_msg == "未检测到明确结果":
                    return "签到失败：未检测到奖励，且余额未增加"

                return result_msg
        else:
            logger.warning("方案1失败，尝试备选方案")

        logger.info("尝试方案2：直接访问签到 URL")
        for url in self.checkin_urls:
            try:
                logger.info(f"正在访问签到地址: {url}")
                self.safe_get(url, max_retries=1, wait_between=3)
                
                if self.wait_for_checkin_page_loaded(max_retries=2, wait_time=15):
                    checkin_result = self.find_and_click_checkin_button()
                    if checkin_result:
                        if checkin_result == "already_checked_in":
                            return "今日已签到"
                        
                        result_msg = self.get_checkin_result()
                        
                        if "获得" not in result_msg and start_balance is not None:
                             logger.info("未从弹窗获取到金额，尝试计算余额差值...")
                             time.sleep(3)
                             self.driver.refresh()
                             time.sleep(5)
                             end_balance = self._get_balance_value()
                             logger.info(f"签到后余额: {end_balance}")
                             if end_balance is not None and end_balance > start_balance:
                                 diff = round(end_balance - start_balance, 2)
                                 if diff > 0:
                                     return f"签到成功！您获得了 {diff} 元奖励！"
                             else:
                                logger.warning(f"余额未增加: start={start_balance}, end={end_balance}")
                        
                        if result_msg == "未检测到明确结果":
                            return "签到失败：未检测到奖励，且余额未增加"

                        return result_msg
            except Exception as e:
                logger.warning(f"访问 {url} 失败: {e}")
                continue
        
        raise Exception("所有签到方案均失败")
    
    def get_checkin_result(self):
        """获取签到结果消息"""
        try:
            time.sleep(3)
            
            # 优先查找明确的成功提示元素
            success_selectors = [
                ".alert-success", ".success", ".message", "[class*='success']", 
                "[class*='message']", ".modal-content", ".ant-message", 
                ".el-message", ".toast", ".notification",
                "//div[contains(@class, 'ant-message-notice')]//span",
                "//div[contains(@class, 'el-message__content')]"
            ]
            
            for selector in success_selectors:
                try:
                    if selector.startswith("//"):
                        elements = self.driver.find_elements(By.XPATH, selector)
                    else:
                        elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                        
                    for element in elements:
                        if element.is_displayed():
                            text = element.text.strip()
                            # 尝试从提示文本中提取金额
                            match = re.search(r'获得\s*(\d+\.?\d*)\s*元', text) or \
                                    re.search(r'\+\s*(\d+\.?\d*)\s*元', text) or \
                                    re.search(r'(\d+\.?\d*)\s*元', text)
                            
                            if match and ("签到" in text or "成功" in text or "获得" in text):
                                return f"签到成功！您获得了 {match.group(1)} 元奖励！"
                            
                            if text and ("签到" in text or "成功" in text) and len(text) > 4: 
                                return text
                except:
                    continue
            
            # 如果没找到弹窗，扫描全页面文本
            page_text = self.driver.find_element(By.TAG_NAME, "body").text
            
            # 1. 匹配标准奖励格式
            match = re.search(r'获得\s*(\d+\.?\d*)\s*元', page_text) or \
                    re.search(r'\+\s*(\d+\.?\d*)\s*元', page_text)
            if match:
                return f"签到成功！您获得了 {match.group(1)} 元奖励！"
            
            # 2. 匹配签到记录行
            date_pattern = datetime.now().strftime("%Y-%m-%d")
            lines = page_text.split('\n')
            for line in lines:
                line = line.strip()
                if date_pattern in line and ("+" in line or "元" in line):
                     match = re.search(r'(\d+\.?\d*)\s*元', line) or re.search(r'\+\s*(\d+\.?\d*)', line)
                     if match:
                         return f"签到成功！您获得了 {match.group(1)} 元奖励！"
                     return f"签到成功！({line})"

            # 3. 检查按钮状态
            try:
                checkin_btn = None
                btn_selectors = ["button.checkin-btn", "//button[contains(., '已签到')]"]
                for sel in btn_selectors:
                    try:
                        if sel.startswith("//"):
                            els = self.driver.find_elements(By.XPATH, sel)
                        else:
                            els = self.driver.find_elements(By.CSS_SELECTOR, sel)
                        if els:
                            checkin_btn = els[0]
                            break
                    except: pass
                
                if checkin_btn:
                    if not checkin_btn.is_enabled() or "已签到" in checkin_btn.text:
                        return "签到成功！(已签到)"
            except:
                pass
            
            return "未检测到明确结果"
            
        except Exception as e:
            return f"获取结果出错: {str(e)}"
    
    def run(self):
        """单个账号执行流程"""
        try:
            logger.info(f"开始处理账号")
            
            if self.login():
                result = self.checkin()
                balance = self.get_balance()
                
                logger.info(f"签到结果: {result}, 余额: {balance}")
                return True, result, balance
            else:
                raise Exception("登录失败")
                
        except Exception as e:
            # 发生异常时，强制截图
            if self.driver:
                try:
                    timestamp = datetime.now().strftime("%H%M%S")
                    filename = f"error_snapshot_{timestamp}.png"
                    self.driver.save_screenshot(filename)
                    logger.info(f"已保存错误现场截图: {filename}")
                except:
                    pass

            error_msg = f"自动签到失败: {str(e)}"
            if self._is_driver_timeout(str(e)):
                logger.warning("检测到驱动超时，尝试重启驱动并重试一次...")
                try:
                    self.restart_driver()
                    if self.login():
                        result = self.checkin()
                        balance = self.get_balance()
                        logger.info(f"Checkin result: {result}, balance: {balance}")
                        return True, result, balance
                except Exception as retry_e:
                    error_msg = f"Auto checkin failed: {str(retry_e)}"
            logger.error(error_msg)
            return False, error_msg, "未知"
        
        finally:
            if self.driver:
                try:
                    # 无论成功失败，最后都保存一张状态截图
                    self.driver.save_screenshot("final_state.png")
                except:
                    pass
                self.driver.quit()

class MultiAccountManager:
    """多账号管理器 - 简化配置版本"""
    
    def __init__(self, auto_load=True):
        self.telegram_bot_token = os.getenv('TELEGRAM_BOT_TOKEN', '')
        self.telegram_chat_id = os.getenv('TELEGRAM_CHAT_ID', '')
        self.accounts = []
        if auto_load:
            self.accounts = self.load_accounts()
    
    def load_accounts(self):
        """从环境变量加载多账号信息，支持冒号分隔多账号和单账号"""
        accounts = []
        
        logger.info("开始加载账号配置...")
        
        accounts_str = os.getenv('LEAFLOW_ACCOUNTS', '').strip()
        if accounts_str:
            try:
                logger.info("尝试解析冒号分隔多账号配置")
                account_pairs = [pair.strip() for pair in accounts_str.split(',')]
                
                logger.info(f"找到 {len(account_pairs)} 个账号")
                
                for i, pair in enumerate(account_pairs):
                    if ':' in pair:
                        email, password = pair.split(':', 1)
                        email = email.strip()
                        password = password.strip()
                        
                        if email and password:
                            accounts.append({
                                'email': email,
                                'password': password
                            })
                            logger.info(f"成功添加第 {i+1} 个账号")
                        else:
                            logger.warning(f"账号对格式错误")
                    else:
                        logger.warning(f"账号对缺少冒号分隔符")
                
                if accounts:
                    logger.info(f"从冒号分隔格式成功加载了 {len(accounts)} 个账号")
                    return accounts
                else:
                    logger.warning("冒号分隔配置中没有找到有效的账号信息")
            except Exception as e:
                logger.error(f"解析冒号分隔账号配置失败: {e}")
        
        single_email = os.getenv('LEAFLOW_EMAIL', '').strip()
        single_password = os.getenv('LEAFLOW_PASSWORD', '').strip()
        
        if single_email and single_password:
            accounts.append({
                'email': single_email,
                'password': single_password
            })
            logger.info("加载了单个账号配置")
            return accounts
        
        logger.error("未找到有效的账号配置")
        logger.error("请检查以下环境变量设置:")
        logger.error("1. LEAFLOW_ACCOUNTS: 冒号分隔多账号 (email1:pass1,email2:pass2)")
        logger.error("2. LEAFLOW_EMAIL 和 LEAFLOW_PASSWORD: 单账号")
        
        raise ValueError("未找到有效的账号配置")
    
    def send_notification(self, results):
        """发送汇总通知到Telegram - 按照指定模板格式"""
        if not self.telegram_bot_token or not self.telegram_chat_id:
            logger.info("Telegram配置未设置，跳过通知")
            return
        
        try:
            success_count = sum(1 for _, success, _, _ in results if success)
            total_count = len(results)
            current_date = datetime.now().strftime("%Y/%m/%d")
            
            message = f"🎁 Leaflow自动签到通知\n"
            message += f"📊 成功: {success_count}/{total_count}\n"
            message += f"📅 签到时间：{current_date}\n\n"
            
            for email, success, result, balance in results:
                masked_email = email[:3] + "***" + email[email.find("@"):]
                
                escaped_result = html.escape(str(result))
                escaped_balance = html.escape(str(balance))
                
                if success:
                    status = "✅"
                    message += f"账号：{masked_email}\n"
                    message += f"{status} {escaped_result}\n"
                    message += f"💰 当前总余额：{escaped_balance}。\n\n"
                else:
                    status = "❌"
                    message += f"账号：{masked_email}\n"
                    message += f"{status} {escaped_result}\n\n"
            
            url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
            data = {
                "chat_id": self.telegram_chat_id,
                "text": message,
                "parse_mode": "HTML"
            }
            
            response = requests.post(url, data=data, timeout=10)
            if response.status_code == 200:
                logger.info("Telegram汇总通知发送成功")
            else:
                logger.error(f"Telegram通知发送失败: {response.text}")
                
        except Exception as e:
            logger.error(f"发送Telegram通知时出错: {e}")
    
    def run_all(self):
        """运行所有账号的签到流程"""
        logger.info(f"开始执行 {len(self.accounts)} 个账号的签到任务")
        
        results = []
        
        for i, account in enumerate(self.accounts, 1):
            logger.info(f"处理第 {i}/{len(self.accounts)} 个账号")
            
            try:
                auto_checkin = LeaflowAutoCheckin(account['email'], account['password'])
                success, result, balance = auto_checkin.run()
                results.append((account['email'], success, result, balance))
                
                if i < len(self.accounts):
                    wait_time = 5
                    logger.info(f"等待{wait_time}秒后处理下一个账号...")
                    time.sleep(wait_time)
                    
            except Exception as e:
                error_msg = f"处理账号时发生异常: {str(e)}"
                logger.error(error_msg)
                results.append((account['email'], False, error_msg, "未知"))
        
        self.send_notification(results)
        
        success_count = sum(1 for _, success, _, _ in results if success)
        return success_count == len(self.accounts), results

def main():
    """主函数"""
    try:
        manager = MultiAccountManager()
        overall_success, detailed_results = manager.run_all()
        
        if overall_success:
            logger.info("✅ 所有账号签到成功")
            exit(0)
        else:
            success_count = sum(1 for _, success, _, _ in detailed_results if success)
            logger.warning(f"⚠️ 部分账号签到失败: {success_count}/{len(detailed_results)} 成功")
            exit(0)
            
    except Exception as e:
        logger.error(f"❌ 脚本执行出错: {e}")
        exit(1)

if __name__ == "__main__":
    main()
