import asyncio
import os
import random
import time
import threading
import sqlite3
import base64
import requests
from flask import Flask
from telethon import TelegramClient, events, functions
from telethon.sessions import StringSession
from telethon.errors import (
    SessionPasswordNeededError,
    UsernameOccupiedError,
    UsernameNotModifiedError,
    FloodWaitError
)

# --- MASTER CONFIGURATION ---
API_ID = int(os.environ.get("API_ID", 35450000))
API_HASH = os.environ.get("API_HASH", "2f06604ccfb6670846f4640ac40b8f97")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8894074405:AAHUbw_kkSMt4CXWHFxxu1LTj46OO5Sj7B0")

# GitHub Sync Configuration for Permanent Storage (Data never lost on redeploy)
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "") # e.g., "username/repo-name"
GITHUB_USERNAME = os.environ.get("GITHUB_USERNAME", "")

DB_FILE = "sessions.db"

# --- GITHUB AUTO-SYNC FUNCTIONS ---
def download_db_from_github():
    if not GITHUB_TOKEN or not GITHUB_REPO:
        print("[*] GitHub sync credentials not found. Using local DB.")
        return
    
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{DB_FILE}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            file_data = response.json()
            file_content = base64.b64decode(file_data["content"])
            with open(DB_FILE, "wb") as f:
                f.write(file_content)
            print("[+] Successfully restored sessions.db from GitHub!")
        else:
            print("[*] No existing sessions.db found on GitHub yet. A new one will be created.")
    except Exception as e:
        print(f"[-] Error downloading DB from GitHub: {e}")

def upload_db_to_github():
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return
    
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{DB_FILE}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    
    try:
        with open(DB_FILE, "rb") as f:
            content_bytes = f.read()
        encoded_content = base64.b64encode(content_bytes).decode("utf-8")
        
        get_resp = requests.get(url, headers=headers)
        sha = get_resp.json().get("sha") if get_resp.status_code == 200 else None
        
        data = {
            "message": "Auto-update sessions.db via bot",
            "content": encoded_content,
            "committer": {"name": GITHUB_USERNAME or "SniperBot", "email": "bot@sniper.com"}
        }
        if sha:
            data["sha"] = sha
            
        put_resp = requests.put(url, headers=headers, json=data)
        if put_resp.status_code in [200, 201]:
            print("[+] sessions.db successfully backed up to GitHub!")
        else:
            print(f"[-] Failed to upload DB to GitHub: {put_resp.text}")
    except Exception as e:
        print(f"[-] Error uploading DB to GitHub: {e}")

# Download DB before initializing
download_db_from_github()

# --- DATABASE SETUP ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS accounts (
            name TEXT PRIMARY KEY,
            session_string TEXT NOT NULL
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def save_session_to_db(name, session_str):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('REPLACE INTO accounts (name, session_string) VALUES (?, ?)', (name, session_str))
    conn.commit()
    conn.close()
    upload_db_to_github()

def get_session_from_db(name):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT session_string FROM accounts WHERE name = ?', (name,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None

def get_all_accounts_from_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT name FROM accounts')
    rows = cursor.fetchall()
    conn.close()
    return [row[0] for row in rows]

# --- FLASK KEEP-ALIVE SERVER ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Self-Sniper Bot with Safe Anti-Flood & GitHub Sync is active 24/7!", 200

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

# --- STATE MANAGEMENT ---
active_session_name = None
active_client = None
user_states = {}

# --- BOTFATHER BOT SETUP ---
bot = TelegramClient('bot_session', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# --- COMMANDS HANDLERS ---

@bot.on(events.NewMessage(pattern=r'/start'))
async def start_cmd(event):
    if event.is_group or event.is_channel:
        return
    help_text = (
        "🤖 **Self-Account Sniper Bot (Anti-Flood Protected)**\n\n"
        "📂 **Session Management:**\n"
        "• `/addaccount <name>` - Add a new Telegram account\n"
        "• `/accounts` - List all saved accounts\n"
        "• `/select <name>` - Choose an account to use\n\n"
        "🎯 **Sniping Controls:**\n"
        "• `/snipe <username>` - Self-snipes with safe 15s interval\n"
        "• `/stop` - Stop active sniping\n"
        "• `/status` - Check current bot status"
    )
    await event.respond(help_text)

@bot.on(events.NewMessage(pattern=r'/addaccount\s+(.+)'))
async def add_account_cmd(event):
    if event.is_group or event.is_channel:
        return
    acc_name = event.pattern_match.group(1).strip()
    user_id = event.sender_id
    
    user_states[user_id] = {"step": "phone", "name": acc_name}
    await event.respond(f"📱 Please send the phone number for account **{acc_name}** (e.g., `+919876543210`):")

@bot.on(events.NewMessage(pattern=r'/accounts'))
async def list_accounts_cmd(event):
    if event.is_group or event.is_channel:
        return
    accounts = get_all_accounts_from_db()
    if not accounts:
        await event.respond("❌ No accounts saved in database yet. Use `/addaccount <name>` to add one.")
        return
    
    msg = "📂 **Saved Accounts (GitHub Backup Secure):**\n"
    for name in accounts:
        indicator = "🟢 (Active)" if name == active_session_name else ""
        msg += f"• `{name}` {indicator}\n"
    await event.respond(msg)

@bot.on(events.NewMessage(pattern=r'/select\s+(.+)'))
async def select_account_cmd(event):
    global active_session_name, active_client
    if event.is_group or event.is_channel:
        return
    acc_name = event.pattern_match.group(1).strip()
    
    session_str = get_session_from_db(acc_name)
    if not session_str:
        await event.respond(f"❌ Account `{acc_name}` not found in database. Check `/accounts`.")
        return
    
    active_session_name = acc_name
    
    if active_client and active_client.is_connected():
        await active_client.disconnect()
        
    active_client = TelegramClient(StringSession(session_str), API_ID, API_HASH, flood_sleep_threshold=0)
    await active_client.connect()
    
    await event.respond(f"✅ Successfully switched active account to: **{acc_name}**")

# Global variables for infinite loop
snipe_task = None
is_sniping = False
active_target = None

async def run_snipe_loop(target_username, event):
    global is_sniping, active_target
    is_sniping = True
    active_target = target_username
    
    start_time = time.time()
    attempts = 0
    
    await event.respond(f"🎯 **Anti-Flood Self-Sniping Started!** Target: `@{target_username}` for Account **{active_session_name}** | Interval: **15s Safe Gap**\n(Running continuously until `/stop`)")
    
    while is_sniping:
        attempts += 1
        try:
            await active_client(functions.account.UpdateUsernameRequest(
                username=target_username
            ))
            
            elapsed = round(time.time() - start_time, 2)
            await event.respond(
                f"🎉 **SUCCESS! Username Claimed for Profile!**\n\n"
                f"📌 Username: `@{target_username}`\n"
                f"👤 Account: `{active_session_name}`\n"
                f"⏱️ Time Taken: **{elapsed} seconds**\n"
                f"🔄 Total Attempts: {attempts}"
            )
            is_sniping = False
            break
            
        except UsernameOccupiedError:
            # Safe 15-second gap with minor random jitter to protect from flood
            await asyncio.sleep(random.uniform(14.8, 16.2))
        except FloodWaitError as e:
            await event.respond(f"⚠️ FloodWait hit: Sleeping safely for {e.seconds} seconds...")
            await asyncio.sleep(e.seconds)
        except UsernameNotModifiedError:
            await event.respond(f"✅ Username `@{target_username}` is already set on your account!")
            is_sniping = False
            break
        except Exception:
            await asyncio.sleep(15.0)

    active_target = None

@bot.on(events.NewMessage(pattern=r'/snipe\s+(.+)'))
async def snipe_cmd(event):
    global snipe_task, is_sniping
    if event.is_group or event.is_channel:
        return
    if is_sniping:
        await event.respond(f"⚠️ Already sniping `@{active_target}`! Send `/stop` first if you want to change target.")
        return
    if not active_session_name or not active_client:
        await event.respond("❌ No account selected! Use `/select <name>` first.")
        return
        
    target_username = event.pattern_match.group(1).strip().lstrip('@')
    snipe_task = asyncio.create_task(run_snipe_loop(target_username, event))

@bot.on(events.NewMessage(pattern=r'/stop'))
async def stop_cmd(event):
    global is_sniping, snipe_task
    if event.is_group or event.is_channel:
        return
    if not is_sniping:
        await event.respond("ℹ️ No active snipe task running.")
        return
    is_sniping = False
    if snipe_task:
        snipe_task.cancel()
    await event.respond("🛑 Sniping stopped successfully.")

@bot.on(events.NewMessage(pattern=r'/status'))
async def status_cmd(event):
    if event.is_group or event.is_channel:
        return
    if is_sniping:
        await event.respond(f"🟢 Actively self-sniping `@{active_target}` using account `{active_session_name}` (15s safe gap)")
    else:
        await event.respond(f"⚪ Idle. Active Account: `{active_session_name or 'None'}`")

# --- INTERACTIVE LOGIN HANDLER ---
@bot.on(events.NewMessage)
async def interactive_auth(event):
    if event.is_group or event.is_channel:
        return
        
    user_id = event.sender_id
    if user_id not in user_states:
        return
        
    text = event.raw_text.strip()
    if text.startswith('/'):
        return

    state = user_states[user_id]
    step = state["step"]
    
    if step == "phone":
        state["phone"] = text
        try:
            temp_client = TelegramClient(StringSession(), API_ID, API_HASH)
            await temp_client.connect()
            sent = await temp_client.send_code_request(text)
            state["temp_client"] = temp_client
            state["phone_hash"] = sent.phone_code_hash
            state["step"] = "code"
            await event.respond("📨 OTP sent to your Telegram app! Please reply with the code:")
        except Exception as e:
            await event.respond(f"❌ Error sending code: {e}")
            del user_states[user_id]

    elif step == "code":
        temp_client = state["temp_client"]
        try:
            await temp_client.sign_in(phone=state["phone"], code=text, phone_code_hash=state["phone_hash"])
            session_str = temp_client.session.save()
            await temp_client.disconnect()
            
            acc_name = state["name"]
            save_session_to_db(acc_name, session_str)
            await event.respond(f"✅ Account **{acc_name}** added & backed up to GitHub securely!\nUse `/select {acc_name}` to activate it.")
            del user_states[user_id]
        except SessionPasswordNeededError:
            state["step"] = "password"
            await event.respond("🔒 2FA Password required. Please enter your cloud password:")
        except Exception as e:
            await event.respond(f"❌ Sign-in failed (Invalid Code): {e}\nPlease send the correct OTP code:")

    elif step == "password":
        temp_client = state["temp_client"]
        try:
            await temp_client.sign_in(password=text)
            session_str = temp_client.session.save()
            await temp_client.disconnect()
            
            acc_name = state["name"]
            save_session_to_db(acc_name, session_str)
            await event.respond(f"✅ Account **{acc_name}** added with 2FA & backed up to GitHub securely!\nUse `/select {acc_name}` to activate it.")
            del user_states[user_id]
        except Exception as e:
            await event.respond(f"❌ Incorrect Password! Please check and send your cloud password again:")

# --- MAIN STARTUP ---
def main():
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    print("[*] Keep-alive Flask server running.")
    print("[*] Self-Sniper Bot with Anti-Flood & GitHub Sync is running...")
    bot.run_until_disconnected()

if __name__ == '__main__':
    main()
