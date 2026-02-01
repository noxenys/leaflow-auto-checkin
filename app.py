from flask import Flask, render_template, request, jsonify
import os
import json
import subprocess
import threading
import time
from datetime import datetime

app = Flask(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
CONFIG_FILE = os.path.join(DATA_DIR, 'config.json')
LOG_FILE = os.path.join(DATA_DIR, 'checkin.log')

if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"accounts": [], "cookies": [], "telegram": {}}

def save_config(config):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=4, ensure_ascii=False)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/config', methods=['GET', 'POST'])
def handle_config():
    if request.method == 'POST':
        config = request.json
        save_config(config)
        return jsonify({"status": "success"})
    return jsonify(load_config())

@app.route('/api/logs')
def get_logs():
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            # 读取最后 100 行
            lines = f.readlines()
            return jsonify({"logs": "".join(lines[-100:])})
    return jsonify({"logs": "暂无日志"})

def run_checkin_process():
    config = load_config()
    env = os.environ.copy()
    
    # 构建环境变量
    accounts = []
    for acc in config.get('accounts', []):
        if acc.get('email') and acc.get('password'):
            accounts.append(f"{acc['email']}:{acc['password']}")
    
    if accounts:
        env['LEAFLOW_ACCOUNTS'] = ",".join(accounts)
    
    cookies = []
    for cookie in config.get('cookies', []):
        if cookie.get('value'):
            cookies.append(cookie['value'])
    if cookies:
        env['LEAFLOW_COOKIE'] = cookies[0] # 目前脚本只支持单 Cookie 变量，取第一个
        
    tg = config.get('telegram', {})
    if tg.get('token'):
        env['TELEGRAM_BOT_TOKEN'] = tg['token']
    if tg.get('chat_id'):
        env['TELEGRAM_CHAT_ID'] = tg['chat_id']

    # 运行脚本并将输出重定向到日志文件
    with open(LOG_FILE, 'a', encoding='utf-8') as log_f:
        log_f.write(f"\n--- 任务开始: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---\n")
        log_f.flush()
        process = subprocess.Popen(
            [os.sys.executable, 'leaflow_checkin.py'],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8'
        )
        
        for line in process.stdout:
            log_f.write(line)
            log_f.flush()
            
        process.wait()
        log_f.write(f"\n--- 任务结束: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---\n")

@app.route('/api/run', methods=['POST'])
def run_checkin():
    threading.Thread(target=run_checkin_process).start()
    return jsonify({"status": "started", "message": "签到任务已在后台启动，请查看日志"})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
