#!/usr/bin/env python3
import os
import logging
import io
import zipfile
import subprocess
import tempfile
import shutil
import json
import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

# ===== BOT CONFIGURATION =====
BOT_TOKEN = "7822750441:AAGnM-i42XsSTv1jywj4OEnTYMDAAFRHzUg"
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB Telegram limit
ADMIN_ID = 7278872449  # Admin user ID (@devkushwaha8970)
ADMIN_USERNAME = "@devkushwaha8970"

# Bot settings file
SETTINGS_FILE = "bot_settings.json"

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ===== ADMIN SYSTEM =====
def load_settings():
    """Load bot settings from file"""
    default_settings = {
        "maintenance": False,
        "user_limit": None,  # None means no limit
        "allowed_users": [ADMIN_ID],  # Admin is always allowed
        "banned_users": [],
        "total_users": 0,
        "active_users": 0,
        "downloads_count": 0,
        "start_time": time.time()
    }
    
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, 'r') as f:
                settings = json.load(f)
                # Ensure admin is always in allowed_users
                if ADMIN_ID not in settings.get("allowed_users", []):
                    settings["allowed_users"].append(ADMIN_ID)
                # Ensure default fields exist
                for key, value in default_settings.items():
                    if key not in settings:
                        settings[key] = value
                return settings
    except Exception as e:
        logger.error(f"Error loading settings: {e}")
    
    return default_settings

def save_settings(settings):
    """Save bot settings to file"""
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings, f, indent=4)
        return True
    except Exception as e:
        logger.error(f"Error saving settings: {e}")
        return False

def is_admin(user_id):
    """Check if user is admin"""
    return user_id == ADMIN_ID

def check_user_permission(user_id, settings):
    """Check if user has permission to use bot"""
    # Admin always has permission
    if is_admin(user_id):
        return True, "Admin access granted"
    
    # Check if banned
    if user_id in settings.get("banned_users", []):
        return False, "❌ You are banned from using this bot."
    
    # Check if in allowed users
    if user_id not in settings.get("allowed_users", []):
        return False, "❌ You don't have permission to use this bot.\n\nPlease ask admin for permission."
    
    # Check user limit
    user_limit = settings.get("user_limit")
    if user_limit is not None:
        active_users = settings.get("active_users", 0)
        if active_users >= user_limit:
            return False, f"❌ Bot user limit reached.\nLimit: {user_limit} users"
    
    return True, "Permission granted"

# ===== UTILITY FUNCTIONS =====
def create_keyboard():
    """Create download options keyboard"""
    keyboard = [
        [InlineKeyboardButton("🌐 Full Source Download", callback_data="full")],
        [InlineKeyboardButton("📄 Partial Download", callback_data="partial")],
        [InlineKeyboardButton("🚫 Cancel", callback_data="cancel")]
    ]
    return InlineKeyboardMarkup(keyboard)

def clean_url(url):
    """Clean and validate URL"""
    url = url.strip()
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    return url

def download_to_memory(url, download_type="full"):
    """Download website directly to memory (no disk storage)"""
    import tempfile
    
    # Create temporary directory in memory if possible
    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            if download_type == "full":
                # Full website download
                cmd = [
                    "wget",
                    "--mirror",
                    "--convert-links",
                    "--adjust-extension",
                    "--page-requisites",
                    "--no-parent",
                    "--no-check-certificate",
                    "-e", "robots=off",
                    "--user-agent=Mozilla/5.0",
                    "--quiet",
                    "-P", temp_dir,
                    url
                ]
            else:
                # Partial download
                cmd = [
                    "wget",
                    "-r",
                    "-l", "2",
                    "-k",
                    "-p",
                    "-E",
                    "--no-check-certificate",
                    "-e", "robots=off",
                    "--quiet",
                    "-P", temp_dir,
                    url
                ]
            
            # Run download
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            
            if result.returncode != 0:
                logger.error(f"Download failed: {result.stderr}")
                return None, "Download failed", 0
            
            # Create zip in memory
            zip_buffer = io.BytesIO()
            file_count = 0
            
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(temp_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        
                        # Read file and add to zip
                        try:
                            with open(file_path, 'rb') as f:
                                file_data = f.read()
                            
                            # Create relative path for zip
                            arcname = os.path.relpath(file_path, temp_dir)
                            zipf.writestr(arcname, file_data)
                            file_count += 1
                            
                        except Exception as e:
                            logger.warning(f"Could not add file {file}: {e}")
            
            zip_buffer.seek(0)
            file_size = zip_buffer.getbuffer().nbytes
            
            if file_size > MAX_FILE_SIZE:
                return None, f"File too large ({file_size/1024/1024:.1f}MB). Max 50MB.", 0
            
            return zip_buffer, None, file_count
            
        except subprocess.TimeoutExpired:
            return None, "Download timeout (2 minutes)", 0
        except Exception as e:
            logger.error(f"Download error: {e}")
            return None, str(e), 0

def create_direct_zip(url, download_type="full"):
    """Download and create zip directly without saving to disk"""
    # Create temporary directory
    temp_dir = tempfile.mkdtemp()
    
    try:
        if download_type == "full":
            cmd = f"""wget --mirror --convert-links --adjust-extension --page-requisites \
                    --no-parent --no-check-certificate -e robots=off \
                    --user-agent="Mozilla/5.0" --quiet -P "{temp_dir}" "{url}" """
        else:
            cmd = f"""wget -r -l 2 -k -p -E --no-check-certificate \
                    -e robots=off --quiet -P "{temp_dir}" "{url}" """
        
        # Execute download
        os.system(cmd)
        
        # Create zip in memory
        zip_buffer = io.BytesIO()
        file_count = 0
        
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as zipf:
            for root, dirs, files in os.walk(temp_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    try:
                        with open(file_path, 'rb') as f:
                            file_data = f.read()
                        
                        arcname = os.path.relpath(file_path, temp_dir)
                        zipf.writestr(arcname, file_data)
                        file_count += 1
                    except:
                        continue
        
        zip_buffer.seek(0)
        
        # Cleanup temp directory
        shutil.rmtree(temp_dir, ignore_errors=True)
        
        return zip_buffer, file_count
        
    except Exception as e:
        # Cleanup on error
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise e

# ===== TELEGRAM HANDLERS =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send welcome message"""
    user_id = update.effective_user.id
    settings = load_settings()
    
    # Check if bot is in maintenance
    if settings.get("maintenance", False):
        await update.message.reply_text(
            "🔧 **Bot is under maintenance**\n\n"
            "Please try again later.\n\n"
            "Admin: " + ADMIN_USERNAME
        )
        return
    
    # Check user permission
    allowed, message = check_user_permission(user_id, settings)
    if not allowed:
        await update.message.reply_text(message)
        return
    
    welcome_text = """
    🌐 **Direct Website Source Downloader** 🌐
    
    Send me any website URL, I'll download the source code and send it directly as a zip file!
    
    **How to use:**
    1. Send any website URL
    2. Choose download type (Full/Partial)
    3. Receive zip file directly in chat
    
    **Commands:**
    /start - Show this message
    /help - Show help
    /cancel - Cancel current operation
    
    Made with ❤️ by Khatab
    Admin: @uchiarex
    """
    
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send help message"""
    user_id = update.effective_user.id
    settings = load_settings()
    
    # Check if bot is in maintenance
    if settings.get("maintenance", False):
        await update.message.reply_text(
            "🔧 **Bot is under maintenance**\n\n"
            "Please try again later.\n\n"
            "Admin: " + ADMIN_USERNAME
        )
        return
    
    # Check user permission
    allowed, message = check_user_permission(user_id, settings)
    if not allowed:
        await update.message.reply_text(message)
        return
    
    help_text = """
    🤖 **Bot Help**
    
    **Download Types:**
    • **Full Source Download**: Complete website (all pages, images, CSS, JS)
    • **Partial Download**: Only main page and direct resources
    
    **Features:**
    • No files saved on disk
    • Direct zip file sent to Telegram
    • Fast download
    • Clean memory after sending
    
    **File Size Limit**: 50MB (Telegram restriction)
    
    **Examples:**
    • https://example.com
    • example.com
    • http://test-site.org
    
    **Admin Commands:**
    • /p [user_id] - Give permission to user
    • /ban [user_id] - Ban user
    • /unban [user_id] - Unban user
    • /lim [number] - Set user limit
    • /man - Toggle maintenance mode
    • /stats - Show bot statistics
    
    Note: Some websites may have protection.
    """
    
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming URL message"""
    user_id = update.effective_user.id
    settings = load_settings()
    
    # Check if bot is in maintenance
    if settings.get("maintenance", False):
        await update.message.reply_text(
            "🔧 **Bot is under maintenance**\n\n"
            "Please try again later.\n\n"
            "Admin: " + ADMIN_USERNAME
        )
        return
    
    # Check user permission
    allowed, message = check_user_permission(user_id, settings)
    if not allowed:
        await update.message.reply_text(message)
        return
    
    url = update.message.text.strip()
    
    # Store URL in context
    context.user_data['url'] = url
    
    # Clean URL
    clean_url_str = clean_url(url)
    
    # Ask for download type
    await update.message.reply_text(
        f"🌐 **Website URL Received**\n\n`{clean_url_str}`\n\nPlease choose download type:",
        parse_mode='Markdown',
        reply_markup=create_keyboard()
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button clicks"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    settings = load_settings()
    
    # Check if bot is in maintenance
    if settings.get("maintenance", False):
        await query.edit_message_text(
            "🔧 **Bot is under maintenance**\n\n"
            "Please try again later.\n\n"
            "Admin: " + ADMIN_USERNAME
        )
        return
    
    # Check user permission
    allowed, message = check_user_permission(user_id, settings)
    if not allowed:
        await query.edit_message_text(message)
        return
    
    user_data = context.user_data
    url = user_data.get('url')
    
    if not url:
        await query.edit_message_text("❌ No URL found. Please send URL again.")
        return
    
    if query.data == "cancel":
        await query.edit_message_text("🚫 Operation cancelled.")
        return
    
    # Determine download type
    download_type = query.data  # "full" or "partial"
    download_name = "Full Website" if download_type == "full" else "Partial Website"
    
    # Update message
    await query.edit_message_text(
        f"⏳ **Downloading {download_name}**\n\nURL: `{url}`\n\nPlease wait...",
        parse_mode='Markdown'
    )
    
    try:
        # Download and create zip directly
        await query.edit_message_text(f"📥 Downloading website...")
        zip_buffer, file_count = create_direct_zip(url, download_type)
        
        file_size = zip_buffer.getbuffer().nbytes
        file_size_mb = file_size / 1024 / 1024
        
        if file_size > MAX_FILE_SIZE:
            await query.edit_message_text(
                f"❌ **File Too Large**\n\nSize: {file_size_mb:.1f}MB\nLimit: 50MB\n\nTry partial download instead."
            )
            return
        
        # Create filename
        import time
        domain = url.replace("https://", "").replace("http://", "").split("/")[0]
        filename = f"{domain}_{download_type}_{int(time.time())}.zip"
        
        # Send file
        await query.edit_message_text(f"📤 Sending file ({file_size_mb:.1f}MB)...")
        
        caption = f"""
        ✅ **Website Source Downloaded!**
        
        **Details:**
        • Website: `{url}`
        • Type: {download_name}
        • File Size: {file_size_mb:.2f} MB
        • Files: {file_count}
        
        Made with ❤️ by Khatab
        Admin: @uchiarex
        """
        
        await context.bot.send_document(
            chat_id=query.message.chat_id,
            document=zip_buffer,
            filename=filename,
            caption=caption,
            parse_mode='Markdown'
        )
        
        # Update download count
        settings = load_settings()
        settings["downloads_count"] = settings.get("downloads_count", 0) + 1
        save_settings(settings)
        
        # Success message
        await query.edit_message_text(f"✅ **Done!** File sent successfully.\n\nFiles: {file_count}\nSize: {file_size_mb:.1f}MB")
        
    except Exception as e:
        logger.error(f"Error: {e}")
        await query.edit_message_text(f"❌ **Error**\n\n```{str(e)[:500]}```", parse_mode='Markdown')

# ===== ADMIN COMMANDS =====
async def permission_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Give permission to user /p [user_id]"""
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ Only admin can use this command.")
        return
    
    if not context.args:
        await update.message.reply_text("❌ Usage: `/p [user_id]`", parse_mode='Markdown')
        return
    
    try:
        target_user_id = int(context.args[0])
        settings = load_settings()
        
        if target_user_id in settings["allowed_users"]:
            await update.message.reply_text(f"ℹ️ User `{target_user_id}` already has permission.", parse_mode='Markdown')
            return
        
        settings["allowed_users"].append(target_user_id)
        
        # Remove from banned if exists
        if target_user_id in settings.get("banned_users", []):
            settings["banned_users"].remove(target_user_id)
        
        save_settings(settings)
        
        await update.message.reply_text(
            f"✅ User `{target_user_id}` has been given permission to use the bot.\n\n"
            f"Allowed users: {len(settings['allowed_users'])}",
            parse_mode='Markdown'
        )
        
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID. User ID must be a number.")

async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ban user /ban [user_id]"""
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ Only admin can use this command.")
        return
    
    if not context.args:
        await update.message.reply_text("❌ Usage: `/ban [user_id]`", parse_mode='Markdown')
        return
    
    try:
        target_user_id = int(context.args[0])
        settings = load_settings()
        
        if target_user_id == ADMIN_ID:
            await update.message.reply_text("❌ You cannot ban admin!")
            return
        
        if target_user_id in settings.get("banned_users", []):
            await update.message.reply_text(f"ℹ️ User `{target_user_id}` is already banned.", parse_mode='Markdown')
            return
        
        settings["banned_users"].append(target_user_id)
        
        # Remove from allowed if exists
        if target_user_id in settings.get("allowed_users", []):
            settings["allowed_users"].remove(target_user_id)
        
        save_settings(settings)
        
        await update.message.reply_text(
            f"✅ User `{target_user_id}` has been banned from using the bot.\n\n"
            f"Banned users: {len(settings['banned_users'])}",
            parse_mode='Markdown'
        )
        
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID. User ID must be a number.")

async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Unban user /unban [user_id]"""
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ Only admin can use this command.")
        return
    
    if not context.args:
        await update.message.reply_text("❌ Usage: `/unban [user_id]`", parse_mode='Markdown')
        return
    
    try:
        target_user_id = int(context.args[0])
        settings = load_settings()
        
        if target_user_id not in settings.get("banned_users", []):
            await update.message.reply_text(f"ℹ️ User `{target_user_id}` is not banned.", parse_mode='Markdown')
            return
        
        settings["banned_users"].remove(target_user_id)
        save_settings(settings)
        
        await update.message.reply_text(
            f"✅ User `{target_user_id}` has been unbanned.\n\n"
            f"Banned users: {len(settings['banned_users'])}",
            parse_mode='Markdown'
        )
        
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID. User ID must be a number.")

async def limit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set user limit /lim [number]"""
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ Only admin can use this command.")
        return
    
    if not context.args:
        await update.message.reply_text("❌ Usage: `/lim [number]`\nExample: `/lim 5` for 5 users\n`/lim 0` for no limit", parse_mode='Markdown')
        return
    
    try:
        limit = int(context.args[0])
        
        if limit < 0:
            await update.message.reply_text("❌ Limit must be 0 or positive number.")
            return
        
        settings = load_settings()
        
        if limit == 0:
            settings["user_limit"] = None
            await update.message.reply_text("✅ User limit removed (no limit).")
        else:
            settings["user_limit"] = limit
            await update.message.reply_text(f"✅ User limit set to {limit} users.")
        
        save_settings(settings)
        
    except ValueError:
        await update.message.reply_text("❌ Invalid number. Please enter a valid number.")

async def maintenance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggle maintenance mode /man"""
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ Only admin can use this command.")
        return
    
    settings = load_settings()
    settings["maintenance"] = not settings.get("maintenance", False)
    
    status = "ON 🔧" if settings["maintenance"] else "OFF ✅"
    
    save_settings(settings)
    
    await update.message.reply_text(
        f"✅ **Maintenance mode {status}**\n\n"
        f"Bot is now {'under maintenance' if settings['maintenance'] else 'active'}."
    )

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show bot statistics /stats"""
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ Only admin can use this command.")
        return
    
    settings = load_settings()
    
    # Calculate uptime
    uptime_seconds = time.time() - settings.get("start_time", time.time())
    days = int(uptime_seconds // 86400)
    hours = int((uptime_seconds % 86400) // 3600)
    minutes = int((uptime_seconds % 3600) // 60)
    seconds = int(uptime_seconds % 60)
    
    if days > 0:
        uptime_str = f"{days}d {hours}h {minutes}m {seconds}s"
    elif hours > 0:
        uptime_str = f"{hours}h {minutes}m {seconds}s"
    elif minutes > 0:
        uptime_str = f"{minutes}m {seconds}s"
    else:
        uptime_str = f"{seconds}s"
    
    # Get user limit display
    user_limit = settings.get("user_limit")
    user_limit_display = "No limit" if user_limit is None else f"{user_limit} users"
    
    stats_text = f"""
📊 **Bot Statistics**

**General:**
• Maintenance Mode: {'ON 🔧' if settings.get('maintenance') else 'OFF ✅'}
• User Limit: {user_limit_display}
• Total Downloads: {settings.get('downloads_count', 0)}
• Uptime: {uptime_str}

**Users:**
• Admin ID: {ADMIN_ID}
• Admin Username: {ADMIN_USERNAME}
• Allowed Users: {len(settings.get('allowed_users', []))}
• Banned Users: {len(settings.get('banned_users', []))}

**Allowed Users List:**
{', '.join([str(uid) for uid in settings.get('allowed_users', [])])}

**Banned Users List:**
{', '.join([str(uid) for uid in settings.get('banned_users', [])]) if settings.get('banned_users') else 'None'}

**System:**
• Settings File: {SETTINGS_FILE}
• Max File Size: {MAX_FILE_SIZE / 1024 / 1024} MB
• Bot Started: {time.ctime(settings.get('start_time', time.time()))}
    """
    
    await update.message.reply_text(stats_text, parse_mode='Markdown')

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel current operation"""
    context.user_data.clear()
    await update.message.reply_text("🚫 Operation cancelled.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all messages"""
    user_id = update.effective_user.id
    settings = load_settings()
    
    # Check if bot is in maintenance
    if settings.get("maintenance", False):
        await update.message.reply_text(
            "🔧 **Bot is under maintenance**\n\n"
            "Please try again later.\n\n"
            "Admin: " + ADMIN_USERNAME
        )
        return
    
    # Check user permission for non-command messages
    allowed, message = check_user_permission(user_id, settings)
    if not allowed:
        await update.message.reply_text(message)
        return
    
    text = update.message.text
    
    # Check if it's a URL
    if any(text.startswith(prefix) for prefix in ['http://', 'https://', 'www.']) or '.' in text:
        await handle_url(update, context)
    else:
        await update.message.reply_text("Please send a valid website URL.")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors"""
    logger.error(f"Update {update} caused error {context.error}")
    
    try:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="❌ An error occurred. Please try again."
        )
    except:
        pass

# ===== MAIN FUNCTION =====
def main():
    """Start the bot"""
    # Check if wget is installed
    try:
        subprocess.run(["which", "wget"], check=True, capture_output=True)
    except:
        print("❌ ERROR: wget is not installed!")
        print("Install it with:")
        print("  Ubuntu/Debian: sudo apt install wget")
        print("  Termux: pkg install wget")
        exit(1)
    
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("cancel", cancel))
    
    # Admin commands
    application.add_handler(CommandHandler("p", permission_command))
    application.add_handler(CommandHandler("ban", ban_command))
    application.add_handler(CommandHandler("unban", unban_command))
    application.add_handler(CommandHandler("lim", limit_command))
    application.add_handler(CommandHandler("man", maintenance_command))
    application.add_handler(CommandHandler("stats", stats_command))
    
    # Message handler
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # Add error handler
    application.add_error_handler(error_handler)
    
    # Start bot
    print("=" * 50)
    print("✅ Bot started successfully!")
    print(f"🤖 Bot Token: {BOT_TOKEN}")
    print(f"👑 Admin ID: {ADMIN_ID}")
    print(f"👑 Admin Username: {ADMIN_USERNAME}")
    print("📤 Send /start to begin")
    print("⚡ Files will be sent directly to Telegram (no disk storage)")
    print("=" * 50)
    print("\n🔧 **Admin Commands:**")
    print("  /p [user_id] - Give permission to user")
    print("  /ban [user_id] - Ban user")
    print("  /unban [user_id] - Unban user")
    print("  /lim [number] - Set user limit (0 for no limit)")
    print("  /man - Toggle maintenance mode")
    print("  /stats - Show bot statistics")
    print("=" * 50)
    
    # Initialize settings file
    settings = load_settings()
    save_settings(settings)
    print(f"📁 Settings file created: {SETTINGS_FILE}")
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
