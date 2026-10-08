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
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8894074405:AAHUbw_kkSMt4CXWHFxxu1LTj46OO5Sj7B")

# GitHub Sync Configuration for Permanent Storage
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "") 
GITHUB_USERNAME = os.environ.get("GITHUB_USERNAME", "")

DB_FILE = "sessions.db"

# --- GITHUB AUTO-SYNC FUNCTIONS ---
def download_db_from_github():
    if not GITHUB_TOKEN or not GITHUB_REPO:
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
        requests.put(url, headers=headers, json=data)
    except Exception as e:
        print(f"[-] Error uploading DB to GitHub: {e}")

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
    return "Interleaved Multi-Account Sniper Bot is active 24/7!", 200

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

# --- STATE MANAGEMENT ---
user_states = {}
is_sniping = False
active_target = None
snipe_tasks = []

bot = TelegramClient('bot_session', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# --- COMMANDS ---
@bot.on(events.NewMessage(pattern=r'/start'))
async def start_cmd(event):
    if event.is_group or event.is_channel:
        return
    help_text = (
        "🤖 **Interleaved Dual-Account Sniper Bot**\n\n"
        "📂 **Commands:**\n"
        "• `/addaccount <name>` - Add accounts\n"
        "• `/accounts` - View saved accounts\n"
        "• `/snipe <username>` - Starts interleaved dual sniping (Account 1 @ 0s, Account 2 @ 10s)\n"
        "• `/stop` - Stop all sniping\n"
        "• `/status` - Check current status"
    )
    await event.respond(help_text)

@bot.on(events.NewMessage(pattern=r'/addaccount\s+(.+)'))
async def add_account_cmd(event):
    if event.is_group or event.is_channel:
        return
    acc_name = event.pattern_match.group(1).strip()
    user_id = event.sender_id
    user_states[user_id] = {"step": "phone", "name": acc_name}
    await event.respond(f"📱 Send phone number for account **{acc_name}** (e.g., `+919876543210`):")

@bot.on(events.NewMessage(pattern=r'/accounts'))
async def list_accounts_cmd(event):
    if event.is_group or event.is_channel:
        return
    accounts = get_all_accounts_from_db()
    if not accounts:
        await event.respond("❌ No accounts found. Use `/addaccount <name>`.")
        return
    msg = "📂 **Saved Accounts Pool:**\n"
    for name in accounts:
        msg += f"• `{name}`\n"
    await event.respond(msg)

# --- INDIVIDUAL WORKER FOR INTERLEAVED TIMING ---
async def sniper_worker(acc_name, session_str, target_username, initial_delay, event):
    global is_sniping
    client = TelegramClient(StringSession(session_str), API_ID, API_HASH, flood_sleep_threshold=0)
    try:
        await client.connect()
    except Exception as e:
        await event.respond(f"❌ Connection failed for account `{acc_name}`: {e}")
        return

    # Initial staggered delay (e.g., 0s for first account, 10s for second account)
    if initial_delay > 0:
        await asyncio.sleep(initial_delay)

    attempts = 0
    start_time = time.time()

    while is_sniping:
        attempts += 1
        try:
            await client(functions.account.UpdateUsernameRequest(username=target_username))
            
            elapsed = round(time.time() - start_time, 2)
            await event.respond(
                f"🎉 **SUCCESS! Username Claimed!**\n\n"
                f"📌 Username: `@{target_username}`\n"
                f"👤 Successful Account: `{acc_name}`\n"
                f"⏱️ Time Taken: **{elapsed} seconds**\n"
                f"🔄 Total Attempts (by this account): {attempts}"
            )
            is_sniping = False
            break
            
        except UsernameOccupiedError:
            # 20 seconds total interval per account, but since we have 2 accounts interleaved, total effective hits go every 10 seconds!
            await asyncio.sleep(20.0)
            
        except FloodWaitError as e:
            await event.respond(f"⚠️ Account `{acc_name}` hit FloodWait ({e.seconds}s). Sleeping that specific account...")
            await asyncio.sleep(e.seconds)
            
        except UsernameNotModifiedError:
            await event.respond(f"✅ Username `@{target_username}` is already set on account `{acc_name}`!")
            is_sniping = False
            break
        except Exception:
            await asyncio.sleep(20.0)

    try:
        await client.disconnect()
    except:
        pass

@bot.on(events.NewMessage(pattern=r'/snipe\s+(.+)'))
async def snipe_cmd(event):
    global snipe_tasks, is_sniping, active_target
    if event.is_group or event.is_channel:
        return
    if is_sniping:
        await event.respond(f"⚠️ Already sniping `@{active_target}`! Send `/stop` first.")
        return
        
    accounts = get_all_accounts_from_db()
    if len(accounts) < 2:
        await event.respond(f"❌ You need at least **2 accounts** saved in database for this interleaved strategy! Currently found: {len(accounts)}. Add more using `/addaccount`.")
        return

    target_username = event.pattern_match.group(1).strip().lstrip('@')
    is_sniping = True
    active_target = target_username
    snipe_tasks = []

    # Pick first 2 accounts for dual-interleaved rotation
    acc1 = accounts[0]
    acc2 = accounts[1]
    
    str1 = get_session_from_db(acc1)
    str2 = get_session_from_db(acc2)

    await event.respond(
        f"🎯 **Interleaved Dual-Sniper Started!**\n"
        f"Target: `@{target_username}`\n"
        f"• Account 1 (`{acc1}`): Starts immediately (0s gap, then every 20s)\n"
        f"• Account 2 (`{acc2}`): Starts with 10s offset (then every 20s)\n"
        f"⚡ *Result: Effective request frequency = Every 10 seconds across accounts!*"
    )

    # Launch both workers concurrently with a 10-second offset
    task1 = asyncio.create_task(sniper_worker(acc1, str1, target_username, 0, event))
    task2 = asyncio.create_task(sniper_worker(acc2, str2, target_username, 10, event))
    
    snipe_tasks = [task1, task2]

@bot.on(events.NewMessage(pattern=r'/stop'))
async def stop_cmd(event):
    global is_sniping, snipe_tasks
    if event.is_group or event.is_channel:
        return
    if not is_sniping:
        await event.respond("ℹ️ No active sniping running.")
        return
    is_sniping = False
    for task in snipe_tasks:
        task.cancel()
    await event.respond("🛑 Interleaved sniping stopped successfully.")

@bot.on(events.NewMessage(pattern=r'/status'))
async def status_cmd(event):
    if event.is_group or event.is_channel:
        return
    if is_sniping:
        await event.respond(f"🟢 Dual-Interleaved Sniping active on `@{target_username}`.")
    else:
        await event.respond("⚪ Idle.")

# --- AUTH HANDLER ---
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
            await event.respond("📨 OTP sent! Please reply with the code:")
        except Exception as e:
            await event.respond(f"❌ Error: {e}")
            del user_states[user_id]

    elif step == "code":
        temp_client = state["temp_client"]
        try:
            await temp_client.sign_in(phone=state["phone"], code=text, phone_code_hash=state["phone_hash"])
            session_str = temp_client.session.save()
            await temp_client.disconnect()
            acc_name = state["name"]
            save_session_to_db(acc_name, session_str)
            await event.respond(f"✅ Account **{acc_name}** added & backed up to GitHub securely!")
            del user_states[user_id]
        except SessionPasswordNeededError:
            state["step"] = "password"
            await event.respond("🔒 Enter 2FA Password:")
        except Exception as e:
            await event.respond(f"❌ Invalid Code: {e}\nSend correct code:")

    elif step == "password":
        temp_client = state["temp_client"]
        try:
            await temp_client.sign_in(password=text)
            session_str = temp_client.session.save()
            await temp_client.disconnect()
            acc_name = state["name"]
            save_session_to_db(acc_name, session_str)
            await event.respond(f"✅ Account **{acc_name}** added with 2FA & backed up!")
            del user_states[user_id]
        except Exception as e:
            await event.respond(f"❌ Incorrect Password! Try again:")

def main():
    threading.Thread(target=run_flask, daemon=True).start()
    print("[*] Interleaved Dual-Account Sniper Bot running 24/7.")
    bot.run_until_disconnected()

if __name__ == '__main__':
    main()
