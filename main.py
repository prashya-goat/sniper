import asyncio
import os
import shutil
import time
import random
import itertools
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
    return "Telegram Username Scanner Bot is Running!"

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

is_scanner_running = False
active_clients = []
user_states = {}
scanner_start_time = 0

# --- Stats Tracking ---
total_checked = 0
found_usernames = []
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


# --- Bulk Scanner Loop (Monitor & Alert Only - No Claiming) ---
async def bulk_scanner_loop():
    global is_scanner_running, active_clients, scanner_start_time, total_checked, found_usernames, account_stats_map
    
    try:
        total_accounts = len(active_clients)
        if total_accounts == 0:
            is_scanner_running = False
            return

        # 17,576 combinations generate karna (e.g., a_a_a, a_a_b ... z_z_z)
        letters = 'abcdefghijklmnopqrstuvwxyz'
        all_combinations = [f"{i}_{j}_{k}" for i, j, k in itertools.product(letters, repeat=3)]
        
        print(f"🚀 Bulk Scanner Loop started with {total_accounts} accounts checking {len(all_combinations)} combinations...")
        
        combo_index = 0
        total_combos = len(all_combinations)
        
        while is_scanner_running and combo_index < total_combos:
            
            for idx, client in enumerate(active_clients):
                if not is_scanner_running or combo_index >= total_combos:
                    break
                    
                client_index = idx + 1
                stats = account_stats_map[client_index]
                current_time = time.time()
                
                # 🛑 FloodWait Check
                if current_time < stats['flood_till']:
                    remaining_flood = int(stats['flood_till'] - current_time)
                    stats['status'] = f"⏳ FloodWait ({remaining_flood}s)"
                    continue  
                
                target = all_combinations[combo_index]
                combo_index += 1
                
                try:
                    stats['status'] = f"🟢 Checking @{target}"
                    total_checked += 1
                    stats['checked'] += 1
                    
                    result = await client(functions.account.CheckUsernameRequest(
                        username=target
                    ))
                    
                    if result:
                        # Agar available hai, toh sirf alert bhejo (No Channel Creation)
                        found_usernames.append(target)
                        print(f"🎉 FOUND AVAILABLE USERNAME: @{target}")
                        
                        await control_bot.send_message(
                            OWNER_ID,
                            f"🔥 **Available Username Found!**\n\n"
                            f"🎯 Username: `@{target}`\n"
                            f"👥 Checked by Account #{client_index}\n"
                            f"⚡ Jaldi jaakar claim kar le!"
                        )
                    else:
                        stats['status'] = f"🔴 @{target} (Taken)"
                        
                except FloodWaitError as e:
                    wait_sec = e.seconds
                    stats['flood_till'] = time.time() + wait_sec
                    stats['status'] = f"⚠️ FloodWait ({wait_sec}s)"
                    print(f"⚠️ Account #{client_index} hit FloodWait: {wait_sec}s")
                except Exception as e:
                    stats['status'] = f"❌ Error"
                    print(f"⚠️ Check error on @{target}: {e}")
                
                # ⏱️ Anti-Detection Jitter Delay (50s total cycle distributed among accounts)
                base_delay = 50.0 / total_accounts
                jitter = random.uniform(-1.0, 2.0)
                sleep_time = max(1.5, base_delay + jitter)
                
                await asyncio.sleep(sleep_time)
                
            await asyncio.sleep(random.uniform(1.0, 2.5))
            
        is_scanner_running = False
        await control_bot.send_message(OWNER_ID, "🏁 **Scanning Complete!** Saare 17,576 combinations check ho chuke hain.")
        
    except Exception as loop_err:
        is_scanner_running = False
        print(f"❌ Scanner Loop Crashed: {loop_err}")


# --- Inline Keyboard Menu ---
def get_main_menu_buttons():
    return [
        [Button.inline("➕ Add Sessions", b"add_string"), Button.inline("📂 View Sessions", b"list_sessions")],
        [Button.inline("🚀 Start Scan (17k+)", b"start_scan"), Button.inline("📊 Check Status", b"check_stat")],
        [Button.inline("🛑 Stop Scanner", b"stop_scanner")]
    ]


# --- Bot Commands ---

@control_bot.on(events.NewMessage(pattern='/start'))
async def start_cmd(event):
    if event.sender_id != OWNER_ID:
        return
    await event.respond(
        "🤖 **Telegram 5-Character Pattern Scanner**\n\n"
        "Ye bot 17,576 combinations (`a_a_a` to `z_z_z`) ko bina claim kiye chupchaap monitor karega aur available milne par alert dega.",
        buttons=get_main_menu_buttons()
    )


@control_bot.on(events.NewMessage(pattern='/scan'))
async def scan_cmd(event):
    global is_scanner_running, active_clients, scanner_start_time, total_checked, found_usernames, account_stats_map
    if event.sender_id != OWNER_ID:
        return
        
    if is_scanner_running:
        await event.respond("⚠️ Scanner pehle se hi chal raha hai!")
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
                account_stats_map[client_index] = {'checked': 0, 'status': '🟢 Ready', 'flood_till': 0}
            else:
                account_stats_map[client_index] = {'checked': 0, 'status': '⚠️ Unauthorized', 'flood_till': 0}
                await client.disconnect()
        except Exception:
            pass
            
    if not active_clients:
        await event.respond("❌ Koi bhi valid session active nahi hai!")
        return
        
    is_scanner_running = True
    scanner_start_time = time.time()
    total_checked = 0
    found_usernames.clear()
    
    await event.respond(
        f"🚀 **Bulk Scanner Started!**\n"
        f"👥 Active Accounts: `{len(active_clients)}`\n"
        f"📋 Target: `17,576 combinations (a_a_a to z_z_z)`\n"
        f"🔔 Mode: Monitor & Alert Only (No claiming)",
        buttons=get_main_menu_buttons()
    )
    
    asyncio.create_task(bulk_scanner_loop())


@control_bot.on(events.NewMessage(pattern='/stat'))
async def stat_cmd(event):
    global is_scanner_running, total_checked, found_usernames, scanner_start_time, account_stats_map
    if event.sender_id != OWNER_ID:
        return
        
    status = "🟢 **Running**" if is_scanner_running else "🔴 **Stopped**"
    elapsed = round(time.time() - scanner_start_time, 1) if is_scanner_running else 0
    
    msg = (
        f"📊 **Scanner Statistics**\n\n"
        f"⚙️ **Status:** {status}\n"
        f"🔄 **Total Checked:** `{total_checked} / 17,576`\n"
        f"🎉 **Found Available:** `{len(found_usernames)}`\n"
        f"⏱️ **Elapsed Time:** `{elapsed}s`\n\n"
        f"📋 **Account Wise Status:**\n"
    )
    
    for acc_id, data in account_stats_map.items():
        msg += f"- **Account #{acc_id}** ➔ Checked: `{data['checked']}` | {data['status']}\n"
        
    if found_usernames:
        msg += f"\n🔥 **Available List:**\n" + ", ".join(f"`@{u}`" for u in found_usernames[:10])
        
    await event.respond(msg, buttons=get_main_menu_buttons())


@control_bot.on(events.NewMessage(pattern='/stop'))
async def stop_cmd(event):
    global is_scanner_running
    if event.sender_id != OWNER_ID:
        return
    is_scanner_running = False
    await event.respond("🛑 Scanner successfully rok diya gaya hai.")


# --- Callback Handlers ---
@control_bot.on(events.CallbackQuery)
async def callback_handler(event):
    global is_scanner_running
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
    elif data == b"start_scan":
        # Simulate /scan command trigger
        event.text = "/scan"
        await scan_cmd(event)
    elif data == b"check_stat":
        event.text = "/stat"
        await stat_cmd(event)
    elif data == b"stop_scanner":
        is_scanner_running = False
        await event.respond("🛑 Scanner stopped.")
        
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
    print("Starting Scanner Control Bot...")
    await control_bot.start(bot_token=BOT_TOKEN)
    await start_session_otp_listeners()
    print("✅ Bot is online and ready!")
    await control_bot.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
