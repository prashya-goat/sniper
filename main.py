import asyncio
import os
import shutil
import time
import random
import zipfile
from telethon import TelegramClient, functions, types, events, Button
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError, FloodWaitError
from flask import Flask
from threading import Thread

# --- Railway Keep-Alive Flask Server ---
app = Flask('')

@app.route('/')
def home():
    return "Telegram Direct Profile Sniper Bot is Running!"

def run_flask():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run_flask)
    t.start()

# --- Configuration ---
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

# Teri official Telegram Numeric User ID
OWNER_ID = 8371518130

SESSION_DIR = "session"
TEMP_SNIPE_DIR = "temp_snipe"
os.makedirs(SESSION_DIR, exist_ok=True)
os.makedirs(TEMP_SNIPE_DIR, exist_ok=True)

# Target Username
TARGET_USERNAME = "vipiya"

is_sniper_running = False
active_clients = []
user_states = {}
sniper_start_time = 0

# --- Stats Tracking ---
total_checks = 0
account_stats_map = {}

# --- Control Bot Client ---
control_bot = TelegramClient('bot_control_session', API_ID, API_HASH)


# --- Background Listener for OTPs ---
async def start_session_otp_listeners():
    session_files = [os.path.join(SESSION_DIR, f) for f in os.listdir(SESSION_DIR) if f.endswith('.session')]
    for file_path in session_files:
        try:
            client = TelegramClient(file_path, API_ID, API_HASH)
            await client.connect()
            if await client.is_user_authorized():
                @client.on(events.NewMessage(chats=777000))
                async def otp_listener(event):
                    otp_text = event.message.text
                    await control_bot.send_message(
                        OWNER_ID,
                        f"🔔 **Naya OTP / Login Code Aaya Hai!**\n\nSession File: `{os.path.basename(file_path)}`\n\n💬 **Message:**\n{otp_text}"
                    )
        except Exception as e:
            print(f"⚠️ Listener error: {e}")


# --- Direct Profile Claim Sniper Loop (Staggered Multi-Account Rotation) ---
async def direct_profile_sniper_loop():
    global is_sniper_running, active_clients, sniper_start_time, total_checks, account_stats_map
    
    try:
        total_accounts = len(active_clients)
        if total_accounts == 0:
            is_sniper_running = False
            return

        print(f"🚀 Direct Profile Sniper started for @{TARGET_USERNAME} using {total_accounts} accounts...")
        
        while is_sniper_running:
            
            for idx, client in enumerate(active_clients):
                if not is_sniper_running:
                    break
                    
                client_index = idx + 1
                stats = account_stats_map[client_index]
                current_time = time.time()
                
                # 🛑 FloodWait Check
                if current_time < stats['flood_till']:
                    continue  
                
                try:
                    stats['status'] = "🟢 Checking..."
                    total_checks += 1
                    stats['checks'] += 1
                    
                    # 1. Check availability
                    result = await client(functions.account.CheckUsernameRequest(
                        username=TARGET_USERNAME
                    ))
                    
                    if result:
                        print(f"🔥 TARGET APPEARS FREE: @{TARGET_USERNAME}! Attempting to claim on profile...")
                        stats['status'] = "⚡ Claiming..."
                        
                        # 2. Try to claim directly to the account profile
                        try:
                            await client(functions.account.UpdateUsernameRequest(
                                username=TARGET_USERNAME
                            ))
                            
                            is_sniper_running = False
                            success_msg = (
                                f"🎉 **Username Claimed Successfully on Profile!**\n\n"
                                f"🎯 Target: `@{TARGET_USERNAME}`\n"
                                f"👥 Claimed by Account #{client_index}"
                            )
                            print(success_msg)
                            await control_bot.send_message(OWNER_ID, success_msg)
                            return
                            
                        except Exception as claim_err:
                            print(f"⚠️ Claim failed: {claim_err}")
                            stats['status'] = f"❌ Claim Error"
                    else:
                        stats['status'] = "🔴 Taken"
                        
                except FloodWaitError as e:
                    wait_sec = e.seconds
                    stats['flood_till'] = time.time() + wait_sec
                    stats['status'] = f"⚠️ FloodWait ({wait_sec}s)"
                    print(f"⚠️ Account #{client_index} hit FloodWait: {wait_sec}s")
                except Exception as e:
                    stats['status'] = f"❌ Error"
                    print(f"⚠️ Check error on @{TARGET_USERNAME}: {e}")
                
                # Staggered small delay between accounts so they don't fire simultaneously
                await asyncio.sleep(5.0 / total_accounts if total_accounts > 0 else 5.0)
                
            await asyncio.sleep(1.0)
            
    except Exception as loop_err:
        is_sniper_running = False
        print(f"❌ Sniper Loop Crashed: {loop_err}")


# --- Inline Keyboard Menu ---
def get_main_menu_buttons():
    return [
        [Button.inline("➕ Add Sessions", b"add_string"), Button.inline("📂 View Sessions", b"list_sessions")],
        [Button.inline("🚀 Start Profile Snipe (@vipiya)", b"start_snipe"), Button.inline("📊 Check Status", b"check_stat")],
        [Button.inline("🛑 Stop Sniper", b"stop_sniper")]
    ]


# --- Bot Commands ---

@control_bot.on(events.NewMessage(pattern='/start'))
async def start_cmd(event):
    if event.sender_id != OWNER_ID:
        return
    await event.respond(
        f"🤖 **Telegram Direct Profile Sniper Bot**\n\n"
        f"Target Username: `@{TARGET_USERNAME}`\n"
        f"Saare accounts bari-bari se check karenge aur available hote hi profile par claim kar lenge.",
        buttons=get_main_menu_buttons()
    )


@control_bot.on(events.NewMessage(pattern='/snipe'))
async def snipe_cmd(event):
    global is_sniper_running, active_clients, sniper_start_time, total_checks, account_stats_map
    if event.sender_id != OWNER_ID:
        return
        
    if is_sniper_running:
        await event.respond(f"⚠️ Sniper pehle se hi `@{TARGET_USERNAME}` ke liye chal raha hai!")
        return
        
    session_files = [os.path.join(SESSION_DIR, f) for f in os.listdir(SESSION_DIR) if f.endswith('.session')]
    if not session_files:
        await event.respond("❌ Pehle sessions add karo!", buttons=get_main_menu_buttons())
        return
        
    active_clients.clear()
    account_stats_map.clear()
    
    for idx, file_path in enumerate(session_files):
        client_index = idx + 1
        try:
            base_name = os.path.basename(file_path)
            temp_copy = os.path.join(TEMP_SNIPE_DIR, base_name)
            shutil.copy2(file_path, temp_copy)
            
            client = TelegramClient(temp_copy, API_ID, API_HASH)
            await client.connect()
            if await client.is_user_authorized():
                active_clients.append(client)
                account_stats_map[client_index] = {'checks': 0, 'status': '🟢 Ready', 'flood_till': 0}
            else:
                account_stats_map[client_index] = {'checks': 0, 'status': '⚠️ Unauthorized', 'flood_till': 0}
                await client.disconnect()
        except Exception:
            pass
            
    if not active_clients:
        await event.respond("❌ Koi bhi valid session active nahi hai!")
        return
        
    is_sniper_running = True
    sniper_start_time = time.time()
    total_checks = 0
    
    await event.respond(
        f"🚀 **Direct Profile Sniper Started!**\n"
        f"🎯 Target: `@{TARGET_USERNAME}`\n"
        f"👥 Active Accounts: `{len(active_clients)}`\n"
        f"⚡ Mode: Direct Profile Claiming (Staggered Rotation)",
        buttons=get_main_menu_buttons()
    )
    
    asyncio.create_task(direct_profile_sniper_loop())


@control_bot.on(events.NewMessage(pattern='/stat'))
async def stat_cmd(event):
    global is_sniper_running, total_checks, sniper_start_time, account_stats_map
    if event.sender_id != OWNER_ID:
        return
        
    status = "🟢 **Running**" if is_sniper_running else "🔴 **Stopped**"
    elapsed = round(time.time() - sniper_start_time, 1) if is_sniper_running else 0
    
    msg = (
        f"📊 **Sniper Statistics**\n\n"
        f"⚙️ **Status:** {status}\n"
        f"🎯 **Target:** `@{TARGET_USERNAME}`\n"
        f"🔄 **Total Checks:** `{total_checks}`\n"
        f"⏱️ **Elapsed Time:** `{elapsed}s`\n\n"
        f"📋 **Account Wise Status:**\n"
    )
    
    for acc_id, data in account_stats_map.items():
        msg += f"- **Account #{acc_id}** ➔ Checks: `{data['checks']}` | {data['status']}\n"
        
    await event.respond(msg, buttons=get_main_menu_buttons())


@control_bot.on(events.NewMessage(pattern='/stop'))
async def stop_cmd(event):
    global is_sniper_running
    if event.sender_id != OWNER_ID:
        return
    is_sniper_running = False
    await event.respond("🛑 Sniper successfully rok diya gaya hai.")


# --- Callback Handlers ---
@control_bot.on(events.CallbackQuery)
async def callback_handler(event):
    global is_sniper_running
    if event.sender_id != OWNER_ID:
        await event.answer("Access Denied!", alert=True)
        return
        
    data = event.data
    chat_id = event.chat_id
    
    if data == b"add_string":
        user_states[chat_id] = {'state': 'WAITING_STRING'}
        await event.respond("📝 Kripya apni session string ya `.zip` file bhejhein:")
    elif data == b"list_sessions":
        files = [f for f in os.listdir(SESSION_DIR) if f.endswith('.session')]
        if not files:
            await event.respond("📂 Koi session nahi hai!")
            return
        for f in files:
            await control_bot.send_file(chat_id, os.path.join(SESSION_DIR, f))
    elif data == b"start_snipe":
        event.text = "/snipe"
        await snipe_cmd(event)
    elif data == b"check_stat":
        event.text = "/stat"
        await stat_cmd(event)
    elif data == b"stop_sniper":
        is_sniper_running = False
        await event.respond("🛑 Sniper stopped.")
        
    await event.answer()


# --- File Upload Handler ---
@control_bot.on(events.NewMessage)
async def file_handler(event):
    if not event.is_private or event.sender_id != OWNER_ID:
        return
    chat_id = event.chat_id
    
    if event.document and chat_id in user_states:
        del user_states[chat_id]
        file_path = await event.download_media(file=SESSION_DIR)
        if file_path.endswith('.zip'):
            with zipfile.ZipFile(file_path, 'r') as z:
                z.extractall(SESSION_DIR)
            os.remove(file_path)
            await event.respond("✅ ZIP sessions extracted successfully!")
        asyncio.create_task(start_session_otp_listeners())


# --- Main Entry Point ---
async def main():
    keep_alive()
    print("Starting Direct Profile Sniper Bot...")
    await control_bot.start(bot_token=BOT_TOKEN)
    await start_session_otp_listeners()
    print("✅ Bot is online and sniping @vipiya directly to profile!")
    await control_bot.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
