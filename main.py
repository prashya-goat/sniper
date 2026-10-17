import asyncio
import os
import shutil
import time
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
    return "Telegram Smart Sniper Bot is Running!"

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

current_target = None
active_clients = []
is_sniper_running = False
user_states = {}
snipe_start_time = 0

# --- Control Bot Client ---
control_bot = TelegramClient('bot_control_session', API_ID, API_HASH)


# --- Background Listener for Auto OTP Forwarding from Session Accounts ---
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
                
                print(f"👂 OTP Listener active for session: {os.path.basename(file_path)}")
        except Exception as e:
            print(f"⚠️ Could not start listener for {file_path}: {e}")


# --- Smart Rotational Sniper Master Loop (Staggered Delay Logic) ---
async def rotational_sniper_loop():
    global is_sniper_running, current_target, active_clients, snipe_start_time
    
    total_accounts = len(active_clients)
    if total_accounts == 0:
        is_sniper_running = False
        return

    # User ke kehne ke anusar: Har account ke beech ka gap (jaise 8-10 seconds)
    # Taaki saare accounts ek sath hit na karein aur loop smooth chale.
    account_delay = 10.0 if total_accounts > 1 else 5.0
    
    print(f"🚀 Rotational Sniper started with {total_accounts} accounts targeting @{current_target}...")
    
    while is_sniper_running and current_target:
        for idx, client in enumerate(active_clients):
            if not is_sniper_running or not current_target:
                break
                
            client_index = idx + 1
            try:
                print(f"🔍 Account {client_index}/{total_accounts} checking @{current_target}...")
                result = await client(functions.account.CheckUsernameRequest(
                    username=current_target
                ))
                
                if result:
                    time_taken = round(time.time() - snipe_start_time, 2)
                    print(f"🎉 SUCCESS! Username @{current_target} is available! Grabbed by Account {client_index} in {time_taken} seconds.")
                    grabbed_user = current_target
                    is_sniper_running = False  
                    
                    try:
                        channel = await client(functions.channels.CreateChannelRequest(
                            title=f"Sniped {grabbed_user}",
                            about="Secured by Telegram Sniper Bot",
                            megagroup=False
                        ))
                        channel_id = channel.chats[0].id
                        
                        await client(functions.channels.UpdateUsernameRequest(
                            channel=channel_id,
                            username=grabbed_user
                        ))
                        
                        invite = await client(functions.messages.ExportChatInviteRequest(peer=channel_id))
                        
                        await control_bot.send_message(
                            OWNER_ID, 
                            f"🎉 **Username Sniped Successfully!**\n\n"
                            f"🎯 Target: `@{grabbed_user}`\n"
                            f"⏱️ **Time Taken:** `{time_taken} seconds`\n"
                            f"👥 Grabbed by Account #{client_index}\n\n"
                            f"🔗 Join this channel quickly to claim ownership:\n{invite.link}"
                        )
                        
                        print(f"⏳ Waiting for Owner (ID: {OWNER_ID}) to join the channel...")
                        while True:
                            await asyncio.sleep(5)
                            try:
                                user_entity = await client.get_entity(OWNER_ID)
                                
                                is_member = False
                                async for user in client.iter_participants(channel_id):
                                    if user.id == OWNER_ID:
                                        is_member = True
                                        break
                                
                                if is_member:
                                    await client(functions.channels.EditAdminRequest(
                                        channel=channel_id,
                                        user_id=user_entity.id,
                                        admin_rights=types.ChatAdminRights(
                                            change_info=True, post_messages=True, edit_messages=True,
                                            delete_messages=True, invite_users=True, pin_messages=True,
                                            manage_call=True, manage_topics=True, invite_link=True, admin=True
                                        ),
                                        rank="Owner"
                                    ))
                                    await control_bot.send_message(OWNER_ID, f"👑 Ownership transferred successfully for `@{grabbed_user}`!")
                                    
                                    try:
                                        await client(functions.channels.LeaveChannelRequest(channel=channel_id))
                                        print("👋 Sniper account left the channel successfully.")
                                    except Exception as leave_err:
                                        print(f"⚠️ Could not leave channel: {leave_err}")
                                        
                                    break
                            except Exception:
                                pass
                    except Exception as ex:
                        print(f"❌ Error during channel claiming: {ex}")
                    return
                else:
                    print(f"[-] Account {client_index}: @{current_target} is taken.")
                    
            except FloodWaitError as e:
                err_msg = f"⚠️ Account {client_index} hit FloodWait: sleeping for {e.seconds} seconds."
                print(err_msg)
                await control_bot.send_message(OWNER_ID, err_msg)
                await asyncio.sleep(e.seconds)
            except Exception as e:
                print(f"⚠️ Account {client_index} check error: {e}")
                
            # Har account ki request ke beech mein user ka diya hua gap delay
            await asyncio.sleep(account_delay)


# --- Inline Keyboard Menu ---
def get_main_menu_buttons():
    return [
        [Button.inline("➕ Add via String/File", b"add_string"), Button.inline("📱 Add via Phone", b"add_phone")],
        [Button.inline("📂 View Sessions", b"list_sessions"), Button.inline("🚀 Start Snipe", b"menu_snipe")],
        [Button.inline("🛑 Stop Sniper", b"stop_sniper")]
    ]


# --- Bot Commands & Button Handlers ---

@control_bot.on(events.NewMessage(pattern='/start'))
async def start_cmd(event):
    if event.sender_id != OWNER_ID:
        return
    await event.respond(
        "🤖 **Telegram Smart Sniper Control Panel**\n\n"
        "Neche diye gaye buttons ka use karke apne sessions manage karo:",
        buttons=get_main_menu_buttons()
    )


@control_bot.on(events.CallbackQuery)
async def callback_query_handler(event):
    if event.sender_id != OWNER_ID:
        await event.answer("Access Denied!", alert=True)
        return
    
    data = event.data
    chat_id = event.chat_id
    
    if data == b"add_string":
        user_states[chat_id] = {'state': 'WAITING_STRING'}
        await event.respond("📝 **Session Add karne ke liye:**\n\nKripya apni Telethon session string ya `.zip` / `.session` file yahan bhejhein:", buttons=get_main_menu_buttons())
        
    elif data == b"add_phone":
        user_states[chat_id] = {'state': 'WAITING_PHONE'}
        await event.respond("📱 **Phone Number se Login karne ke liye:**\n\nKripya apna phone number country code ke sath bhejhein (jaise `+919876543210`):", buttons=get_main_menu_buttons())
        
    elif data == b"list_sessions":
        files = [f for f in os.listdir(SESSION_DIR) if f.endswith('.session')]
        if not files:
            await event.respond("📂 Koi session file saved nahi hai!", buttons=get_main_menu_buttons())
            return
        
        await event.respond(f"📂 Found **{len(files)}** session files. Sending them now...")
        for file in files:
            await control_bot.send_file(chat_id, os.path.join(SESSION_DIR, file), caption=f"📁 `{file}`")
        await control_bot.send_message(chat_id, "✅ Saari files bhej di gayi hain.", buttons=get_main_menu_buttons())
        
    elif data == b"menu_snipe":
        await event.respond("🎯 Target set karne ke liye command use karein:\n\n👉 `/snipe <username>`\n(Example: `/snipe PARSHYA`)", buttons=get_main_menu_buttons())
        
    elif data == b"stop_sniper":
        global is_sniper_running
        is_sniper_running = False
        await event.respond("🛑 Sniper successfully rok diya gaya hai.", buttons=get_main_menu_buttons())
    
    await event.answer()


# --- Conversation Handler ---

@control_bot.on(events.NewMessage)
async def message_handler(event):
    if not event.is_private:
        return
    if event.sender_id != OWNER_ID:
        return
    
    chat_id = event.chat_id
    
    if event.document and chat_id in user_states and user_states[chat_id].get('state') == 'WAITING_STRING':
        del user_states[chat_id]
        try:
            await event.respond("⏳ Downloading and processing file...")
            file_path = await event.download_media(file=SESSION_DIR)
            
            saved_count = 0
            if file_path.endswith('.zip'):
                with zipfile.ZipFile(file_path, 'r') as zip_ref:
                    for filename in zip_ref.namelist():
                        if filename.endswith('.session'):
                            zip_ref.extract(filename, SESSION_DIR)
                            saved_count += 1
                os.remove(file_path)
                await event.respond(f"✅ **ZIP file processed successfully!** Extracted `{saved_count}` session file(s).", buttons=get_main_menu_buttons())
            elif file_path.endswith('.session'):
                await event.respond(f"✅ **Session file saved successfully!**", buttons=get_main_menu_buttons())
            else:
                os.remove(file_path)
                await event.respond("❌ Invalid file format! Kripya `.zip` ya `.session` file bhejhein.", buttons=get_main_menu_buttons())
            
            asyncio.create_task(start_session_otp_listeners())
        except Exception as e:
            err_text = f"❌ Error processing file: {e}"
            await event.respond(err_text, buttons=get_main_menu_buttons())
        return

    if not event.text:
        return
        
    text = event.text.strip()
    if text.startswith('/'):
        return
        
    if chat_id not in user_states:
        return
        
    state_data = user_states[chat_id]
    state = state_data.get('state')
    
    if state == 'WAITING_STRING':
        del user_states[chat_id]
        try:
            await event.respond("⏳ Testing session string...")
            test_client = TelegramClient(StringSession(text), API_ID, API_HASH)
            await test_client.connect()
            
            if await test_client.is_user_authorized():
                me = await test_client.get_me()
                name = f"{me.first_name} {me.last_name or ''}".strip()
                phone = str(me.phone) if hasattr(me, 'phone') else "NoPhone"
                
                file_name = f"session_{me.id}.session"
                file_path = os.path.join(SESSION_DIR, file_name)
                
                await test_client.disconnect()
                
                file_client = TelegramClient(file_path, API_ID, API_HASH)
                await file_client.connect()
                temp_str_client = TelegramClient(StringSession(text), API_ID, API_HASH)
                await temp_str_client.connect()
                
                file_client.session.auth_key = temp_str_client.session.auth_key
                file_client.session.dc_id = temp_str_client.session.dc_id
                file_client.session.server_address = temp_str_client.session.server_address
                file_client.session.port = temp_str_client.session.port
                file_client.session.save()
                
                await temp_str_client.disconnect()
                await file_client.disconnect()
                
                await event.respond(f"✅ **Session Saved Successfully!**\n👤 Name: {name}\n📱 Phone: `{phone}`", buttons=get_main_menu_buttons())
                asyncio.create_task(start_session_otp_listeners())
            else:
                await event.respond("❌ Session invalid ya unauthorized hai!", buttons=get_main_menu_buttons())
                await test_client.disconnect()
        except Exception as e:
            await event.respond(f"❌ Error: {e}", buttons=get_main_menu_buttons())
            
    elif state == 'WAITING_PHONE':
        phone_number = text
        try:
            await event.respond("⏳ Sending OTP request to Telegram...")
            temp_file = f"temp_login_{chat_id}.session"
            client = TelegramClient(temp_file, API_ID, API_HASH)
            await client.connect()
            
            sent_code = await client.send_code_request(phone_number)
            user_states[chat_id] = {
                'state': 'WAITING_OTP',
                'phone': phone_number,
                'client': client,
                'phone_code_hash': sent_code.phone_code_hash,
                'temp_file': temp_file
            }
            await event.respond("✅ OTP bhej diya gaya hai! Kripya apna **OTP code** yahan bhejhein:")
        except Exception as e:
            await event.respond(f"❌ Error sending code: {e}", buttons=get_main_menu_buttons())
            del user_states[chat_id]
            
    elif state == 'WAITING_OTP':
        otp_code = text
        client = state_data['client']
        phone = state_data['phone']
        phone_code_hash = state_data['phone_code_hash']
        temp_file = state_data['temp_file']
        
        try:
            await client.sign_in(phone=phone, code=otp_code, phone_code_hash=phone_code_hash)
            me = await client.get_me()
            await client.disconnect()
            
            perm_file = os.path.join(SESSION_DIR, f"session_{me.id}.session")
            if os.path.exists(perm_file):
                os.remove(perm_file)
            os.rename(temp_file, perm_file)
            
            del user_states[chat_id]
            await event.respond(f"✅ **Account Login Successful & Saved!**\n👤 Name: {me.first_name}", buttons=get_main_menu_buttons())
            asyncio.create_task(start_session_otp_listeners())
            
        except SessionPasswordNeededError:
            user_states[chat_id] = {
                'state': 'WAITING_2FA',
                'client': client,
                'temp_file': temp_file
            }
            await event.respond("🔐 Account par **2FA** laga hua hai. Kripya apna **2FA Password** yahan bhejhein:")
        except Exception as e:
            await event.respond(f"❌ Error signing in: {e}", buttons=get_main_menu_buttons())
            try:
                await client.disconnect()
            except:
                pass
            del user_states[chat_id]
            
    elif state == 'WAITING_2FA':
        password = text
        client = state_data['client']
        temp_file = state_data['temp_file']
        
        try:
            await client.sign_in(password=password)
            me = await client.get_me()
            await client.disconnect()
            
            perm_file = os.path.join(SESSION_DIR, f"session_{me.id}.session")
            if os.path.exists(perm_file):
                os.remove(perm_file)
            os.rename(temp_file, perm_file)
            
            del user_states[chat_id]
            await event.respond(f"✅ **2FA Verified & Session Saved!**\n👤 Name: {me.first_name}", buttons=get_main_menu_buttons())
            asyncio.create_task(start_session_otp_listeners())
            
        except Exception as e:
            await event.respond(f"❌ Invalid 2FA password: {e}", buttons=get_main_menu_buttons())
            try:
                await client.disconnect()
            except:
                pass
            del user_states[chat_id]


# --- Snipe Command ---

@control_bot.on(events.NewMessage(pattern='/snipe'))
async def snipe_cmd(event):
    global is_sniper_running, current_target, active_clients, snipe_start_time
    if event.sender_id != OWNER_ID:
        return
    
    args = event.text.split(' ', 1)
    if len(args) < 2:
        await event.respond("⚠️ Format: `/snipe <username>` (e.g., `/snipe PARSHYA`)")
        return
        
    current_target = args[1].strip().replace("@", "")
    
    if is_sniper_running:
        await event.respond(f"🔄 Target updated to `@{current_target}`!")
        return
        
    session_files = [os.path.join(SESSION_DIR, f) for f in os.listdir(SESSION_DIR) if f.endswith('.session')]
    if not session_files:
        await event.respond("❌ Koi session file nahi mili! Pehle sessions add karo.", buttons=get_main_menu_buttons())
        return
        
    # Clear temp folder before copying
    for f in os.listdir(TEMP_SNIPE_DIR):
        try:
            os.remove(os.path.join(TEMP_SNIPE_DIR, f))
        except:
            pass

    active_clients.clear()
    for file_path in session_files:
        try:
            base_name = os.path.basename(file_path)
            temp_copy_path = os.path.join(TEMP_SNIPE_DIR, base_name)
            shutil.copy2(file_path, temp_copy_path)
            
            client = TelegramClient(temp_copy_path, API_ID, API_HASH)
            await client.connect()
            is_auth = await client.is_user_authorized()
            if is_auth:
                active_clients.append(client)
            else:
                err_msg = f"⚠️ Session Unauthorized: {base_name}"
                print(err_msg)
                await control_bot.send_message(OWNER_ID, err_msg)
                await client.disconnect()
        except Exception as e:
            err_msg = f"❌ Session Error ({os.path.basename(file_path)}): {e}"
            print(err_msg)
            await control_bot.send_message(OWNER_ID, err_msg)
            
    total_accounts = len(active_clients)
    if total_accounts == 0:
        await event.respond("❌ Ek bhi valid session file nahi chali! (Error details upar bhej di gayi hain)")
        return
        
    is_sniper_running = True
    snipe_start_time = time.time()  # Timer start
    
    await event.respond(
        f"🚀 **Rotational Sniper Started!**\n"
        f"🎯 Target: `@{current_target}`\n"
        f"👥 Active Accounts: **{total_accounts}**\n"
        f"⏱️ Staggered Delay Mode Active.",
        buttons=get_main_menu_buttons()
    )
    
    # Background task for rotational sequential checks
    asyncio.create_task(rotational_sniper_loop())

@control_bot.on(events.NewMessage(pattern='/stopsniper'))
async def stop_sniper_cmd(event):
    global is_sniper_running
    if event.sender_id != OWNER_ID:
        return
    is_sniper_running = False
    await event.respond("🛑 Sniper stopped successfully.")


# --- Main Async Entry Point ---
async def main():
    keep_alive()
    print("Starting Telegram control bot...")
    await control_bot.start(bot_token=BOT_TOKEN)
    await start_session_otp_listeners()
    print("✅ Control bot started successfully and listening for messages & OTPs!")
    await control_bot.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
