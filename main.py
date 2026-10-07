import asyncio
import os
import random
import time
import threading
import sqlite3
from flask import Flask
from telethon import TelegramClient, events, functions
from telethon.sessions import StringSession
from telethon.errors import (
    SessionPasswordNeededError,
    UsernameOccupiedError,
    UsernameNotModifiedError,
    ChatAdminRequiredError,
    ChannelsAdminPublicTooMuchError,
    FloodWaitError
)

# --- MASTER CONFIGURATION ---
API_ID = int(os.environ.get("API_ID", 35450000))
API_HASH = os.environ.get("API_HASH", "2f06604ccfb6670846f4640ac40b8f97")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8894074405:AAHUbw_kkSMt4CXWHFxxu1LTj46OO5Sj7B0")
TARGET_CHANNEL = os.environ.get("TARGET_CHANNEL_ID", "your_channel_username")

# --- DATABASE SETUP (Prevents data loss on redeploy if persistent disk is attached, or saves locally) ---
DB_FILE = "sessions.db"

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
    return "Multi-Session Sniper Bot is active 24/7!", 200

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
        "🤖 **Multi-Account Sniper Bot Control Panel**\n\n"
        "📂 **Session Management:**\n"
        "• `/addaccount <name>` - Add a new Telegram account\n"
        "• `/accounts` - List all saved accounts\n"
        "• `/select <name>` - Choose an account to use\n\n"
        "🎯 **Sniping Controls:**\n"
        "• `/snipe <username>` - Start infinite sniping until /stop\n"
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
    
    msg = "📂 **Saved Accounts (Database Secure):**\n"
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

async def run_snipe_loop(target_username, channel_entity, event):
    global is_sniping, active_target
    is_sniping = True
    active_target = target_username
    
    start_time = time.time()
    attempts = 0
    
    await event.respond(f"🎯 **Infinite Sniping Started!** Target: `@{target_username}` using account **{active_session_name}**...\n(Bot will keep trying continuously until you send `/stop`)")
    
    while is_sniping:
        attempts += 1
        try:
            await active_client(functions.channels.UpdateUsernameRequest(
                channel=channel_entity,
                username=target_username
            ))
            
            elapsed = round(time.time() - start_time, 2)
            await event.respond(
                f"🎉 **SUCCESS! Username Claimed!**\n\n"
                f"📌 Username: `@{target_username}`\n"
                f"👤 Account: `{active_session_name}`\n"
                f"⏱️ Time Taken: **{elapsed} seconds**\n"
                f"🔄 Total Attempts: {attempts}"
            )
            is_sniping = False
            break
            
        except UsernameOccupiedError:
            # Short delay for continuous high-speed loop without getting banned instantly
            await asyncio.sleep(random.uniform(1.2, 1.8))
        except FloodWaitError as e:
            await event.respond(f"⚠️ FloodWait: Sleeping for {e.seconds} seconds...")
            await asyncio.sleep(e.seconds)
        except UsernameNotModifiedError:
            # Means the username is already owned by this channel
            await event.respond(f"✅ Username `@{target_username}` is already successfully set on the channel!")
            is_sniping = False
            break
        except ChatAdminRequiredError:
            await event.respond(f"❌ Error: Account is not an admin in the target channel.")
            is_sniping = False
            break
        except ChannelsAdminPublicTooMuchError:
            await event.respond(f"❌ Error: Account has reached max public channel limit.")
            is_sniping = False
            break
        except Exception as e:
            # Catch minor connection glitches and continue looping without stopping
            await asyncio.sleep(1.0)

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
    
    try:
        if TARGET_CHANNEL.startswith('-') or TARGET_CHANNEL.isdigit():
            channel_entity = await active_client.get_entity(int(TARGET_CHANNEL))
        else:
            channel_entity = await active_client.get_entity(TARGET_CHANNEL)
    except Exception as e:
        await event.respond(f"❌ Failed to resolve channel: {e}\nMake sure the selected account has joined the channel.")
        return
        
    snipe_task = asyncio.create_task(run_snipe_loop(target_username, channel_entity, event))

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
        await event.respond(f"🟢 Actively sniping `@{active_target}` using account `{active_session_name}`")
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
            save_session_to_db(acc_name, session_str) # Saved permanently to SQLite DB
            await event.respond(f"✅ Account **{acc_name}** added & saved securely in database!\nUse `/select {acc_name}` to activate it.")
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
            save_session_to_db(acc_name, session_str) # Saved permanently to SQLite DB
            await event.respond(f"✅ Account **{acc_name}** added with 2FA & saved securely in database!\nUse `/select {acc_name}` to activate it.")
            del user_states[user_id]
        except Exception as e:
            await event.respond(f"❌ Incorrect Password! Please check and send your cloud password again:")

# --- MAIN STARTUP ---
def main():
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    print("[*] Keep-alive Flask server running.")
    print("[*] Master Bot is running with SQLite database storage...")
    bot.run_until_disconnected()

if __name__ == '__main__':
    main()
