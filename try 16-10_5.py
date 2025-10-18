import random
import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters

# Replace with your bot token
TELEGRAM_TOKEN = "8443822936:AAHBesRM3d6NLlSOvcBjHfeE7addfdH9Q4Q"

# Default motivational messages
motivational_messages = [
    "💧 Fun fact: Even mild dehydration (1–2% of body weight) can cause fatigue and reduce focus — sip up and stay sharp! 🧠✨",
    "🩵 Your body is about 70% water — every sip helps your cells stay happy and active! 🌿",
    "🚰 Feeling hungry but just ate? Sometimes thirst disguises itself as hunger — try drinking a glass of water first! 🍽️💦",
    "💦 Reminder: If your urine is dark yellow, you may need more fluids — aim for pale straw color! 🚽🌼",
    "🌞 Staying hydrated keeps your skin supple and glowing — beauty starts with water! 💧💋",
    "⚡ Water helps regulate body temperature and transport nutrients — you’re literally fueling life! 🌍💪",
    "🥤 Take a sip! Your kidneys are working hard — help them flush out toxins efficiently 💦",
    "🧘 Hydration helps your muscles and joints move smoothly — great for staying flexible and active! 🦵💧",
    "🕒 Tiny tip: Take small, regular sips throughout the day instead of gulping all at once — it hydrates you better! ⏳💦",
    "🌊 Did you know? The brain is around 75% water — drinking enough helps keep your mood and memory stable 🧠💙",
    "💧 Dry lips, headache, or dizziness? Those are early signs of dehydration — grab your bottle! 🚰🌤️",
    "☕ Had coffee or tea today? They’re slightly dehydrating — balance with an extra glass of water 🥰💧",
    "🍉 Hydration hack: Foods like cucumber, watermelon, and oranges are over 90% water! Snack smart 💚",
    "💦 It’s not just thirst — hydration helps your heart pump blood more easily ❤️",
    "🌿 Sip steadily — your body loses water even when breathing or sweating lightly! 🌬️💧",
    "😴 Drinking enough water can actually improve sleep quality — your body repairs better when hydrated 🌙💧",
    "💧 Stay refreshed! Proper hydration helps prevent headaches and improve mood 🧃😊",
    "🏃 After a walk or workout, replenish your fluids — your muscles will thank you 💪💦",
    "☀️ Don’t wait to feel thirsty — by then, you’re already a little dehydrated! Start sipping early 💧",
    "🌈 Water is life — every glass is a step toward clearer skin, better focus, and more energy 🌟"
]

# Store user windows: {chat_id: [ {days, start, end, interval}, ... ]}
user_windows = {}
user_messages = {}  # Store custom messages per user
user_preferences = {}  # Store user preferences
user_paused = set()  # Store users who have paused the bot

# Store temporary data for conversation flow
user_temp_data = {}

# Days mapping
DAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
DAY_SHORT_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

def find_schedule_conflicts(schedules):
    """Find and resolve conflicts between schedules"""
    conflicts = []
    
    for i, s1 in enumerate(schedules):
        for j, s2 in enumerate(schedules):
            if i >= j:  # Avoid duplicate checks and self-comparison
                continue
            
            # Find overlapping days
            overlapping_days = s1['days'] & s2['days']
            if not overlapping_days:
                continue
            
            # Find overlapping time ranges
            latest_start = max(s1['start'], s2['start'])
            earliest_end = min(s1['end'], s2['end'])
            
            if latest_start < earliest_end:
                # There's a time overlap on overlapping days
                conflicts.append({
                    'schedule1_idx': i,
                    'schedule2_idx': j,
                    'overlapping_days': overlapping_days,
                    'time_overlap': (latest_start, earliest_end)
                })
    
    return conflicts

def resolve_schedule_conflicts(schedules):
    """Automatically resolve conflicts by adjusting overlapping schedules"""
    conflicts = find_schedule_conflicts(schedules)
    
    if not conflicts:
        return schedules, []
    
    resolution_notes = []
    resolved_schedules = schedules.copy()
    
    for conflict in conflicts:
        i, j = conflict['schedule1_idx'], conflict['schedule2_idx']
        s1, s2 = resolved_schedules[i], resolved_schedules[j]
        overlapping_days = conflict['overlapping_days']
        
        # Strategy: Keep the more specific schedule intact, adjust the broader one
        # A schedule with fewer days is considered more specific
        s1_specificity = len(s1['days'])
        s2_specificity = len(s2['days'])
        
        if s1_specificity <= s2_specificity:
            # s1 is more specific or equally specific, adjust s2
            adjust_schedule = s2
            keep_schedule = s1
            adjust_idx = j
            keep_idx = i
        else:
            # s2 is more specific, adjust s1
            adjust_schedule = s1
            keep_schedule = s2
            adjust_idx = i
            keep_idx = j
        
        # Remove overlapping days from the schedule to adjust
        original_days = adjust_schedule['days'].copy()
        adjust_schedule['days'] = adjust_schedule['days'] - overlapping_days
        
        if adjust_schedule['days']:  # If there are still days left
            # FIXED: Properly format the day names list
            day_names_list = [DAY_NAMES[d] for d in sorted(overlapping_days)]
            resolution_notes.append(
                f"Schedule {adjust_idx + 1} adjusted: removed {', '.join(day_names_list)} "
                f"(conflict with Schedule {keep_idx + 1})"
            )
        else:
            # If no days left, remove the schedule entirely
            resolved_schedules[adjust_idx] = None
            resolution_notes.append(
                f"Schedule {adjust_idx + 1} removed (completely conflicted with Schedule {keep_idx + 1})"
            )
    
    # Remove any schedules that were set to None
    resolved_schedules = [s for s in resolved_schedules if s is not None]
    
    return resolved_schedules, resolution_notes

def restart_all_jobs(chat_id, context):
    """Restart all jobs for a user - used when schedules are modified"""
    # Remove all existing jobs for this user
    for job in context.job_queue.get_jobs_by_name(str(chat_id)):
        job.schedule_removal()
    
    # Remove all precise jobs for this user
    for job in context.job_queue.jobs():
        if job.name and job.name.startswith(f"{chat_id}_precise_"):
            job.schedule_removal()
    
    # Don't create new jobs if user has paused the bot
    if chat_id in user_paused:
        return
    
    # Create new jobs for all schedules
    for i, schedule in enumerate(user_windows.get(chat_id, [])):
        now = datetime.datetime.now()
        if now.weekday() in schedule['days'] and schedule['start'] <= now.time() <= schedule['end']:
            next_reminder_time = calculate_next_reminder_time(
                schedule['start'], schedule['interval'], now.time()
            )
            
            next_reminder_datetime = datetime.datetime.combine(now.date(), next_reminder_time)
            if next_reminder_datetime < now:
                days_ahead = 1
                while True:
                    next_day = now + datetime.timedelta(days=days_ahead)
                    if next_day.weekday() in schedule['days']:
                        next_reminder_datetime = datetime.datetime.combine(next_day.date(), schedule['start'])
                        break
                    days_ahead += 1
            
            delay = (next_reminder_datetime - now).total_seconds()
            
            if delay > 0:
                context.job_queue.run_once(
                    send_precise_reminder,
                    delay,
                    chat_id=chat_id,
                    name=f"{chat_id}_precise_{i}",
                    data=schedule
                )

def stop_all_jobs(chat_id, context):
    """Stop all jobs for a user - used when pausing the bot"""
    # Remove all existing jobs for this user
    for job in context.job_queue.get_jobs_by_name(str(chat_id)):
        job.schedule_removal()
    
    # Remove all precise jobs for this user
    for job in context.job_queue.jobs():
        if job.name and job.name.startswith(f"{chat_id}_precise_"):
            job.schedule_removal()

# Utility function to parse days with better error handling
def parse_days(days_str):
    days_str = days_str.strip().title()
    mapping = {'Mon': 0, 'Tue': 1, 'Wed': 2, 'Thu': 3, 'Fri': 4, 'Sat': 5, 'Sun': 6,
               'Monday': 0, 'Tuesday': 1, 'Wednesday': 2, 'Thursday': 3, 'Friday': 4, 'Saturday': 5, 'Sunday': 6}
    
    if '-' in days_str:
        try:
            start, end = days_str.split('-')
            start_idx = mapping[start.strip()]
            end_idx = mapping[end.strip()]
            if start_idx <= end_idx:
                return set(range(start_idx, end_idx + 1))
            else:  # wrap-around like Fri-Mon
                return set(list(range(start_idx, 7)) + list(range(0, end_idx + 1)))
        except (ValueError, KeyError):
            raise ValueError("Invalid day range format. Use like 'Mon-Fri' or 'Monday-Friday'")
    else:
        try:
            days_list = [d.strip() for d in days_str.split(',')]
            return {mapping[d] for d in days_list}
        except KeyError as e:
            raise ValueError(f"Invalid day name: {e}")

def calculate_next_reminder_time(start_time, interval_min, current_time=None):
    """Calculate the next exact reminder time based on interval alignment"""
    if current_time is None:
        current_time = datetime.datetime.now().time()
    
    # Convert times to minutes since midnight
    start_minutes = start_time.hour * 60 + start_time.minute
    current_minutes = current_time.hour * 60 + current_time.minute
    
    # Calculate how many intervals have passed since start time
    if current_minutes < start_minutes:
        # If current time is before start time today, first reminder will be at start time
        next_minutes = start_minutes
    else:
        # Calculate next aligned interval
        intervals_passed = (current_minutes - start_minutes) // interval_min
        next_minutes = start_minutes + (intervals_passed + 1) * interval_min
    
    # Convert back to time object
    next_hour = next_minutes // 60
    next_minute = next_minutes % 60
    
    # Handle crossing midnight
    if next_hour >= 24:
        next_hour -= 24
    
    return datetime.time(next_hour, next_minute)

def get_schedule_times(start_time, end_time, interval_min):
    """Get all reminder times for a schedule"""
    start_minutes = start_time.hour * 60 + start_time.minute
    end_minutes = end_time.hour * 60 + end_time.minute
    
    times = []
    current_minutes = start_minutes
    
    while current_minutes <= end_minutes:
        hour = current_minutes // 60
        minute = current_minutes % 60
        times.append(datetime.time(hour, minute))
        current_minutes += interval_min
    
    return times

def get_user_messages(chat_id):
    """Get messages for a user based on their preferences"""
    custom_msgs = user_messages.get(chat_id, [])
    use_only_custom = user_preferences.get(chat_id, {}).get('use_only_custom', False)
    
    if use_only_custom:
        if custom_msgs:
            return custom_msgs
        else:
            # Fallback to default if no custom messages
            return motivational_messages
    else:
        # Mix custom messages with defaults
        all_messages = motivational_messages.copy()
        all_messages.extend(custom_msgs)
        return all_messages

# --- Button Handlers ---
async def days_selection(update: Update, context: ContextTypes.DEFAULT_TYPE, editing_index=None):
    """Show day selection buttons"""
    # Get message object for both command and callback scenarios
    if update.message:
        message = update.message
    elif update.callback_query:
        message = update.callback_query.message
    else:
        return
    
    chat_id = message.chat_id
    
    # Create keyboard with days
    keyboard = []
    row = []
    for i, day in enumerate(DAY_SHORT_NAMES):
        row.append(InlineKeyboardButton(day, callback_data=f"day_{i}"))
        if len(row) == 3 or i == len(DAY_SHORT_NAMES) - 1:
            keyboard.append(row)
            row = []
    
    # Add quick selection buttons
    keyboard.append([
        InlineKeyboardButton("Weekdays", callback_data="quick_weekdays"),
        InlineKeyboardButton("Weekends", callback_data="quick_weekends")
    ])
    keyboard.append([
        InlineKeyboardButton("Every Day", callback_data="quick_alldays"),
        InlineKeyboardButton("Clear All", callback_data="quick_clear")
    ])
    keyboard.append([InlineKeyboardButton("✅ Done", callback_data=f"days_done_{editing_index if editing_index is not None else 'new'}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Initialize or get current selection
    if chat_id not in user_temp_data:
        user_temp_data[chat_id] = {'selected_days': set()}
    
    # If editing, pre-select the current days
    if editing_index is not None and chat_id in user_windows and 0 <= editing_index < len(user_windows[chat_id]):
        # FIX: Directly use the stored days instead of trying to match representations
        user_temp_data[chat_id]['selected_days'] = user_windows[chat_id][editing_index]['days'].copy()
    
    selected_days = user_temp_data[chat_id]['selected_days']
    
    # Create message text showing selected days
    if selected_days:
        # FIX: Better display logic that shows the actual selected days
        if selected_days == set(range(7)):
            selection_text = "Every day"
        elif selected_days == set(range(5)):
            selection_text = "Weekdays"
        elif selected_days == {5, 6}:
            selection_text = "Weekends"
        else:
            selected_names = [DAY_NAMES[i] for i in sorted(selected_days)]
            selection_text = f"Selected: {', '.join(selected_names)}"
    else:
        selection_text = "No days selected yet"
    
    message_text = f"📅 *Select Days for Your Schedule*\n\n{selection_text}\n\nClick days to select/deselect them, then press '✅ Done' when finished."
    
    if editing_index is not None:
        message_text = f"✏️ *Editing Schedule {editing_index + 1}*\n\n{message_text}"
    
    await message.reply_text(
        message_text,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    
    # Store message ID and editing info for later editing
    user_temp_data[chat_id]['days_message_id'] = message.message_id
    if editing_index is not None:
        user_temp_data[chat_id]['editing_index'] = editing_index

async def days_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle day selection button clicks"""
    query = update.callback_query
    await query.answer()
    
    chat_id = query.message.chat_id
    data = query.data
    
    # Initialize temp data if not exists
    if chat_id not in user_temp_data:
        user_temp_data[chat_id] = {'selected_days': set()}
    
    selected_days = user_temp_data[chat_id]['selected_days']
    editing_index = user_temp_data[chat_id].get('editing_index')
    
    if data.startswith('day_'):
        # Toggle individual day
        day_index = int(data.split('_')[1])
        if day_index in selected_days:
            selected_days.remove(day_index)
        else:
            selected_days.add(day_index)
    
    elif data == 'quick_weekdays':
        # Select weekdays (Mon-Fri)
        selected_days.update({0, 1, 2, 3, 4})
    
    elif data == 'quick_weekends':
        # Select weekends (Sat-Sun)
        selected_days.update({5, 6})
    
    elif data == 'quick_alldays':
        # Select all days
        selected_days.update({0, 1, 2, 3, 4, 5, 6})
    
    elif data == 'quick_clear':
        # Clear all selection
        selected_days.clear()
    
    elif data.startswith('days_done_'):
        if not selected_days:
            await query.edit_message_text(
                "❌ Please select at least one day for your schedule.\n\n"
                "Use /setup to try again."
            )
            return
        
        # Store selected days and ask for start time
        user_temp_data[chat_id]['schedule_days'] = selected_days.copy()
        editing_type = data.split('_')[-1]
        
        if editing_type != 'new':
            user_temp_data[chat_id]['editing_index'] = int(editing_type)
        
        await query.edit_message_text(
            "📅 *Days Selected!* ✅\n\n"
            "Now, please send me the *start time* in 24-hour format:\n\n"
            "*Examples:*\n"
            "• `09:00` for 9 AM\n"
            "• `14:30` for 2:30 PM\n"
            "• `08:00` for 8 AM\n\n"
            "Please type the start time:",
            parse_mode='Markdown'
        )
        user_temp_data[chat_id]['waiting_for'] = 'start_time'
        return
    
    # Update the message with current selection
    if selected_days:
        # FIX: Better display logic
        if selected_days == set(range(7)):
            selection_text = "Every day"
        elif selected_days == set(range(5)):
            selection_text = "Weekdays"
        elif selected_days == {5, 6}:
            selection_text = "Weekends"
        else:
            selected_names = [DAY_NAMES[i] for i in sorted(selected_days)]
            selection_text = f"Selected: {', '.join(selected_names)}"
    else:
        selection_text = "No days selected yet"
    
    # Recreate keyboard with proper selection states
    keyboard = []
    row = []
    for i, day in enumerate(DAY_SHORT_NAMES):
        # Show selected days with checkmark - FIX: Use exact day comparison
        button_text = f"✅ {day}" if i in selected_days else day
        row.append(InlineKeyboardButton(button_text, callback_data=f"day_{i}"))
        if len(row) == 3 or i == len(DAY_SHORT_NAMES) - 1:
            keyboard.append(row)
            row = []
    
    # Add quick selection buttons with proper states
    # FIX: Check exact sets for quick selection buttons
    weekdays_selected = selected_days == set(range(5))
    weekends_selected = selected_days == {5, 6}
    alldays_selected = selected_days == set(range(7))
    
    keyboard.append([
        InlineKeyboardButton(f"✅ Weekdays" if weekdays_selected else "Weekdays", callback_data="quick_weekdays"),
        InlineKeyboardButton(f"✅ Weekends" if weekends_selected else "Weekends", callback_data="quick_weekends")
    ])
    keyboard.append([
        InlineKeyboardButton(f"✅ Every Day" if alldays_selected else "Every Day", callback_data="quick_alldays"),
        InlineKeyboardButton("Clear All", callback_data="quick_clear")
    ])
    
    done_callback = f"days_done_{editing_index if editing_index is not None else 'new'}"
    keyboard.append([InlineKeyboardButton("✅ Done", callback_data=done_callback)])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message_text = f"📅 *Select Days for Your Schedule*\n\n{selection_text}\n\nClick days to select/deselect them, then press '✅ Done' when finished."
    
    if editing_index is not None:
        message_text = f"✏️ *Editing Schedule {editing_index + 1}*\n\n{message_text}"
    
    await query.edit_message_text(
        message_text,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def handle_time_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle time and interval inputs from user"""
    chat_id = update.effective_chat.id
    
    if chat_id not in user_temp_data or 'waiting_for' not in user_temp_data[chat_id]:
        return
    
    waiting_for = user_temp_data[chat_id]['waiting_for']
    user_input = update.message.text.strip()
    editing_index = user_temp_data[chat_id].get('editing_index')
    
    try:
        if waiting_for == 'start_time':
            # Validate start time
            start_time = datetime.datetime.strptime(user_input, "%H:%M").time()
            user_temp_data[chat_id]['start_time'] = start_time
            user_temp_data[chat_id]['waiting_for'] = 'end_time'
            
            await update.message.reply_text(
                f"⏰ *Start time set to {user_input}* ✅\n\n"
                "Now, please send me the *end time* in 24-hour format:\n\n"
                "*Examples:*\n"
                "• `17:00` for 5 PM\n"
                "• `18:30` for 6:30 PM\n"
                "• `20:00` for 8 PM\n\n"
                "Please type the end time:",
                parse_mode='Markdown'
            )
        
        elif waiting_for == 'end_time':
            # Validate end time
            end_time = datetime.datetime.strptime(user_input, "%H:%M").time()
            start_time = user_temp_data[chat_id]['start_time']
            
            if end_time <= start_time:
                await update.message.reply_text(
                    "❌ End time must be after start time. Please enter the end time again:"
                )
                return
            
            user_temp_data[chat_id]['end_time'] = end_time
            user_temp_data[chat_id]['waiting_for'] = 'interval'
            
            await update.message.reply_text(
                f"⏰ *End time set to {user_input}* ✅\n\n"
                "Now, please send me the *interval in minutes*:\n\n"
                "*Examples:*\n"
                "• `30` for 30 minutes (reminders at :00 and :30)\n"
                "• `60` for 1 hour (reminders at :00)\n"
                "• `90` for 1.5 hours\n"
                "• `120` for 2 hours\n\n"
                "Please type the interval (in minutes):",
                parse_mode='Markdown'
            )
        
        elif waiting_for == 'interval':
            # Validate interval
            interval_min = int(user_input)
            if interval_min < 1:
                await update.message.reply_text("❌ Interval must be at least 1 minute. Please try again:")
                return
            
            # Now we have all data, create or update the schedule
            days = user_temp_data[chat_id]['schedule_days']
            start_time = user_temp_data[chat_id]['start_time']
            end_time = user_temp_data[chat_id]['end_time']
            
            # Calculate exact reminder times for display
            reminder_times = get_schedule_times(start_time, end_time, interval_min)
            
            # Create the new/updated schedule
            window = {
                "days": days,
                "start": start_time,
                "end": end_time,
                "interval": interval_min,
                "reminder_times": reminder_times
            }
            
            # Get current schedules
            user_windows.setdefault(chat_id, [])
            current_schedules = user_windows[chat_id].copy()
            
            if editing_index is not None:
                # Update existing schedule
                current_schedules[editing_index] = window
                action_text = "updated"
            else:
                # Add new schedule
                current_schedules.append(window)
                action_text = "created"
            
            # Check for and resolve conflicts
            resolved_schedules, resolution_notes = resolve_schedule_conflicts(current_schedules)
            
            # Update user windows with resolved schedules
            user_windows[chat_id] = resolved_schedules
            
            # Restart all jobs to avoid conflicts
            restart_all_jobs(chat_id, context)
            
            # Format days for display
            if days == set(range(7)):
                days_str = "Every day"
            elif days == set(range(5)):
                days_str = "Weekdays"
            elif days == {5, 6}:
                days_str = "Weekends"
            else:
                selected_names = [DAY_NAMES[i] for i in sorted(days)]
                days_str = ", ".join(selected_names)
            
            # Show sample reminder times
            sample_times = reminder_times[:5]  # Show first 5 times
            times_text = "\n".join([f"• {t.strftime('%H:%M')}" for t in sample_times])
            if len(reminder_times) > 5:
                times_text += f"\n• ... and {len(reminder_times) - 5} more times"
            
            # Build success message
            success_msg = f"""
✅ *Schedule {action_text.capitalize()} Successfully!* 💧

*Your Reminder Schedule:*
• 📅 *Days:* {days_str}
• ⏰ *Time:* {start_time.strftime('%H:%M')} - {end_time.strftime('%H:%M')}
• 🔄 *Interval:* Every {interval_min} minutes

"""
            
            # Add conflict resolution notes if any
            if resolution_notes:
                success_msg += "\n*🔧 Automatic Adjustments Made:*\n"
                for note in resolution_notes:
                    success_msg += f"• {note}\n"
                success_msg += "\nI adjusted conflicting schedules to avoid duplicate reminders."
            
            success_msg += "\nUse /myschedule to view your updated schedules."
            
            await update.message.reply_text(success_msg, parse_mode='Markdown')
            
            # Clean up temp data
            del user_temp_data[chat_id]
    
    except ValueError:
        if waiting_for in ['start_time', 'end_time']:
            await update.message.reply_text(
                "❌ Invalid time format. Please use HH:MM format (e.g., 09:00, 14:30):"
            )
        else:  # interval
            await update.message.reply_text(
                "❌ Please enter a valid number for the interval (in minutes):"
            )

async def send_precise_reminder(context: ContextTypes.DEFAULT_TYPE):
    """Send reminder at precise times and schedule the next one"""
    job = context.job
    chat_id = job.chat_id
    schedule = job.data
    
    # Check if user has paused the bot
    if chat_id in user_paused:
        return  # Don't send reminder if bot is paused
    
    # Send the reminder using user's preferred messages
    messages = get_user_messages(chat_id)
    message = random.choice(messages)
    await context.bot.send_message(chat_id, text=message)
    
    # Schedule next reminder for this schedule
    now = datetime.datetime.now()
    next_reminder_time = calculate_next_reminder_time(schedule['start'], schedule['interval'])
    
    # Create datetime for next reminder
    next_reminder_datetime = datetime.datetime.combine(now.date(), next_reminder_time)
    
    # If next reminder time is before now or outside schedule hours, find next eligible day
    if (next_reminder_datetime < now or 
        next_reminder_time > schedule['end'] or 
        now.weekday() not in schedule['days']):
        
        days_ahead = 1
        while True:
            next_day = now + datetime.timedelta(days=days_ahead)
            if next_day.weekday() in schedule['days']:
                next_reminder_datetime = datetime.datetime.combine(next_day.date(), schedule['start'])
                break
            days_ahead += 1
    
    # Calculate delay until next reminder
    delay = (next_reminder_datetime - now).total_seconds()
    
    if delay > 0:
        # Schedule the next reminder
        context.job_queue.run_once(
            send_precise_reminder,
            delay,
            chat_id=chat_id,
            name=job.name,  # Keep the same job name
            data=schedule
        )

# --- Bot commands ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = """
💦 *Welcome to AquaBuddy!* 💧

I am here to help you stay hydrated!

*Available Commands:*
💧 /setup - Set up your first reminder schedule
📋 /myschedule - View your current schedules
✏️ /edit - Edit a schedule
➕ /add - Add another schedule
🗑 /removeselect - Remove a schedule
⏸️ /stop - Pause all reminders
▶️ /startbot - Resume reminders
💬 /addmessage - Add custom reminder messages
📝 /mymessages - View your custom messages
⚙️ /settings - Manage preferences
❓ /help - Show this help message

*Quick Controls:*
    """
    
    keyboard = [
        [InlineKeyboardButton("⏸️ Pause Bot", callback_data="pause_bot")],
        [InlineKeyboardButton("📋 View Schedules", callback_data="view_schedules")],
        [InlineKeyboardButton("⚙️ Settings", callback_data="settings_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Get message object for both command and callback scenarios
    if update.message:
        await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')
    elif update.callback_query:
        await update.callback_query.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
*💧 AquaBuddy Help 💧*

*Pause/Resume Feature:*
• Use `/stop` to pause all reminders
• Use `/startbot` to resume reminders
• Your schedules are saved and will restart automatically

*Commands:*
/setup - Create your first schedule
/myschedule - View all schedules
/edit <num> - Edit a schedule
/add - Add another schedule  
/remove <num> - Remove a schedule
/stop - Pause all reminders
/startbot - Resume reminders
/settings - Message preferences
    """
    
    keyboard = [
        [InlineKeyboardButton("⏸️ Pause Bot", callback_data="pause_bot")],
        [InlineKeyboardButton("▶️ Resume Bot", callback_data="resume_bot")],
        [InlineKeyboardButton("📋 My Schedules", callback_data="view_schedules")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Get message object for both command and callback scenarios
    if update.message:
        await update.message.reply_text(help_text, reply_markup=reply_markup, parse_mode='Markdown')
    elif update.callback_query:
        await update.callback_query.message.reply_text(help_text, reply_markup=reply_markup, parse_mode='Markdown')

async def setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the interactive setup process with button-based day selection"""
    await days_selection(update, context)

async def add_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add another schedule using the same button interface"""
    await days_selection(update, context)

async def my_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View current schedules - FIXED to handle both message and callback"""
    # Get message object for both command and callback scenarios
    if update.message:
        message = update.message
    elif update.callback_query:
        message = update.callback_query.message
    else:
        return
    
    chat_id = message.chat_id
    
    # Check if bot is paused for this user
    is_paused = chat_id in user_paused
    
    if chat_id not in user_windows or not user_windows[chat_id]:
        keyboard = [
            [InlineKeyboardButton("💧 Create Schedule", callback_data="setup_schedule")],
            [InlineKeyboardButton("⏸️ Pause Bot", callback_data="pause_bot")] if not is_paused else
            [InlineKeyboardButton("▶️ Resume Bot", callback_data="resume_bot")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        status_text = "⏸️ *Bot is currently paused*" if is_paused else "▶️ *Bot is running*"
        
        await message.reply_text(
            f"💧 *Your Water Reminder Schedules*\n\n{status_text}\n\n"
            "You don't have any reminder schedules set up yet!\n\n"
            "Use the button below to create your first schedule!",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return
    
    text = "💧 *Your Water Reminder Schedules:*\n\n"
    day_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    
    for i, w in enumerate(user_windows[chat_id], 1):
        active_days = []
        for day_num in range(7):
            if day_num in w['days']:
                active_days.append(day_names[day_num][:3])
        
        days_str = ", ".join(active_days)
        if set(w['days']) == set(range(7)):
            days_str = "Every day"
        elif w['days'] == set(range(5)):
            days_str = "Weekdays"
        elif w['days'] == set([5, 6]):
            days_str = "Weekends"
        
        # Show first few reminder times
        sample_times = w.get('reminder_times', [])[:3]
        times_text = ", ".join([t.strftime('%H:%M') for t in sample_times])
        if len(w.get('reminder_times', [])) > 3:
            times_text += f", ..."
        
        text += f"*{i}. {days_str}*\n"
        text += f"   ⏰ {w['start'].strftime('%H:%M')} - {w['end'].strftime('%H:%M')}\n"
        text += f"   🔄 Every {w['interval']} minutes\n"
        text += f"   🕒 Times: {times_text}\n\n"
    
    # Check for conflicts in current setup
    conflicts = find_schedule_conflicts(user_windows[chat_id])
    if conflicts:
        text += "⚠️ *Note:* Some schedules have overlapping times. I'll automatically handle these to avoid duplicate reminders.\n"
    
    # Add bot status
    status_text = "⏸️ *Bot Status: PAUSED* - Use /startbot to resume" if is_paused else "▶️ *Bot Status: RUNNING* - Use /stop to pause"
    text += f"\n{status_text}"
    
    # Create keyboard with appropriate buttons
    keyboard = [
        [InlineKeyboardButton("✏️ Edit Schedules", callback_data="edit_schedules")],
        [InlineKeyboardButton("⏸️ Pause Bot", callback_data="pause_bot")] if not is_paused else
        [InlineKeyboardButton("▶️ Resume Bot", callback_data="resume_bot")],
        [InlineKeyboardButton("➕ Add Schedule", callback_data="add_schedule")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def edit_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Edit a schedule - FIXED to handle both message and callback"""
    # Get message object for both command and callback scenarios
    if update.message:
        message = update.message
    elif update.callback_query:
        message = update.callback_query.message
    else:
        return
    
    chat_id = message.chat_id

    if chat_id not in user_windows or not user_windows[chat_id]:
        await message.reply_text("❌ You don't have any schedules to edit. Use /setup first.")
        return

    if not context.args:
        await my_schedule(update, context)
        await message.reply_text(
            "✏️ *Edit Schedule*\n\n"
            "To edit a schedule, use:\n"
            "`/edit <schedule_number>`\n\n"
            "*Example:* `/edit 1`\n\n"
            "This will start the editing process for that schedule.",
            parse_mode='Markdown'
        )
        return

    try:
        schedule_number = int(context.args[0])
        if not (1 <= schedule_number <= len(user_windows[chat_id])):
            raise ValueError("Invalid schedule number")
        
        # Start the editing process for this schedule
        await days_selection(update, context, editing_index=schedule_number-1)
        
    except (ValueError, IndexError):
        await message.reply_text("❌ Invalid schedule number. Use /myschedule to see your schedules.")

async def remove_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove a schedule - FIXED to handle both message and callback"""
    # Get message object for both command and callback scenarios
    if update.message:
        message = update.message
    elif update.callback_query:
        message = update.callback_query.message
    else:
        return
    
    chat_id = message.chat_id

    if chat_id not in user_windows or not user_windows[chat_id]:
        await message.reply_text("❌ You don't have any schedules to remove.")
        return

    if not context.args:
        await my_schedule(update, context)
        await message.reply_text(
            "To remove a schedule, use:\n"
            "`/remove <number>`\n\n"
            "*Example:* `/remove 1`",
            parse_mode='Markdown'
        )
        return

    try:
        window_number = int(context.args[0]) - 1
        if not (0 <= window_number < len(user_windows[chat_id])):
            raise IndexError
        
        removed = user_windows[chat_id].pop(window_number)
        
        # Restart all jobs properly
        restart_all_jobs(chat_id, context)
        
        await message.reply_text(
            f"✅ *Schedule {window_number + 1} removed!*\n\n"
            f"Use /setup to add new reminders if needed.",
            parse_mode='Markdown'
        )
        
    except (ValueError, IndexError):
        await message.reply_text("❌ Invalid schedule number. Use /myschedule to see your schedules.")

# --- Stop/Start Commands ---
async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Stop all reminders for the user"""
    # Get message object for both command and callback scenarios
    if update.message:
        message = update.message
    elif update.callback_query:
        message = update.callback_query.message
    else:
        return
    
    chat_id = message.chat_id
    
    if chat_id in user_paused:
        await message.reply_text(
            "⏸️ *Bot is already paused!*\n\n"
            "Use /startbot to resume your reminders.",
            parse_mode='Markdown'
        )
        return
    
    # Stop all jobs
    stop_all_jobs(chat_id, context)
    
    # Mark user as paused
    user_paused.add(chat_id)
    
    await message.reply_text(
        "⏸️ *Bot Paused!*\n\n"
        "All your water reminders have been stopped.\n\n"
        "Use /startbot to resume your reminders whenever you're ready! 💧",
        parse_mode='Markdown'
    )

async def startbot_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Resume reminders for the user"""
    # Get message object for both command and callback scenarios
    if update.message:
        message = update.message
    elif update.callback_query:
        message = update.callback_query.message
    else:
        return
    
    chat_id = message.chat_id
    
    if chat_id not in user_paused:
        await message.reply_text(
            "▶️ *Bot is already running!*\n\n"
            "Use /stop to pause your reminders.",
            parse_mode='Markdown'
        )
        return
    
    # Remove from paused set
    user_paused.discard(chat_id)
    
    # Restart all jobs
    restart_all_jobs(chat_id, context)
    
    schedule_count = len(user_windows.get(chat_id, []))
    
    if schedule_count > 0:
        await message.reply_text(
            f"▶️ *Bot Resumed!*\n\n"
            f"Your {schedule_count} reminder schedule(s) have been restarted! 💧\n\n"
            f"Use /stop to pause reminders again.",
            parse_mode='Markdown'
        )
    else:
        await message.reply_text(
            "▶️ *Bot Resumed!*\n\n"
            "Bot is now active, but you don't have any schedules set up yet.\n\n"
            "Use /setup to create your first reminder schedule! 💧",
            parse_mode='Markdown'
        )

async def pause_resume_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle pause/resume button clicks"""
    query = update.callback_query
    await query.answer()
    
    chat_id = query.message.chat_id
    data = query.data
    
    if data == "pause_bot":
        if chat_id in user_paused:
            await query.edit_message_text(
                "⏸️ *Bot is already paused!*\n\n"
                "Use the button below to resume your reminders.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("▶️ Resume Bot", callback_data="resume_bot")
                ]]),
                parse_mode='Markdown'
            )
        else:
            # Stop all jobs
            stop_all_jobs(chat_id, context)
            user_paused.add(chat_id)
            
            await query.edit_message_text(
                "⏸️ *Bot Paused!*\n\n"
                "All your water reminders have been stopped.\n\n"
                "Use the button below to resume your reminders whenever you're ready! 💧",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("▶️ Resume Bot", callback_data="resume_bot")
                ]]),
                parse_mode='Markdown'
            )
    
    elif data == "resume_bot":
        if chat_id not in user_paused:
            await query.edit_message_text(
                "▶️ *Bot is already running!*\n\n"
                "Use the button below to pause your reminders.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⏸️ Pause Bot", callback_data="pause_bot")
                ]]),
                parse_mode='Markdown'
            )
        else:
            # Remove from paused set and restart jobs
            user_paused.discard(chat_id)
            restart_all_jobs(chat_id, context)
            
            schedule_count = len(user_windows.get(chat_id, []))
            
            if schedule_count > 0:
                await query.edit_message_text(
                    f"▶️ *Bot Resumed!*\n\n"
                    f"Your {schedule_count} reminder schedule(s) have been restarted! 💧\n\n"
                    f"Use the button below to pause reminders again.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("⏸️ Pause Bot", callback_data="pause_bot")
                    ]]),
                    parse_mode='Markdown'
                )
            else:
                await query.edit_message_text(
                    "▶️ *Bot Resumed!*\n\n"
                    "Bot is now active, but you don't have any schedules set up yet.\n\n"
                    "Use /setup to create your first reminder schedule! 💧",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("⏸️ Pause Bot", callback_data="pause_bot")
                    ]]),
                    parse_mode='Markdown'
                )

# --- Message Management Commands ---
async def add_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add custom message"""
    # Get message object for both command and callback scenarios
    if update.message:
        message = update.message
    elif update.callback_query:
        message = update.callback_query.message
    else:
        return
    
    chat_id = message.chat_id
    msg = " ".join(context.args)
    
    if not msg:
        await message.reply_text(
            "💬 *Add Custom Message*\n\n"
            "Usage: `/addmessage <your custom message>`\n\n"
            "*Example:* `/addmessage Time to hydrate! Stay awesome! 💧`\n\n"
            "*No limits!* Add as many custom messages as you want!",
            parse_mode='Markdown'
        )
        return
    
    user_messages.setdefault(chat_id, []).append(msg)
    
    await message.reply_text(
        f"✅ *Custom message added!*\n\n"
        f"\"{msg}\"\n\n"
        f"You now have {len(user_messages[chat_id])} custom message(s).\n"
        f"Use /mymessages to view all your messages.",
        parse_mode='Markdown'
    )

async def my_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View custom messages"""
    # Get message object for both command and callback scenarios
    if update.message:
        message = update.message
    elif update.callback_query:
        message = update.callback_query.message
    else:
        return
    
    chat_id = message.chat_id
    custom_msgs = user_messages.get(chat_id, [])
    
    if not custom_msgs:
        await message.reply_text(
            "💬 *Your Custom Messages*\n\n"
            "You haven't added any custom messages yet.\n\n"
            "Use `/addmessage <your message>` to add your own motivational water reminders!\n\n"
            "*No limits!* Add as many as you want!",
            parse_mode='Markdown'
        )
        return
    
    use_only_custom = user_preferences.get(chat_id, {}).get('use_only_custom', False)
    preference_text = "🔸 *Currently using:* Only your custom messages" if use_only_custom else "🔸 *Currently using:* Mixed (default + your custom messages)"
    
    text = f"💬 *Your Custom Messages:*\n\n{preference_text}\n\n"
    for i, msg in enumerate(custom_msgs, 1):
        text += f"{i}. {msg}\n"
    
    text += f"\nYou have {len(custom_msgs)} custom message(s).\n"
    text += "Use /settings to change how messages are used."
    
    await message.reply_text(text, parse_mode='Markdown')

async def clear_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove all custom messages"""
    # Get message object for both command and callback scenarios
    if update.message:
        message = update.message
    elif update.callback_query:
        message = update.callback_query.message
    else:
        return
    
    chat_id = message.chat_id
    custom_msgs = user_messages.get(chat_id, [])
    
    if not custom_msgs:
        await message.reply_text("❌ You don't have any custom messages to clear.")
        return
    
    # Ask for confirmation
    keyboard = [
        [
            InlineKeyboardButton("✅ Yes, clear all", callback_data="confirm_clear"),
            InlineKeyboardButton("❌ Cancel", callback_data="cancel_clear")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await message.reply_text(
        f"⚠️ *Are you sure you want to clear all {len(custom_msgs)} custom messages?*\n\n"
        "This action cannot be undone!",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show settings for message preferences"""
    # Get message object for both command and callback scenarios
    if update.message:
        message = update.message
    elif update.callback_query:
        message = update.callback_query.message
    else:
        return
    
    chat_id = message.chat_id
    current_setting = user_preferences.get(chat_id, {}).get('use_only_custom', False)
    custom_count = len(user_messages.get(chat_id, []))
    
    if current_setting:
        current_text = "✅ *Currently using only your custom messages*"
        other_option = "🔘 Switch to mixed messages (default + custom)"
        callback_data = "pref_mixed"
    else:
        current_text = "✅ *Currently using mixed messages* (default + your custom)"
        other_option = "🔘 Switch to only custom messages"
        callback_data = "pref_custom_only"
    
    keyboard = [
        [InlineKeyboardButton(other_option, callback_data=callback_data)],
        [InlineKeyboardButton("📋 View My Messages", callback_data="view_messages")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_settings")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = f"""
⚙️ *Message Settings*

{current_text}

• You have {custom_count} custom message(s)
• Mixed messages: Bot's default messages + your custom messages
• Custom only: Only your messages (falls back to default if none)

Choose your preference:
    """
    
    await message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle settings callback queries"""
    query = update.callback_query
    await query.answer()
    
    chat_id = query.message.chat_id
    data = query.data
    
    if data == "pref_custom_only":
        user_preferences.setdefault(chat_id, {})['use_only_custom'] = True
        await query.edit_message_text(
            "✅ *Settings Updated!*\n\n"
            "Now using only your custom messages for reminders.\n\n"
            "If you don't have any custom messages, I'll fall back to the default messages.",
            parse_mode='Markdown'
        )
    
    elif data == "pref_mixed":
        user_preferences.setdefault(chat_id, {})['use_only_custom'] = False
        await query.edit_message_text(
            "✅ *Settings Updated!*\n\n"
            "Now using mixed messages (default + your custom messages) for reminders.",
            parse_mode='Markdown'
        )
    
    elif data == "view_messages":
        await my_messages(update, context)
    
    elif data == "cancel_settings":
        await query.edit_message_text("Settings unchanged.")
    
    elif data == "confirm_clear":
        user_messages[chat_id] = []
        await query.edit_message_text("✅ *All custom messages have been cleared!*")
    
    elif data == "cancel_clear":
        await query.edit_message_text("✅ Message clearing cancelled.")

# --- General Callback Handler ---
async def general_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle general callback queries"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data == "view_schedules":
        await my_schedule(update, context)
    elif data == "setup_schedule":
        await setup(update, context)
    elif data == "add_schedule":
        await add_schedule(update, context)
    elif data == "edit_schedules":
        await edit_schedule(update, context)
    elif data == "settings_menu":
        await settings_command(update, context)

# === BULK SCHEDULE REMOVAL FUNCTIONS ===

async def remove_all_schedules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove all schedules at once"""
    # Get message object for both command and callback scenarios
    if update.message:
        message = update.message
    elif update.callback_query:
        message = update.callback_query.message
    else:
        return
    
    chat_id = message.chat_id

    if chat_id not in user_windows or not user_windows[chat_id]:
        await message.reply_text("❌ You don't have any schedules to remove.")
        return

    schedule_count = len(user_windows[chat_id])
    
    # Ask for confirmation
    keyboard = [
        [
            InlineKeyboardButton("✅ Yes, remove all", callback_data="confirm_remove_all"),
            InlineKeyboardButton("❌ Cancel", callback_data="cancel_remove_all")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await message.reply_text(
        f"⚠️ *Are you sure you want to remove all {schedule_count} schedule(s)?*\n\n"
        "This action cannot be undone!",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def remove_multiple_schedules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove multiple schedules by numbers"""
    # Get message object for both command and callback scenarios
    if update.message:
        message = update.message
    elif update.callback_query:
        message = update.callback_query.message
    else:
        return
    
    chat_id = message.chat_id

    if chat_id not in user_windows or not user_windows[chat_id]:
        await message.reply_text("❌ You don't have any schedules to remove.")
        return

    if not context.args:
        await my_schedule(update, context)
        await message.reply_text(
            "🗑️ *Remove Multiple Schedules*\n\n"
            "To remove multiple schedules, use:\n"
            "`/removemultiple <schedule_numbers>`\n\n"
            "*Examples:*\n"
            "• `/removemultiple 1 3` - Remove schedules 1 and 3\n"
            "• `/removemultiple 2-4` - Remove schedules 2, 3, and 4\n"
            "• `/removemultiple 1,3,5` - Remove schedules 1, 3, and 5\n\n"
            "Use /myschedule to see your current schedules.",
            parse_mode='Markdown'
        )
        return

    try:
        schedules_to_remove = set()
        input_text = " ".join(context.args)
        
        # Parse different input formats: "1 3", "1-3", "1,3,5"
        if '-' in input_text:
            # Handle range format: "1-3"
            start, end = map(int, input_text.split('-'))
            schedules_to_remove.update(range(start, end + 1))
        elif ',' in input_text:
            # Handle comma format: "1,3,5"
            schedules_to_remove.update(map(int, input_text.split(',')))
        else:
            # Handle space format: "1 3"
            schedules_to_remove.update(map(int, input_text.split()))
        
        # Convert to 0-based indices and validate
        schedule_indices = [num - 1 for num in schedules_to_remove]
        
        # Validate all schedule numbers
        invalid_schedules = []
        for idx in schedule_indices:
            if not (0 <= idx < len(user_windows[chat_id])):
                invalid_schedules.append(str(idx + 1))
        
        if invalid_schedules:
            await message.reply_text(
                f"❌ Invalid schedule numbers: {', '.join(invalid_schedules)}\n"
                f"Please use numbers between 1 and {len(user_windows[chat_id])}.",
                parse_mode='Markdown'
            )
            return
        
        if not schedule_indices:
            await message.reply_text("❌ No valid schedule numbers provided.")
            return
        
        # Show confirmation with schedule details
        schedule_details = []
        for idx in sorted(schedule_indices):
            schedule = user_windows[chat_id][idx]
            days_str = format_days_display(schedule['days'])
            schedule_details.append(f"• Schedule {idx + 1}: {days_str} {schedule['start'].strftime('%H:%M')}-{schedule['end'].strftime('%H:%M')} every {schedule['interval']}min")
        
        # Store the indices to remove in temp data for confirmation
        user_temp_data[chat_id] = {
            'remove_multiple_indices': schedule_indices,
            'remove_multiple_details': schedule_details
        }
        
        keyboard = [
            [
                InlineKeyboardButton("✅ Confirm Remove", callback_data="confirm_remove_multiple"),
                InlineKeyboardButton("❌ Cancel", callback_data="cancel_remove_multiple")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await message.reply_text(
            f"⚠️ *Remove {len(schedule_indices)} Schedule(s)?*\n\n"
            f"{chr(10).join(schedule_details)}\n\n"
            "Are you sure you want to remove these schedules?",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
    except ValueError:
        await message.reply_text(
            "❌ Invalid format. Please use:\n"
            "• `/removemultiple 1 3` for schedules 1 and 3\n"
            "• `/removemultiple 1-3` for schedules 1, 2, and 3\n"
            "• `/removemultiple 1,3,5` for schedules 1, 3, and 5",
            parse_mode='Markdown'
        )

# === INTERACTIVE SCHEDULE REMOVAL FUNCTION ===

async def remove_schedule_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show interactive schedule selection for removal - similar to /add"""
    # Get message object for both command and callback scenarios
    if update.message:
        message = update.message
    elif update.callback_query:
        message = update.callback_query.message
    else:
        return
    
    chat_id = message.chat_id

    if chat_id not in user_windows or not user_windows[chat_id]:
        await message.reply_text("❌ You don't have any schedules to remove.")
        return

    # Initialize selection set if not exists
    if chat_id not in user_temp_data:
        user_temp_data[chat_id] = {'selected_for_removal': set()}
    
    selected_for_removal = user_temp_data[chat_id]['selected_for_removal']
    
    # Create selection keyboard similar to day selection
    keyboard = []
    for i, schedule in enumerate(user_windows[chat_id], 1):
        days_str = format_days_display(schedule['days'])
        # Show selected schedules with checkmark, similar to day selection
        button_text = f"✅ Schedule {i}" if (i-1) in selected_for_removal else f"Schedule {i}"
        schedule_text = f"{button_text}: {days_str} {schedule['start'].strftime('%H:%M')}-{schedule['end'].strftime('%H:%M')}"
        keyboard.append([InlineKeyboardButton(schedule_text, callback_data=f"select_remove_{i-1}")])
    
    # Add action buttons at the bottom, similar to /add layout
    action_buttons = []
    if selected_for_removal:
        action_buttons.append(InlineKeyboardButton("🗑️ Remove Selected", callback_data="execute_remove_selected"))
    action_buttons.append(InlineKeyboardButton("🗑️ Remove All", callback_data="remove_all_prompt"))
    
    if action_buttons:
        keyboard.append(action_buttons)
    
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel_remove_selection")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Build message text similar to day selection interface
    selected_count = len(selected_for_removal)
    
    if selected_count > 0:
        selection_text = f"Selected {selected_count} schedule(s) for removal"
    else:
        selection_text = "No schedules selected yet"
    
    message_text = f"""
🗑️ *Select Schedules to Remove*

{selection_text}

Click schedules to select/deselect them for removal.
Selected schedules will show with ✅ checkmark.

*Your Current Schedules:*
"""
    
    # Add schedule details
    for i, schedule in enumerate(user_windows[chat_id], 1):
        days_str = format_days_display(schedule['days'])
        selected_indicator = " ✅" if (i-1) in selected_for_removal else ""
        message_text += f"\n{i}. {days_str} {schedule['start'].strftime('%H:%M')}-{schedule['end'].strftime('%H:%M')} every {schedule['interval']}min{selected_indicator}"
    
    await message.reply_text(
        message_text,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

# Helper function to format days for display
def format_days_display(days_set):
    """Format days set for display"""
    if days_set == set(range(7)):
        return "Every day"
    elif days_set == set(range(5)):
        return "Weekdays"
    elif days_set == {5, 6}:
        return "Weekends"
    else:
        selected_names = [DAY_NAMES[i][:3] for i in sorted(days_set)]
        return ", ".join(selected_names)

# Callback handler for removal interactions
async def remove_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle removal callback queries"""
    query = update.callback_query
    await query.answer()
    
    chat_id = query.message.chat_id
    data = query.data
    
    if data.startswith("select_remove_"):
        # Toggle schedule selection - similar to day selection
        schedule_index = int(data.split('_')[-1])
        
        if chat_id not in user_temp_data:
            user_temp_data[chat_id] = {'selected_for_removal': set()}
        
        selected_set = user_temp_data[chat_id]['selected_for_removal']
        
        if schedule_index in selected_set:
            selected_set.remove(schedule_index)
        else:
            selected_set.add(schedule_index)
        
        # Update the selection interface (like day selection updates)
        await remove_schedule_selection(update, context)
    
    elif data == "execute_remove_selected":
        if chat_id in user_temp_data and 'selected_for_removal' in user_temp_data[chat_id]:
            selected_indices = list(user_temp_data[chat_id]['selected_for_removal'])
            
            if not selected_indices:
                await query.edit_message_text("❌ No schedules selected for removal.")
                return
            
            # Show confirmation with selected schedule details
            schedule_details = []
            for idx in sorted(selected_indices):
                if 0 <= idx < len(user_windows[chat_id]):
                    schedule = user_windows[chat_id][idx]
                    days_str = format_days_display(schedule['days'])
                    schedule_details.append(f"• Schedule {idx + 1}: {days_str} {schedule['start'].strftime('%H:%M')}-{schedule['end'].strftime('%H:%M')}")
            
            keyboard = [
                [
                    InlineKeyboardButton("✅ Confirm Remove", callback_data="confirm_remove_selected"),
                    InlineKeyboardButton("❌ Cancel", callback_data="cancel_remove_selected")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                f"⚠️ *Remove {len(selected_indices)} Schedule(s)?*\n\n"
                f"{chr(10).join(schedule_details)}\n\n"
                "Are you sure you want to remove these schedules?",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        else:
            await query.edit_message_text("❌ No schedules selected for removal.")
    
    elif data == "confirm_remove_selected":
        if chat_id in user_temp_data and 'selected_for_removal' in user_temp_data[chat_id]:
            selected_indices = list(user_temp_data[chat_id]['selected_for_removal'])
            
            # Remove schedules in reverse order
            removed_count = 0
            for idx in sorted(selected_indices, reverse=True):
                if 0 <= idx < len(user_windows[chat_id]):
                    user_windows[chat_id].pop(idx)
                    removed_count += 1
            
            # Restart jobs
            restart_all_jobs(chat_id, context)
            
            # Clean up temp data
            del user_temp_data[chat_id]
            
            await query.edit_message_text(
                f"✅ *{removed_count} schedule(s) removed successfully!*\n\n"
                f"Use /myschedule to view your remaining schedules.",
                parse_mode='Markdown'
            )
        else:
            await query.edit_message_text("❌ No schedules selected for removal.")
    
    elif data == "cancel_remove_selected":
        # Go back to selection interface
        await remove_schedule_selection(update, context)
    
    elif data == "remove_all_prompt":
        if chat_id in user_windows and user_windows[chat_id]:
            schedule_count = len(user_windows[chat_id])
            
            keyboard = [
                [
                    InlineKeyboardButton("✅ Yes, remove all", callback_data="confirm_remove_all"),
                    InlineKeyboardButton("❌ Cancel", callback_data="cancel_remove_all")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                f"⚠️ *Are you sure you want to remove all {schedule_count} schedule(s)?*\n\n"
                "This action cannot be undone!",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        else:
            await query.edit_message_text("❌ No schedules to remove.")
    
    elif data == "confirm_remove_all":
        if chat_id in user_windows and user_windows[chat_id]:
            schedule_count = len(user_windows[chat_id])
            # Remove all schedules
            user_windows[chat_id] = []
            # Stop all jobs
            stop_all_jobs(chat_id, context)
            
            # Clean up temp data if exists
            if chat_id in user_temp_data:
                del user_temp_data[chat_id]
            
            await query.edit_message_text(
                f"✅ *All {schedule_count} schedule(s) removed!*\n\n"
                f"Use /setup to create new schedules.",
                parse_mode='Markdown'
            )
        else:
            await query.edit_message_text("❌ No schedules to remove.")
    
    elif data == "cancel_remove_all":
        await remove_schedule_selection(update, context)
    
    elif data == "cancel_remove_selection":
        if chat_id in user_temp_data:
            del user_temp_data[chat_id]
        await query.edit_message_text("✅ Schedule removal cancelled.")

# Update the help command to include the new removal option
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
*💧 AquaBuddy Help 💧*

*Schedule Management:*
/setup - Create your first schedule
/myschedule - View all schedules
/edit <num> - Edit a schedule
/add - Add another schedule
/remove <num> - Remove a single schedule
/removeselect - Interactive schedule removal (select multiple)

*Other Commands:*
/stop - Pause all reminders
/startbot - Resume reminders
/settings - Message preferences
    """
    
    keyboard = [
        [InlineKeyboardButton("⏸️ Pause Bot", callback_data="pause_bot")],
        [InlineKeyboardButton("▶️ Resume Bot", callback_data="resume_bot")],
        [InlineKeyboardButton("📋 My Schedules", callback_data="view_schedules")],
        [InlineKeyboardButton("🗑️ Remove Schedules", callback_data="remove_select")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Get message object for both command and callback scenarios
    if update.message:
        await update.message.reply_text(help_text, reply_markup=reply_markup, parse_mode='Markdown')
    elif update.callback_query:
        await update.callback_query.message.reply_text(help_text, reply_markup=reply_markup, parse_mode='Markdown')

# Update the general callback handler to include the remove selection
async def general_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle general callback queries"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data == "view_schedules":
        await my_schedule(update, context)
    elif data == "setup_schedule":
        await setup(update, context)
    elif data == "add_schedule":
        await add_schedule(update, context)
    elif data == "edit_schedules":
        await edit_schedule(update, context)
    elif data == "settings_menu":
        await settings_command(update, context)
    elif data == "remove_select":
        await remove_schedule_selection(update, context)
        
# --- Main ---
if __name__ == '__main__':
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("setup", setup))
    application.add_handler(CommandHandler("add", add_schedule))
    application.add_handler(CommandHandler("myschedule", my_schedule))
    application.add_handler(CommandHandler("edit", edit_schedule))
    application.add_handler(CommandHandler("remove", remove_schedule))
    application.add_handler(CommandHandler("stop", stop_command))
    application.add_handler(CommandHandler("startbot", startbot_command))
    application.add_handler(CommandHandler("addmessage", add_message))
    application.add_handler(CommandHandler("mymessages", my_messages))
    application.add_handler(CommandHandler("clearmessages", clear_messages))
    application.add_handler(CommandHandler("settings", settings_command))
    
    # Bulk removal commands (keep only these)
    application.add_handler(CommandHandler("removeall", remove_all_schedules))
    application.add_handler(CommandHandler("removemultiple", remove_multiple_schedules))
    application.add_handler(CommandHandler("removeselect", remove_schedule_selection))

    # Add callback handlers for buttons
    application.add_handler(CallbackQueryHandler(days_button_handler, pattern="^(day_|quick_|days_done)"))
    application.add_handler(CallbackQueryHandler(settings_callback, pattern="^(pref_|view_messages|cancel_settings|confirm_clear|cancel_clear)"))
    application.add_handler(CallbackQueryHandler(pause_resume_button, pattern="^(pause_bot|resume_bot)"))
    application.add_handler(CallbackQueryHandler(general_callback_handler, pattern="^(view_schedules|setup_schedule|add_schedule|edit_schedules|settings_menu|remove_select)"))
    
    # Add removal callback handler (keep only this one)
    application.add_handler(CallbackQueryHandler(remove_callback_handler, pattern="^(select_remove_|execute_remove_selected|confirm_remove_selected|cancel_remove_selected|remove_all_prompt|confirm_remove_all|cancel_remove_all|cancel_remove_selection)"))

    # Add message handler for time inputs
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_time_input))

    print("Bot is running with all bug fixes...")
    application.run_polling()
