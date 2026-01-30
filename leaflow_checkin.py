#!/usr/bin/env python3
"""
Leaflow 多账号自动签到脚本
变量名：LEAFLOW_ACCOUNTS
变量值：邮箱1:密码1,邮箱2:密码2,邮箱3:密码3
"""

import os
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

# 在GitHub Actions环境中使用webdriver-manager
if os.getenv('GITHUB_ACTIONS'):
    from webdriver_manager.chrome import ChromeDriverManager
    from selenium.webdriver.chrome.service import Service

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class LeaflowAutoCheckin:
    def __init__(self, email, password):
        self.email = email
        self.password = password
        self.telegram_bot_token = os.getenv('TELEGRAM_BOT_TOKEN', '')
        self.telegram_chat_id = os.getenv('TELEGRAM_CHAT_ID', '')
        
        if not self.email or not self.password:
            raise ValueError("邮箱和密码不能为空")
        
        self.driver = None
        self.setup_driver()
    
    def setup_driver(self):
        """设置Chrome驱动选项"""
        chrome_options = Options()
        # Reduce page-load blocking in CI.
        chrome_options.page_load_strategy = "eager"
        
        # 通用防检测配置
        chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
        
        # GitHub Actions环境配置
        if os.getenv('GITHUB_ACTIONS'):
            chrome_options.add_argument('--headless=new')
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            chrome_options.add_argument('--disable-gpu')
            chrome_options.add_argument('--window-size=1920,1080')
            
            # 在GitHub Actions环境中使用webdriver-manager自动管理ChromeDriver
            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=chrome_options)
        else:
            # 本地环境配置
            chrome_options.add_argument('--disable-blink-features=AutomationControlled')
            chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
            chrome_options.add_experimental_option('useAutomationExtension', False)
            
            self.driver = webdriver.Chrome(options=chrome_options)
        
        try:
            self.driver.set_page_load_timeout(60)
            self.driver.set_script_timeout(30)
        except Exception:
            pass

        self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
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
            
            # 尝试关闭弹窗
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
        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                logger.info(f"开始登录流程，第 {attempt + 1}/{max_retries} 次尝试...")
                
                # 访问登录页面
                self.driver.get("https://leaflow.net/login")
                
                # 显式等待页面完全加载，防止在白屏阶段就开始查找元素
                WebDriverWait(self.driver, 40).until(
                    EC.presence_of_element_located((By.TAG_NAME, "body"))
                )
                
                time.sleep(5)
        
                # 关闭弹窗
                self.close_popup()
                
                # 输入邮箱
                try:
                    logger.info("查找邮箱输入框...")
                    
                    # 等待页面稳定
                    time.sleep(2)
                    
                    # 尝试多种选择器找到邮箱输入框
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
                    
                    # 清除并输入邮箱
                    email_input.clear()
                    email_input.send_keys(self.email)
                    logger.info("邮箱输入完成")
                    time.sleep(2)
                    
                except Exception as e:
                    logger.error(f"输入邮箱时出错: {e}")
                    # 尝试使用JavaScript直接设置值
                    try:
                        self.driver.execute_script(f"document.querySelector('input[type=\"text\"], input[type=\"email\"]').value = '{self.email}';")
                        logger.info("通过JavaScript设置邮箱")
                        time.sleep(2)
                    except:
                        raise Exception(f"无法输入邮箱: {e}")
                
                # 等待密码输入框出现并输入密码
                try:
                    logger.info("查找密码输入框...")
                    
                    # 等待密码框出现
                    password_input = self.wait_for_element_clickable(
                        By.CSS_SELECTOR, "input[type='password']", 10
                    )
                    
                    password_input.clear()
                    password_input.send_keys(self.password)
                    logger.info("密码输入完成")
                    time.sleep(1)
                    
                except TimeoutException:
                    raise Exception("找不到密码输入框")
                
                # 点击登录按钮
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
                    raise Exception(f"点击登录按钮失败: {e}")
                
                # 等待登录完成 - 延长超时时间到40秒，给Cloudflare的5秒盾留出更多通过时间
                try:
                    WebDriverWait(self.driver, 40).until(
                        lambda driver: "dashboard" in driver.current_url or "workspaces" in driver.current_url or "login" not in driver.current_url
                    )
                    
                    # 检查当前URL确认登录成功
                    current_url = self.driver.current_url
                    if "dashboard" in current_url or "workspaces" in current_url or "login" not in current_url:
                        logger.info(f"登录成功，当前URL: {current_url}")
                        return True
                    else:
                        raise Exception("登录后未跳转到正确页面")
                        
                except TimeoutException:
                    # 检查是否登录失败
                    try:
                        error_selectors = [".error", ".alert-danger", "[class*='error']", "[class*='danger']"]
                        for selector in error_selectors:
                            try:
                                error_msg = self.driver.find_element(By.CSS_SELECTOR, selector)
                                if error_msg.is_displayed():
                                    raise Exception(f"登录失败: {error_msg.text}")
                            except:
                                continue
                        raise Exception("登录超时，无法确认登录状态")
                    except Exception as e:
                        raise e
                
            except Exception as e:
                logger.warning(f"第 {attempt + 1} 次登录尝试失败: {e}")
                
                # 如果不是最后一次尝试，刷新页面并等待后重试
                if attempt < max_retries - 1:
                    logger.info(f"正在进行第 {attempt + 2} 次重试...")
                    self.driver.refresh()
                    time.sleep(5)
                    continue
                else:
                    # 最后一次尝试失败，抛出异常
                    raise Exception(f"登录失败，已尝试 {max_retries} 次: {e}")
        
        return False
    
    def get_balance(self):
        """获取当前账号的总余额"""
        try:
            logger.info("获取账号余额...")
            
            # 跳转到仪表板页面
            self.driver.get("https://leaflow.net/dashboard")
            time.sleep(3)
            
            # 等待页面加载
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            
            # 尝试多种选择器查找余额元素
            balance_selectors = [
                "//*[contains(text(), '¥') or contains(text(), '￥') or contains(text(), '元')]",
                "//*[contains(@class, 'balance')]",
                "//*[contains(@class, 'money')]",
                "//*[contains(@class, 'amount')]",
                "//button[contains(@class, 'dollar')]",
                "//span[contains(@class, 'font-medium')]"
            ]
            
            for selector in balance_selectors:
                try:
                    elements = self.driver.find_elements(By.XPATH, selector)
                    for element in elements:
                        text = element.text.strip()
                        # 查找包含数字和货币符号的文本
                        if any(char.isdigit() for char in text) and ('¥' in text or '￥' in text or '元' in text):
                            # 提取数字部分
                            import re
                            numbers = re.findall(r'\d+\.?\d*', text)
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
                # 检查页面是否包含签到相关元素
                checkin_indicators = [
                    "button.checkin-btn",  # 优先使用这个选择器
                    "//button[contains(text(), '立即签到')]",
                    "//button[contains(text(), '已签到')]",
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
        logger.info("查找签到按钮...")
        
        try:
            # 先等待页面可能的重载
            time.sleep(5)
            
            # 使用和单账号成功时相同的选择器
            checkin_selectors = [
                "button.checkin-btn",
                "//button[contains(text(), '立即签到')]",
                "//button[contains(@class, 'checkin')]",
                "button[type='submit']",
                "button[name='checkin']"
            ]
            
            for selector in checkin_selectors:
                try:
                    if selector.startswith("//"):
                        checkin_btn = WebDriverWait(self.driver, 15).until(
                            EC.presence_of_element_located((By.XPATH, selector))
                        )
                    else:
                        checkin_btn = WebDriverWait(self.driver, 15).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                        )
                    
                    if checkin_btn.is_displayed():
                        # 检查按钮文本，如果包含"已签到"则说明今天已经签到过了
                        btn_text = checkin_btn.text.strip()
                        if "已签到" in btn_text:
                            logger.info("伙计，今日你已经签到过了！")
                            return "already_checked_in"
                        
                        # 检查按钮是否可用
                        if checkin_btn.is_enabled():
                            logger.info(f"找到并点击立即签到按钮")
                            checkin_btn.click()
                            return True
                        else:
                            logger.info("签到按钮不可用，可能已经签到过了")
                            return "already_checked_in"
                        
                except Exception as e:
                    logger.debug(f"选择器未找到按钮: {e}")
                    continue
            
            logger.error("找不到签到按钮")
            return False
                    
        except Exception as e:
            logger.error(f"查找签到按钮时出错: {e}")
            return False
    
    def checkin(self):
        """执行签到流程"""
        logger.info("跳转到签到页面...")
        
        # 跳转到签到页面
        self.safe_get("https://checkin.leaflow.net", max_retries=2, wait_between=3)
        
        # 等待签到页面加载（最多重试3次，每次等待20秒）
        if not self.wait_for_checkin_page_loaded(max_retries=3, wait_time=20):
            raise Exception("签到页面加载失败，无法找到签到相关元素")
        
        # 查找并点击立即签到按钮
        checkin_result = self.find_and_click_checkin_button()
        
        if checkin_result == "already_checked_in":
            return "今日已签到"
        elif checkin_result is True:
            logger.info("已点击立即签到按钮")
            time.sleep(5)  # 等待签到结果
            
            # 获取签到结果
            result_message = self.get_checkin_result()
            return result_message
        else:
            raise Exception("找不到立即签到按钮或按钮不可点击")
    
    def get_checkin_result(self):
        """获取签到结果消息"""
        try:
            # 给页面一些时间显示结果
            time.sleep(3)
            
            # 尝试查找各种可能的成功消息元素
            success_selectors = [
                ".alert-success",
                ".success",
                ".message",
                "[class*='success']",
                "[class*='message']",
                ".modal-content",  # 弹窗内容
                ".ant-message",    # Ant Design 消息
                ".el-message",     # Element UI 消息
                ".toast",          # Toast消息
                ".notification"    # 通知
            ]
            
            for selector in success_selectors:
                try:
                    element = self.driver.find_element(By.CSS_SELECTOR, selector)
                    if element.is_displayed():
                        text = element.text.strip()
                        if text:
                            return text
                except:
                    continue
            
            # 如果没有找到特定元素，检查页面文本
            page_text = self.driver.find_element(By.TAG_NAME, "body").text
            important_keywords = ["成功", "签到", "获得", "恭喜", "谢谢", "感谢", "完成", "已签到", "连续签到"]
            
            for keyword in important_keywords:
                if keyword in page_text:
                    # 提取包含关键词的行
                    lines = page_text.split('\n')
                    for line in lines:
                        if keyword in line and len(line.strip()) < 100:  # 避免提取过长的文本
                            return line.strip()
            
            # 检查签到按钮状态变化
            try:
                checkin_btn = self.driver.find_element(By.CSS_SELECTOR, "button.checkin-btn")
                if not checkin_btn.is_enabled() or "已签到" in checkin_btn.text or "disabled" in checkin_btn.get_attribute("class"):
                    return "今日已签到完成"
            except:
                pass
            
            return "签到完成，但未找到具体结果消息"
            
        except Exception as e:
            return f"获取签到结果时出错: {str(e)}"
    
    def run(self):
        """单个账号执行流程"""
        try:
            logger.info(f"开始处理账号")
            
            # 登录
            if self.login():
                # 签到
                result = self.checkin()
                
                # 获取余额
                balance = self.get_balance()
                
                logger.info(f"签到结果: {result}, 余额: {balance}")
                return True, result, balance
            else:
                raise Exception("登录失败")
                
        except Exception as e:
            error_msg = f"自动签到失败: {str(e)}"
            if self._is_driver_timeout(str(e)):
                logger.warning("Browser timeout detected, restarting driver and retrying once...")
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
                self.driver.quit()

class MultiAccountManager:
    """多账号管理器 - 简化配置版本"""
    
    def __init__(self):
        self.telegram_bot_token = os.getenv('TELEGRAM_BOT_TOKEN', '')
        self.telegram_chat_id = os.getenv('TELEGRAM_CHAT_ID', '')
        self.accounts = self.load_accounts()
    
    def load_accounts(self):
        """从环境变量加载多账号信息，支持冒号分隔多账号和单账号"""
        accounts = []
        
        logger.info("开始加载账号配置...")
        
        # 方法1: 冒号分隔多账号格式
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
        
        # 方法2: 单账号格式
        single_email = os.getenv('LEAFLOW_EMAIL', '').strip()
        single_password = os.getenv('LEAFLOW_PASSWORD', '').strip()
        
        if single_email and single_password:
            accounts.append({
                'email': single_email,
                'password': single_password
            })
            logger.info("加载了单个账号配置")
            return accounts
        
        # 如果所有方法都失败
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
            # 构建通知消息
            success_count = sum(1 for _, success, _, _ in results if success)
            total_count = len(results)
            current_date = datetime.now().strftime("%Y/%m/%d")
            
            message = f"🎁 Leaflow自动签到通知\n"
            message += f"📊 成功: {success_count}/{total_count}\n"
            message += f"📅 签到时间：{current_date}\n\n"
            
            for email, success, result, balance in results:
                # 隐藏邮箱部分字符以保护隐私
                masked_email = email[:3] + "***" + email[email.find("@"):]
                
                # 对结果和余额进行HTML转义，防止特殊符号导致Telegram API报错
                escaped_result = html.escape(str(result))
                escaped_balance = html.escape(str(balance))
                
                if success:
                    status = "✅"
                    message += f"账号：{masked_email}\n"
                    message += f"{status}  {escaped_result}！\n"
                    message += f"💰  当前总余额：{escaped_balance}。\n\n"
                else:
                    status = "❌"
                    message += f"账号：{masked_email}\n"
                    message += f"{status}  {escaped_result}\n\n"
            
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
                
                # 在账号之间添加间隔，避免请求过于频繁
                if i < len(self.accounts):
                    wait_time = 5
                    logger.info(f"等待{wait_time}秒后处理下一个账号...")
                    time.sleep(wait_time)
                    
            except Exception as e:
                error_msg = f"处理账号时发生异常: {str(e)}"
                logger.error(error_msg)
                results.append((account['email'], False, error_msg, "未知"))
        
        # 发送汇总通知
        self.send_notification(results)
        
        # 返回总体结果
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
            # 即使有失败，也不退出错误状态，因为可能部分成功
            exit(0)
            
    except Exception as e:
        logger.error(f"❌ 脚本执行出错: {e}")
        exit(1)

if __name__ == "__main__":
    main()
