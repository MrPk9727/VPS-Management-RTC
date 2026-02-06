import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import subprocess
import json
from datetime import datetime
import shlex
import logging
import shutil
import os
from typing import Optional, List, Dict, Any
import threading
import time

# Load environment variables
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
MAIN_ADMIN_ID = int(os.getenv('MAIN_ADMIN_ID', '1210291131301101618'))
VPS_USER_ROLE_ID = int(os.getenv('VPS_USER_ROLE_ID', '1210291131301101618'))
DEFAULT_STORAGE_POOL = os.getenv('DEFAULT_STORAGE_POOL', 'default')
CPU_THRESHOLD = int(os.getenv('CPU_THRESHOLD', '90'))
RAM_THRESHOLD = int(os.getenv('RAM_THRESHOLD', '90'))
CHECK_INTERVAL = int(os.getenv('CHECK_INTERVAL', '600'))  # 10 minutes for VPS monitoring

# Configure logging to file and console
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('RathamCloud_vps_bot')

# Check if RTC command is available
RTC_EXECUTABLE = shutil.which("RTC")
if not RTC_EXECUTABLE:
    # Fallback to local directory
    local_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "RTC")
    if os.path.isfile(local_path) and os.access(local_path, os.X_OK):
        RTC_EXECUTABLE = local_path
    else:
        logger.error("RTC command not found. Please ensure RTC is installed in your PATH or in the bot directory.")
        raise SystemExit("RTC command not found. Please ensure RTC is installed.")

logger.info(f"Using RTC executable: {RTC_EXECUTABLE}")

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

# Disable the default help command
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# CPU monitoring settings
cpu_monitor_active = True

# Helper function to truncate text to a specific length
def truncate_text(text, max_length=1024):
    """Truncate text to max_length characters"""
    if not text:
        return text
    if len(text) <= max_length:
        return text
    return text[:max_length-3] + "..."

# Embed creation functions with black theme and RathamCloud branding
def create_embed(title, description="", color=0x1a1a1a):
    """Create a dark-themed embed with proper field length handling and RathamCloud branding"""
    embed = discord.Embed(
        title=truncate_text(f"🌟 RathamCloud - {title}", 256),
        description=truncate_text(description, 4096),
        color=color
    )

    embed.set_thumbnail(url="https://github.com/MrPk9727/logo/blob/main/logo-bg.png?raw=true")
    embed.set_footer(text=f"RathamCloud VPS Manager • {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                    icon_url="https://github.com/MrPk9727/logo/blob/main/logo-bg.png?raw=true")

    return embed

def add_field(embed, name, value, inline=False):
    """Add a field to an embed with proper truncation"""
    embed.add_field(
        name=truncate_text(f"▸ {name}", 256),
        value=truncate_text(value, 1024),
        inline=inline
    )
    return embed

def create_success_embed(title, description=""):
    return create_embed(title, description, color=0x00ff88)

def create_error_embed(title, description=""):
    return create_embed(title, description, color=0xff3366)

def create_info_embed(title, description=""):
    return create_embed(title, description, color=0x00ccff)

def create_warning_embed(title, description=""):
    return create_embed(title, description, color=0xffaa00)

# Data storage functions
def load_vps_data():
    try:
        with open('vps_data.json', 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        logger.warning("vps_data.json not found or corrupted, initializing empty data")
        return {}

def load_admin_data():
    try:
        with open('admin_data.json', 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        logger.warning("admin_data.json not found or corrupted, initializing with main admin")
        return {"admins": [str(MAIN_ADMIN_ID)]}

def load_port_data():
    try:
        with open('port_data.json', 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        logger.warning("port_data.json not found or corrupted, initializing empty data")
        return {"users": {}, "active_ports": {}}

# Load all data at startup
vps_data = load_vps_data()
admin_data = load_admin_data()
port_data = load_port_data()

# Save data function
def save_data():
    try:
        # Atomic save for vps_data
        temp_vps = 'vps_data.json.tmp'
        with open(temp_vps, 'w') as f:
            json.dump(vps_data, f, indent=4)
        os.replace(temp_vps, 'vps_data.json')
        
        temp_admin = 'admin_data.json.tmp'
        with open(temp_admin, 'w') as f:
            json.dump(admin_data, f, indent=4)
        os.replace(temp_admin, 'admin_data.json')
        
        temp_port = 'port_data.json.tmp'
        with open(temp_port, 'w') as f:
            json.dump(port_data, f, indent=4)
        os.replace(temp_port, 'port_data.json')
        
        logger.info("Data saved successfully")
    except Exception as e:
        logger.error(f"Error saving data: {e}")

# Admin checks - Updated to not send message in predicate, more specific errors
def is_admin():
    async def predicate(ctx):
        user_id = str(ctx.author.id)
        if user_id == str(MAIN_ADMIN_ID) or user_id in admin_data.get("admins", []):
            return True
        # Custom error handling moved to on_command_error for better UX
        raise commands.CheckFailure(f"You need admin permissions to use this command. Contact RathamCloud support.")
    return commands.check(predicate)

def is_main_admin():
    async def predicate(ctx):
        if str(ctx.author.id) == str(MAIN_ADMIN_ID):
            return True
        raise commands.CheckFailure("Only the main admin can use this command.")
    return commands.check(predicate)

# Clean RTC command execution
async def execute_RTC(command, timeout=120):
    """Execute RTC command with timeout and error handling"""
    try:
        cmd = shlex.split(command)
        # Replace 'RTC' with the actual path if it's the first argument
        if cmd and cmd[0] == "RTC":
            cmd[0] = RTC_EXECUTABLE
            
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)

        if proc.returncode != 0:
            error = stderr.decode().strip() if stderr else "Command failed with no error output"
            raise Exception(error)

        return stdout.decode().strip() if stdout else True
    except asyncio.TimeoutError:
        logger.error(f"RTC command timed out: {command}")
        raise Exception(f"Command timed out after {timeout} seconds")
    except Exception as e:
        logger.error(f"RTC Error: {command} - {str(e)}")
        raise

def get_next_available_port():
    used_ports = set()
    for user_ports in port_data["active_ports"].values():
        for port_info in user_ports:
            used_ports.add(port_info["host_port"])
    
    for p in range(10000, 20000):
        if p not in used_ports:
            return p
    return None

# Get or create VPS user role
async def get_or_create_vps_role(guild):
    """Get or create the VPS User role"""
    global VPS_USER_ROLE_ID
    
    if VPS_USER_ROLE_ID:
        role = guild.get_role(VPS_USER_ROLE_ID)
        if role:
            return role
    
    role = discord.utils.get(guild.roles, name="RathamCloud VPS User")
    if role:
        VPS_USER_ROLE_ID = role.id
        return role
    
    try:
        role = await guild.create_role(
            name="RathamCloud VPS User",
            color=discord.Color.dark_purple(),
            reason="RathamCloud VPS User role for bot management",
            permissions=discord.Permissions.none()
        )
        VPS_USER_ROLE_ID = role.id
        logger.info(f"Created RathamCloud VPS User role: {role.name} (ID: {role.id})")
        return role
    except Exception as e:
        logger.error(f"Failed to create RathamCloud VPS User role: {e}")
        return None

# Host CPU monitoring function
async def get_cpu_usage():
    """Get current CPU usage percentage"""
    try:
        # Get CPU usage using top command asynchronously
        proc = await asyncio.create_subprocess_exec(
            'top', '-bn1',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        output = stdout.decode()
        
        # Parse the output to get CPU usage
        for line in output.split('\n'):
            if '%Cpu(s):' in line:
                words = line.split()
                for i, word in enumerate(words):
                    if word == 'id,':
                        idle_str = words[i-1].rstrip(',')
                        try:
                            idle = float(idle_str)
                            usage = 100.0 - idle
                            return usage
                        except ValueError:
                            pass
                break
        return 0.0
    except Exception as e:
        logger.error(f"Error getting CPU usage: {e}")
        return 0.0

async def cpu_monitor():
    """Monitor CPU usage and stop all VPS if threshold is exceeded"""
    global cpu_monitor_active
    
    while cpu_monitor_active:
        try:
            cpu_usage = await get_cpu_usage()
            logger.info(f"Current CPU usage: {cpu_usage}%")
            
            if cpu_usage > CPU_THRESHOLD:
                logger.warning(f"CPU usage ({cpu_usage}%) exceeded threshold ({CPU_THRESHOLD}%). Stopping all VPS.")
                
                try:
                    await execute_RTC('RTC stop --all --force')
                    logger.info("All VPS stopped due to high CPU usage")
                    
                    # Update all VPS status in database
                    for user_id, vps_list in list(vps_data.items()):
                        for vps in vps_list:
                            if vps.get('status') == 'running':
                                vps['status'] = 'stopped'
                    save_data()
                except Exception as e:
                    logger.error(f"Error stopping all VPS: {e}")
            
            await asyncio.sleep(60)  # Check host every 60 seconds
        except Exception as e:
            logger.error(f"Error in CPU monitor: {e}")
            await asyncio.sleep(60)

# Helper functions for container stats
async def get_container_status(container_name):
    """Get the status of the RTC container"""
    try:
        proc = await asyncio.create_subprocess_exec(
            RTC_EXECUTABLE, "info", container_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        output = stdout.decode()
        for line in output.splitlines():
            if line.startswith("Status: "):
                return line.split(": ", 1)[1].strip()
        return "Unknown"
    except Exception:
        return "Unknown"

async def get_container_cpu(container_name):
    """Get CPU usage inside the container as string"""
    usage = await get_container_cpu_pct(container_name)
    return f"{usage:.1f}%"

async def get_container_cpu_pct(container_name):
    """Get CPU usage percentage inside the container as float"""
    try:
        proc = await asyncio.create_subprocess_exec(
            RTC_EXECUTABLE, "exec", container_name, "--", "top", "-bn1",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        output = stdout.decode()
        for line in output.splitlines():
            if '%Cpu(s):' in line:
                words = line.split()
                for i, word in enumerate(words):
                    if word == 'id,':
                        idle_str = words[i-1].rstrip(',')
                        try:
                            idle = float(idle_str)
                            usage = 100.0 - idle
                            return usage
                        except ValueError:
                            pass
                break
        return 0.0
    except Exception as e:
        logger.error(f"Error getting CPU for {container_name}: {e}")
        return 0.0

async def get_container_memory(container_name):
    """Get memory usage inside the container"""
    try:
        proc = await asyncio.create_subprocess_exec(
            RTC_EXECUTABLE, "exec", container_name, "--", "free", "-m",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        lines = stdout.decode().splitlines()
        if len(lines) > 1:
            parts = lines[1].split()
            total = int(parts[1])
            used = int(parts[2])
            usage_pct = (used / total * 100) if total > 0 else 0
            return f"{used}/{total} MB ({usage_pct:.1f}%)"
        return "Unknown"
    except Exception:
        return "Unknown"

async def get_container_ram_pct(container_name):
    """Get RAM usage percentage inside the container as float"""
    try:
        proc = await asyncio.create_subprocess_exec(
            RTC_EXECUTABLE, "exec", container_name, "--", "free", "-m",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        lines = stdout.decode().splitlines()
        if len(lines) > 1:
            parts = lines[1].split()
            total = int(parts[1])
            used = int(parts[2])
            usage_pct = (used / total * 100) if total > 0 else 0
            return usage_pct
        return 0.0
    except Exception as e:
        logger.error(f"Error getting RAM for {container_name}: {e}")
        return 0.0

async def get_container_disk(container_name):
    """Get disk usage inside the container"""
    try:
        proc = await asyncio.create_subprocess_exec(
            RTC_EXECUTABLE, "exec", container_name, "--", "df", "-h", "/",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        lines = stdout.decode().splitlines()
        for line in lines:
            if '/dev/' in line and ' /' in line:
                parts = line.split()
                if len(parts) >= 5:
                    used = parts[2]
                    size = parts[1]
                    perc = parts[4]
                    return f"{used}/{size} ({perc})"
        return "Unknown"
    except Exception:
        return "Unknown"

def get_uptime():
    """Get host uptime"""
    try:
        result = subprocess.run(['uptime'], capture_output=True, text=True)
        return result.stdout.strip()
    except Exception:
        return "Unknown"

# VPS monitoring task
async def vps_monitor():
    """Monitor each VPS for high CPU/RAM usage every 10 minutes"""
    while True:
        try:
            for user_id, vps_list in list(vps_data.items()):
                for vps in list(vps_list):
                    if vps.get('status') == 'running' and not vps.get('suspended', False):
                        container = vps['container_name']
                        cpu = await get_container_cpu_pct(container)
                        ram = await get_container_ram_pct(container)
                        if cpu > CPU_THRESHOLD or ram > RAM_THRESHOLD:
                            reason = f"High resource usage: CPU {cpu:.1f}%, RAM {ram:.1f}% (threshold: {CPU_THRESHOLD}% CPU / {RAM_THRESHOLD}% RAM)"
                            logger.warning(f"Suspending {container}: {reason}")
                            try:
                                await execute_RTC(f"RTC stop {container}")
                                vps['status'] = 'suspended'
                                vps['suspended'] = True
                                if 'suspension_history' not in vps:
                                    vps['suspension_history'] = []
                                vps['suspension_history'].append({
                                    'time': datetime.now().isoformat(),
                                    'reason': reason,
                                    'by': 'RathamCloud Auto-System'
                                })
                                save_data()
                                # DM owner
                                try:
                                    owner = await bot.fetch_user(int(user_id))
                                    embed = create_warning_embed("🚨 VPS Auto-Suspended", f"Your VPS `{container}` has been automatically suspended due to high resource usage.\n\n**Reason:** {reason}\n\nContact RathamCloud admin to unsuspend and address the issue.")
                                    await owner.send(embed=embed)
                                except Exception as dm_e:
                                    logger.error(f"Failed to DM owner {user_id}: {dm_e}")
                            except Exception as e:
                                logger.error(f"Failed to suspend {container}: {e}")
            await asyncio.sleep(CHECK_INTERVAL)
        except Exception as e:
            logger.error(f"VPS monitor error: {e}")
            await asyncio.sleep(60)

# Bot events
@bot.event
async def on_ready():
    logger.info(f'{bot.user} has connected to Discord!')
    
    # To sync to a specific test server instantly, uncomment and set your Guild ID:
    # TEST_GUILD_ID = 123456789012345678  # Replace with your server ID
    # guild = discord.Object(id=TEST_GUILD_ID)
    # bot.tree.copy_global_to(guild=guild)
    # await bot.tree.sync(guild=guild)

    try:
        # Global sync (takes time to propagate)
        await bot.tree.sync()
        logger.info("Global slash commands synced")
    except Exception as e:
        logger.error(f"Failed to sync slash commands: {e}")
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="RathamCloud VPS Manager"))
    bot.loop.create_task(vps_monitor())
    bot.loop.create_task(cpu_monitor())
    logger.info("RathamCloud Bot is ready! VPS monitoring started.")

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    elif isinstance(error, commands.NoPrivateMessage):
        await ctx.send(embed=create_error_embed("Context Error", "This command cannot be used in Direct Messages."))
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(embed=create_error_embed("Missing Argument", f"Please check command usage. Error: {error}"))
    elif isinstance(error, commands.BadArgument):
        await ctx.send(embed=create_error_embed("Invalid Argument", "Please check your input and try again."))
    elif isinstance(error, commands.CheckFailure):
        error_msg = str(error) if str(error) != "Admin required" else "You need admin permissions for this command. Contact RathamCloud support."
        await ctx.send(embed=create_error_embed("Access Denied", error_msg))
    elif isinstance(error, discord.NotFound):
        await ctx.send(embed=create_error_embed("Error", "The requested resource was not found. Please try again."))
    else:
        logger.error(f"Command error: {error}")
        await ctx.send(embed=create_error_embed("System Error", "An unexpected error occurred. RathamCloud support has been notified."))

# Bot commands
@bot.command(name='sync')
@is_main_admin()
async def sync_commands(ctx, guild_id: Optional[int] = None):
    """Sync slash commands instantly to a server or globally"""
    if guild_id:
        guild = discord.Object(id=guild_id)
    else:
        guild = ctx.guild

    try:
        if guild:
            bot.tree.copy_global_to(guild=guild)
            synced = await bot.tree.sync(guild=guild)
            await ctx.send(embed=create_success_embed("Sync Complete", f"Synced {len(synced)} commands to guild `{guild.id if hasattr(guild, 'id') else guild}`."))
        else:
            synced = await bot.tree.sync()
            await ctx.send(embed=create_success_embed("Global Sync", f"Synced {len(synced)} commands globally. (May take up to 1 hour)"))
    except Exception as e:
        await ctx.send(embed=create_error_embed("Sync Failed", str(e)))

@bot.hybrid_command(name='ping')
async def ping(ctx):
    """Check bot latency"""
    latency = round(bot.latency * 1000)
    embed = create_success_embed("Pong!", f"RathamCloud Bot latency: {latency}ms")
    await ctx.send(embed=embed)

@bot.hybrid_command(name='uptime')
async def uptime(ctx):
    """Show host uptime"""
    up = get_uptime()
    embed = create_info_embed("Host Uptime", up)
    await ctx.send(embed=embed)

@bot.command(name='dynamic-register')
@is_main_admin()
async def dynamic_register(ctx, guild_id: int):
    """Dynamically adds a slash command to a specific guild without decorators"""
    
    # 1. Define the callback function that the slash command will execute
    async def dynamic_hello_callback(interaction: discord.Interaction):
        await interaction.response.send_message(
            f"Hello! This command was dynamically registered to this guild by {ctx.author.name}.",
            ephemeral=True
        )

    # 2. Create the Command object manually
    new_command = app_commands.Command(
        name="dynamic-hello",
        description="A command added at runtime without decorators",
        callback=dynamic_hello_callback
    )

    try:
        # 3. Add the command to the tree for the specific guild
        guild_obj = discord.Object(id=guild_id)
        bot.tree.add_command(new_command, guild=guild_obj)
        
        # 4. Sync the tree for that guild to make it appear instantly
        synced = await bot.tree.sync(guild=guild_obj)
        await ctx.send(embed=create_success_embed("Dynamic Registration", f"Successfully registered `/dynamic-hello` to guild `{guild_id}`."))
    except Exception as e:
        await ctx.send(embed=create_error_embed("Registration Failed", str(e)))

@bot.command(name='dynamic-group-register')
@is_main_admin()
async def dynamic_group_register(ctx, guild_id: int):
    """Dynamically adds a command group with subcommands to a specific guild"""
    
    # 1. Create the Group object
    # Groups allow you to nest commands, resulting in a structure like /vps-tools status
    my_group = app_commands.Group(name="vps-tools", description="Dynamic VPS management tools")

    # 2. Define the callback functions for the subcommands
    async def status_callback(interaction: discord.Interaction):
        await interaction.response.send_message("System status: All RathamCloud nodes are healthy.", ephemeral=True)

    async def info_callback(interaction: discord.Interaction):
        await interaction.response.send_message("This is a dynamically generated info command within a group.", ephemeral=True)

    # 3. Create the individual Command objects for the subcommands
    status_cmd = app_commands.Command(
        name="status",
        description="Check RathamCloud system status",
        callback=status_callback
    )

    info_cmd = app_commands.Command(
        name="info",
        description="Get dynamic group information",
        callback=info_callback
    )

    # 4. Add the subcommands to the group
    my_group.add_command(status_cmd)
    my_group.add_command(info_cmd)

    try:
        # 5. Add the group to the tree for the specific guild
        guild_obj = discord.Object(id=guild_id)
        bot.tree.add_command(my_group, guild=guild_obj)
        
        # 6. Sync the tree for that guild to make the group appear instantly
        await bot.tree.sync(guild=guild_obj)
        await ctx.send(embed=create_success_embed("Dynamic Group Registered", f"Successfully registered `/vps-tools` group with {len(my_group.commands)} subcommands to guild `{guild_id}`."))
    except Exception as e:
        await ctx.send(embed=create_error_embed("Group Registration Failed", str(e)))

@bot.command(name='dynamic-autocomplete-register')
@is_main_admin()
async def dynamic_autocomplete_register(ctx, guild_id: int):
    """Dynamically adds a slash command with autocomplete to a specific guild"""
    
    # 1. Define the autocomplete callback
    # This function generates suggestions based on what the user is typing
    async def container_autocomplete(
        interaction: discord.Interaction, 
        current: str
    ) -> List[app_commands.Choice[str]]:
        choices = []
        # Search through all containers in vps_data
        for user_id, vps_list in vps_data.items():
            for vps in vps_list:
                name = vps['container_name']
                if current.lower() in name.lower():
                    choices.append(app_commands.Choice(name=name, value=name))
        
        # Limit to 25 choices (Discord's maximum)
        return choices[:25]

    # 2. Define the main command callback
    async def search_callback(interaction: discord.Interaction, container_name: str):
        await interaction.response.send_message(
            f"You selected RathamCloud container: `{container_name}`",
            ephemeral=True
        )

    # 3. Create the Command object
    # The parameter name in the callback ('container_name') is what we link to autocomplete
    new_command = app_commands.Command(
        name="vps-search",
        description="Search for a RathamCloud container with autocomplete",
        callback=search_callback
    )

    # 4. Link the autocomplete function to the 'container_name' parameter
    new_command.autocomplete("container_name")(container_autocomplete)

    try:
        # 5. Add to the tree for the specific guild
        guild_obj = discord.Object(id=guild_id)
        bot.tree.add_command(new_command, guild=guild_obj)
        
        # 6. Sync the tree
        await bot.tree.sync(guild=guild_obj)
        await ctx.send(embed=create_success_embed(
            "Dynamic Autocomplete Registered", 
            f"Successfully registered `/vps-search` with autocomplete to guild `{guild_id}`."
        ))
    except Exception as e:
        await ctx.send(embed=create_error_embed("Registration Failed", str(e)))

# Example of a command restricted to specific servers
# Replace 123456789012345678 with your actual server ID
@bot.hybrid_command(name='admin-debug')
@app_commands.guilds(discord.Object(id=1210291131301101618))
@is_main_admin()
async def admin_debug(ctx):
    """A debug command visible only in the management server"""
    await ctx.send(embed=create_info_embed("Debug Info", "This command is only visible in this server."))

@bot.hybrid_command(name='myvps')
async def my_vps(ctx):
    """List your VPS"""
    user_id = str(ctx.author.id)
    vps_list = vps_data.get(user_id, [])
    if not vps_list:
        await ctx.send(embed=create_embed("No VPS Found", "You don't have any RathamCloud VPS. Contact an admin to create one.", 0xff3366))
        return
    embed = create_info_embed("My RathamCloud VPS", "")
    text = []
    for i, vps in enumerate(vps_list):
        status = vps.get('status', 'unknown').upper()
        if vps.get('suspended', False):
            status += " (SUSPENDED)"
        config = vps.get('config', 'Custom')
        text.append(f"**VPS {i+1}:** `{vps['container_name']}` - {status} - {config}")
    add_field(embed, "Your VPS", "\n".join(text), False)
    add_field(embed, "Actions", "Use `!manage` to start/stop/reinstall", False)
    await ctx.send(embed=embed)

@bot.command(name='RTC-list')
@is_admin()
async def RTC_list(ctx):
    """List all RTC containers"""
    try:
        result = await execute_RTC("RTC list")
        embed = create_info_embed("RathamCloud RTC Containers List", result)
        await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(embed=create_error_embed("Error", str(e)))

@bot.hybrid_command(name='create')
@is_admin()
@commands.guild_only()
async def create_vps(ctx, ram: int, cpu: int, disk: int, user: discord.Member):
    """Create a custom VPS for a user (Admin only) - !create <ram_gb> <cpu_cores> <disk_gb> <user>"""
    if ram <= 0 or cpu <= 0 or disk <= 0:
        await ctx.send(embed=create_error_embed("Invalid Specs", "RAM, CPU, and Disk must be positive integers."))
        return

    user_id = str(user.id)
    if user_id not in vps_data:
        vps_data[user_id] = []

    vps_count = len(vps_data[user_id]) + 1
    container_name = f"RathamCloud-vps-{user_id}-{vps_count}"
    ram_mb = ram * 1024

    await ctx.send(embed=create_info_embed("Creating RathamCloud VPS", f"Deploying VPS for {user.mention}..."))

    try:
        # Fixed: Use init for config before start
        await execute_RTC(f"RTC init ubuntu:22.04 {container_name} --storage {DEFAULT_STORAGE_POOL}")
        await execute_RTC(f"RTC config set {container_name} limits.memory {ram_mb}MB")
        await execute_RTC(f"RTC config set {container_name} limits.cpu {cpu}")
        
        # Always resize the disk to specified size
        await execute_RTC(f"RTC config device set {container_name} root size {disk}GB")
        # Start to apply changes
        await execute_RTC(f"RTC start {container_name}")

        config_str = f"{ram}GB RAM / {cpu} CPU / {disk}GB Disk"
        vps_info = {
            "container_name": container_name,
            "ram": f"{ram}GB",
            "cpu": str(cpu),
            "storage": f"{disk}GB",
            "config": config_str,
            "status": "running",
            "suspended": False,
            "suspension_history": [],
            "created_at": datetime.now().isoformat(),
            "shared_with": []
        }
        vps_data[user_id].append(vps_info)
        save_data()

        # Get or create VPS role and assign to user
        if ctx.guild:
            vps_role = await get_or_create_vps_role(ctx.guild)
            if vps_role:
                try:
                    await user.add_roles(vps_role, reason="RathamCloud VPS ownership granted")
                except discord.Forbidden:
                    logger.warning(f"Failed to assign RathamCloud VPS role to {user.name}")

        # Create success embed for channel
        embed = create_success_embed("RathamCloud VPS Created Successfully")
        add_field(embed, "Owner", user.mention, True)
        add_field(embed, "VPS ID", f"#{vps_count}", True)
        add_field(embed, "Container", f"`{container_name}`", True)
        add_field(embed, "Resources", f"**RAM:** {ram}GB\n**CPU:** {cpu} Cores\n**Storage:** {disk}GB", False)
        await ctx.send(embed=embed)

        # Send comprehensive DM to user
        try:
            dm_embed = create_success_embed("RathamCloud VPS Created!", f"Your VPS has been successfully deployed by an admin!")
            add_field(dm_embed, "VPS Details", f"**VPS ID:** #{vps_count}\n**Container Name:** `{container_name}`\n**Configuration:** {config_str}\n**Status:** Running\n**Created:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", False)
            add_field(dm_embed, "Management", "• Use `!manage` to start/stop/reinstall your RathamCloud VPS\n• Use `!manage` → SSH for terminal access\n• Contact RathamCloud admin for upgrades or issues", False)
            add_field(dm_embed, "Important Notes", "• Full root access via SSH\n• Ubuntu 22.04 pre-installed\n• Back up your data regularly with RathamCloud tools", False)
            await user.send(embed=dm_embed)
        except discord.Forbidden:
            await ctx.send(embed=create_info_embed("Notification Failed", f"Couldn't send DM to {user.mention}. Please ensure DMs are enabled."))

    except Exception as e:
        await ctx.send(embed=create_error_embed("Creation Failed", f"Error: {str(e)}"))

class ManageView(discord.ui.View):
    def __init__(self, user_id, vps_list, is_shared=False, owner_id=None, is_admin=False):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.vps_list = vps_list
        self.selected_index = None
        self.is_shared = is_shared
        self.owner_id = owner_id or user_id
        self.is_admin = is_admin

        if len(vps_list) > 1:
            options = [
                discord.SelectOption(
                    label=f"RathamCloud VPS {i+1} ({v.get('config', 'Custom')})",
                    description=f"Status: {v.get('status', 'unknown')}",
                    value=str(i)
                ) for i, v in enumerate(vps_list)
            ]
            self.select = discord.ui.Select(placeholder="Select a RathamCloud VPS to manage", options=options)
            self.select.callback = self.select_vps
            self.add_item(self.select)
            self.initial_embed = create_embed("RathamCloud VPS Management", "Select a VPS from the dropdown menu below.", 0x1a1a1a)
            add_field(self.initial_embed, "Available VPS", "\n".join([f"**VPS {i+1}:** `{v['container_name']}` - Status: `{v.get('status', 'unknown').upper()}`" for i, v in enumerate(vps_list)]), False)
        else:
            self.selected_index = 0
            self.initial_embed = None
            self.add_action_buttons()

    async def get_initial_embed(self):
        if self.initial_embed is not None:
            return self.initial_embed
        self.initial_embed = await self.create_vps_embed(self.selected_index)
        return self.initial_embed

    async def create_vps_embed(self, index):
        vps = self.vps_list[index]
        status = vps.get('status', 'unknown')
        suspended = vps.get('suspended', False)
        status_color = 0x00ff88 if status == 'running' and not suspended else 0xffaa00 if suspended else 0xff3366

        # Fetch live stats
        container_name = vps['container_name']
        RTC_status = await get_container_status(container_name)
        cpu_usage = await get_container_cpu(container_name)
        memory_usage = await get_container_memory(container_name)
        disk_usage = await get_container_disk(container_name)

        status_text = f"{status.upper()}"
        if suspended:
            status_text += " (SUSPENDED)"

        owner_text = ""
        if self.is_admin and self.owner_id != self.user_id:
            try:
                owner_user = bot.get_user(int(self.owner_id))
                owner_text = f"\n**Owner:** {owner_user.mention}"
            except:
                owner_text = f"\n**Owner ID:** {self.owner_id}"

        embed = create_embed(
            f"RathamCloud VPS Management - VPS {index + 1}",
            f"Managing container: `{container_name}`{owner_text}",
            status_color
        )

        resource_info = f"**Configuration:** {vps.get('config', 'Custom')}\n"
        resource_info += f"**Status:** `{status_text}`\n"
        resource_info += f"**RAM:** {vps['ram']}\n"
        resource_info += f"**CPU:** {vps['cpu']} Cores\n"
        resource_info += f"**Storage:** {vps['storage']}"

        add_field(embed, "📊 Allocated Resources", resource_info, False)

        if suspended:
            add_field(embed, "⚠️ Suspended", "This RathamCloud VPS is suspended. Contact an admin to unsuspend.", False)

        live_stats = f"**CPU Usage:** {cpu_usage}\n**Memory:** {memory_usage}\n**Disk:** {disk_usage}"
        add_field(embed, "📈 Live Usage", live_stats, False)

        add_field(embed, "🎮 Controls", "Use the buttons below to manage your RathamCloud VPS", False)

        return embed

    def add_action_buttons(self):
        if not self.is_shared and not self.is_admin:
            reinstall_button = discord.ui.Button(label="🔄 Reinstall", style=discord.ButtonStyle.danger)
            reinstall_button.callback = lambda inter: self.action_callback(inter, 'reinstall')
            self.add_item(reinstall_button)

        start_button = discord.ui.Button(label="▶ Start", style=discord.ButtonStyle.success)
        start_button.callback = lambda inter: self.action_callback(inter, 'start')
        stop_button = discord.ui.Button(label="⏸ Stop", style=discord.ButtonStyle.secondary)
        stop_button.callback = lambda inter: self.action_callback(inter, 'stop')
        ssh_button = discord.ui.Button(label="🔑 SSH", style=discord.ButtonStyle.primary)
        ssh_button.callback = lambda inter: self.action_callback(inter, 'tmate')
        stats_button = discord.ui.Button(label="📊 Stats", style=discord.ButtonStyle.secondary)
        stats_button.callback = lambda inter: self.action_callback(inter, 'stats')

        self.add_item(start_button)
        self.add_item(stop_button)
        self.add_item(ssh_button)
        self.add_item(stats_button)

    async def select_vps(self, interaction: discord.Interaction):
        if str(interaction.user.id) != self.user_id and not self.is_admin:
            await interaction.response.send_message(embed=create_error_embed("Access Denied", "This is not your RathamCloud VPS!"), ephemeral=True)
            return
        self.selected_index = int(self.select.values[0])
        new_embed = await self.create_vps_embed(self.selected_index)
        self.clear_items()
        self.add_action_buttons()
        await interaction.response.edit_message(embed=new_embed, view=self)

    async def action_callback(self, interaction: discord.Interaction, action: str):
        if str(interaction.user.id) != self.user_id and not self.is_admin:
            await interaction.response.send_message(embed=create_error_embed("Access Denied", "This is not your RathamCloud VPS!"), ephemeral=True)
            return

        if self.is_shared:
            vps = vps_data[self.owner_id][self.selected_index]
        else:
            vps = self.vps_list[self.selected_index]
        
        suspended = vps.get('suspended', False)
        if suspended and not self.is_admin and action != 'stats':
            await interaction.response.send_message(embed=create_error_embed("Access Denied", "This RathamCloud VPS is suspended. Contact an admin to unsuspend."), ephemeral=True)
            return
        
        container_name = vps["container_name"]

        if action == 'stats':
            status = await get_container_status(container_name)
            cpu_usage = await get_container_cpu(container_name)
            memory_usage = await get_container_memory(container_name)
            disk_usage = await get_container_disk(container_name)
            stats_embed = create_info_embed("📈 RathamCloud Live Statistics", f"Real-time stats for `{container_name}`")
            add_field(stats_embed, "Status", f"`{status.upper()}`", True)
            add_field(stats_embed, "CPU", cpu_usage, True)
            add_field(stats_embed, "Memory", memory_usage, True)
            add_field(stats_embed, "Disk", disk_usage, True)
            await interaction.response.send_message(embed=stats_embed, ephemeral=True)
            return

        if action == 'reinstall':
            if self.is_shared or self.is_admin:
                await interaction.response.send_message(embed=create_error_embed("Access Denied", "Only the RathamCloud VPS owner can reinstall!"), ephemeral=True)
                return
            if suspended:
                await interaction.response.send_message(embed=create_error_embed("Cannot Reinstall", "Unsuspend the RathamCloud VPS first."), ephemeral=True)
                return

            confirm_embed = create_warning_embed("RathamCloud Reinstall Warning",
                f"⚠️ **WARNING:** This will erase all data on VPS `{container_name}` and reinstall Ubuntu 22.04.\n\n"
                f"This action cannot be undone. Continue?")

            class ConfirmView(discord.ui.View):
                def __init__(self, parent_view, container_name, vps, owner_id, selected_index):
                    super().__init__(timeout=60)
                    self.parent_view = parent_view
                    self.container_name = container_name
                    self.vps = vps
                    self.owner_id = owner_id
                    self.selected_index = selected_index

                @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger)
                async def confirm(self, interaction: discord.Interaction, item: discord.ui.Button):
                    await interaction.response.defer(ephemeral=True)
                    try:
                        # Force delete the container first
                        await interaction.followup.send(embed=create_info_embed("Deleting Container", f"Forcefully removing container `{self.container_name}`..."), ephemeral=True)
                        # Force stop before deletion to ensure clean removal
                        try:
                            await execute_RTC(f"RTC stop {self.container_name} --force")
                        except Exception:
                            pass # Ignore errors if container is already stopped or doesn't exist
                        await execute_RTC(f"RTC delete {self.container_name} --force")

                        # Recreate with original specifications - Fixed init + start
                        await interaction.followup.send(embed=create_info_embed("Recreating Container", f"Creating new RathamCloud container `{self.container_name}`..."), ephemeral=True)
                        original_ram = self.vps["ram"]
                        original_cpu = self.vps["cpu"]
                        original_storage = self.vps["storage"]
                        ram_gb = int(original_ram.replace("GB", ""))
                        ram_mb = ram_gb * 1024
                        storage_gb = int(original_storage.replace("GB", ""))

                        await execute_RTC(f"RTC init ubuntu:22.04 {self.container_name} --storage {DEFAULT_STORAGE_POOL}")
                        await execute_RTC(f"RTC config set {self.container_name} limits.memory {ram_mb}MB")
                        await execute_RTC(f"RTC config set {self.container_name} limits.cpu {original_cpu}")
                        await execute_RTC(f"RTC config device set {self.container_name} root size {storage_gb}GB")
                        await execute_RTC(f"RTC start {self.container_name}")

                        self.vps["status"] = "running"
                        self.vps["suspended"] = False
                        self.vps["created_at"] = datetime.now().isoformat()
                        config_str = f"{ram_gb}GB RAM / {original_cpu} CPU / {storage_gb}GB Disk"
                        self.vps["config"] = config_str
                        save_data()
                        await interaction.followup.send(embed=create_success_embed("Reinstall Complete", f"RathamCloud VPS `{self.container_name}` has been successfully reinstalled!"), ephemeral=True)

                        # Edit the original message if possible, but since ephemeral, send updated embed as followup
                        new_embed = await self.parent_view.create_vps_embed(self.parent_view.selected_index)
                        await interaction.followup.send(embed=new_embed, ephemeral=True)

                    except Exception as e:
                        await interaction.followup.send(embed=create_error_embed("Reinstall Failed", f"Error: {str(e)}"), ephemeral=True)

                @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
                async def cancel(self, interaction: discord.Interaction, item: discord.ui.Button):
                    new_embed = await self.parent_view.create_vps_embed(self.parent_view.selected_index)
                    await interaction.response.edit_message(embed=new_embed, view=self.parent_view)

            await interaction.response.send_message(embed=confirm_embed, view=ConfirmView(self, container_name, vps, self.owner_id, self.selected_index), ephemeral=True)

        elif action == 'start':
            await interaction.response.defer(ephemeral=True)
            if suspended:
                vps['suspended'] = False
                save_data()
            try:
                await execute_RTC(f"RTC start {container_name}")
                vps["status"] = "running"
                save_data()
                await interaction.followup.send(embed=create_success_embed("VPS Started", f"RathamCloud VPS `{container_name}` is now running!"), ephemeral=True)
                new_embed = await self.create_vps_embed(self.selected_index)
                await interaction.message.edit(embed=new_embed, view=self)
            except Exception as e:
                await interaction.followup.send(embed=create_error_embed("Start Failed", str(e)), ephemeral=True)

        elif action == 'stop':
            await interaction.response.defer(ephemeral=True)
            if suspended:
                vps['suspended'] = False
                save_data()
            try:
                await execute_RTC(f"RTC stop {container_name}", timeout=120)
                vps["status"] = "stopped"
                save_data()
                await interaction.followup.send(embed=create_success_embed("VPS Stopped", f"RathamCloud VPS `{container_name}` has been stopped!"), ephemeral=True)
                new_embed = await self.create_vps_embed(self.selected_index)
                await interaction.message.edit(embed=new_embed, view=self)
            except Exception as e:
                await interaction.followup.send(embed=create_error_embed("Stop Failed", str(e)), ephemeral=True)

        elif action == 'tmate':
            if suspended:
                await interaction.response.send_message(embed=create_error_embed("Access Denied", "Cannot access suspended RathamCloud VPS."), ephemeral=True)
                return
            await interaction.response.send_message(embed=create_info_embed("SSH Access", "Generating RathamCloud SSH connection..."), ephemeral=True)

            try:
                # Check if tmate exists
                check_proc = await asyncio.create_subprocess_exec(
                    RTC_EXECUTABLE, "exec", container_name, "--", "which", "tmate",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await check_proc.communicate()

                if check_proc.returncode != 0:
                    await interaction.followup.send(embed=create_info_embed("Installing SSH", "Installing tmate..."), ephemeral=True)
                    await execute_RTC(f"RTC exec {container_name} -- sudo apt-get update -y")
                    await execute_RTC(f"RTC exec {container_name} -- sudo apt-get install tmate -y")
                    await interaction.followup.send(embed=create_success_embed("Installed", "RathamCloud SSH service installed!"), ephemeral=True)

                # Start tmate with unique session name using timestamp
                session_name = f"RathamCloud-session-{datetime.now().strftime('%Y%m%d%H%M%S')}"
                await execute_RTC(f"RTC exec {container_name} -- tmate -S /tmp/{session_name}.sock new-session -d")
                await asyncio.sleep(3)

                # Get SSH link
                ssh_proc = await asyncio.create_subprocess_exec(
                    RTC_EXECUTABLE, "exec", container_name, "--", "tmate", "-S", f"/tmp/{session_name}.sock", "display", "-p", "#{tmate_ssh}",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await ssh_proc.communicate()
                ssh_url = stdout.decode().strip() if stdout else None

                if ssh_url:
                    try:
                        ssh_embed = create_embed("🔑 RathamCloud SSH Access", f"SSH connection for VPS `{container_name}`:", 0x00ff88)
                        add_field(ssh_embed, "Command", f"```{ssh_url}```", False)
                        add_field(ssh_embed, "⚠️ Security", "This link is temporary. Do not share it.", False)
                        add_field(ssh_embed, "📝 Session", f"Session ID: {session_name}", False)
                        await interaction.user.send(embed=ssh_embed)
                        await interaction.followup.send(embed=create_success_embed("SSH Sent", f"Check your DMs for RathamCloud SSH link! Session: {session_name}"), ephemeral=True)
                    except discord.Forbidden:
                        await interaction.followup.send(embed=create_error_embed("DM Failed", "Enable DMs to receive RathamCloud SSH link!"), ephemeral=True)
                else:
                    error_msg = stderr.decode().strip() if stderr else "Unknown error"
                    await interaction.followup.send(embed=create_error_embed("SSH Failed", error_msg), ephemeral=True)
            except Exception as e:
                await interaction.followup.send(embed=create_error_embed("SSH Error", str(e)), ephemeral=True)

@bot.command(name='manage')
async def manage_vps(ctx, user: discord.Member = None):
    """Manage your RathamCloud VPS or another user's VPS (Admin only)"""
    # Check if user is trying to manage someone else's VPS
    if user:
        # Only admins can manage other users' VPS
        user_id_check = str(ctx.author.id)
        if user_id_check != str(MAIN_ADMIN_ID) and user_id_check not in admin_data.get("admins", []):
            await ctx.send(embed=create_error_embed("Access Denied", "Only RathamCloud admins can manage other users' VPS."))
            return
        
        user_id = str(user.id)
        vps_list = vps_data.get(user_id, [])
        if not vps_list:
            await ctx.send(embed=create_error_embed("No VPS Found", f"{user.mention} doesn't have any RathamCloud VPS."))
            return
        
        # Create admin view for managing another user's VPS
        view = ManageView(str(ctx.author.id), vps_list, is_admin=True, owner_id=user_id)
        await ctx.send(embed=create_info_embed(f"Managing {user.name}'s RathamCloud VPS", f"Managing VPS for {user.mention}"), view=view)
    else:
        # User managing their own VPS
        user_id = str(ctx.author.id)
        vps_list = vps_data.get(user_id, [])
        if not vps_list:
            embed = create_embed("No VPS Found", "You don't have any RathamCloud VPS. Contact an admin to create one.", 0xff3366)
            add_field(embed, "Quick Actions", "• `!manage` - Manage VPS\n• Contact RathamCloud admin for VPS creation", False)
            await ctx.send(embed=embed)
            return
        view = ManageView(user_id, vps_list)
        embed = await view.get_initial_embed()
        await ctx.send(embed=embed, view=view)

@bot.command(name='list-all')
@is_admin()
async def list_all_vps(ctx):
    """List all RathamCloud VPS and user information (Admin only)"""
    total_vps = 0
    total_users = len(vps_data)
    running_vps = 0
    stopped_vps = 0
    suspended_vps = 0
    
    vps_info = []
    user_summary = []
    
    for user_id, vps_list in vps_data.items():
        try:
            user = await bot.fetch_user(int(user_id))
            user_vps_count = len(vps_list)
            user_running = sum(1 for vps in vps_list if vps.get('status') == 'running' and not vps.get('suspended', False))
            user_stopped = sum(1 for vps in vps_list if vps.get('status') == 'stopped')
            user_suspended = sum(1 for vps in vps_list if vps.get('suspended', True))
            
            total_vps += user_vps_count
            running_vps += user_running
            stopped_vps += user_stopped
            suspended_vps += user_suspended
            
            # User summary
            user_summary.append(f"**{user.name}** ({user.mention}) - {user_vps_count} RathamCloud VPS ({user_running} running, {user_suspended} suspended)")
            
            # Individual VPS details
            for i, vps in enumerate(vps_list):
                status_emoji = "🟢" if vps.get('status') == 'running' and not vps.get('suspended', False) else "🟡" if vps.get('suspended', False) else "🔴"
                status_text = vps.get('status', 'unknown').upper()
                if vps.get('suspended', False):
                    status_text += " (SUSPENDED)"
                vps_info.append(f"{status_emoji} **{user.name}** - VPS {i+1}: `{vps['container_name']}` - {vps.get('config', 'Custom')} - {status_text}")
                
        except discord.NotFound:
            vps_info.append(f"❓ Unknown User ({user_id}) - {len(vps_list)} RathamCloud VPS")
    
    # Create multiple embeds if needed to avoid character limit
    embeds = []
    
    # First embed with overview
    embed = create_embed("All RathamCloud VPS Information", "Complete overview of all RathamCloud VPS deployments and user statistics", 0x1a1a1a)
    add_field(embed, "System Overview", f"**Total Users:** {total_users}\n**Total VPS:** {total_vps}\n**Running:** {running_vps}\n**Stopped:** {stopped_vps}\n**Suspended:** {suspended_vps}", False)
    embeds.append(embed)
    
    # User summary embed
    if user_summary:
        embed = create_embed("RathamCloud User Summary", f"Summary of all users and their RathamCloud VPS", 0x1a1a1a)
        # Split user summary into chunks to avoid character limit
        for i in range(0, len(user_summary), 10):
            chunk = user_summary[i:i+10]
            summary_text = "\n".join(chunk)
            if i == 0:
                add_field(embed, "Users", summary_text, False)
            else:
                add_field(embed, f"Users (continued {i+1}-{min(i+10, len(user_summary))})", summary_text, False)
        embeds.append(embed)
    
    # VPS details embeds
    if vps_info:
        # Split VPS info into chunks to avoid character limit
        for i in range(0, len(vps_info), 15):
            chunk = vps_info[i:i+15]
            embed = create_embed(f"RathamCloud VPS Details ({i+1}-{min(i+15, len(vps_info))})", "List of all RathamCloud VPS deployments", 0x1a1a1a)
            add_field(embed, "VPS List", "\n".join(chunk), False)
            embeds.append(embed)
    
    # Send all embeds
    for embed in embeds:
        await ctx.send(embed=embed)

@bot.command(name='manage-shared')
async def manage_shared_vps(ctx, owner: discord.Member, vps_number: int):
    """Manage a shared RathamCloud VPS"""
    owner_id = str(owner.id)
    user_id = str(ctx.author.id)
    if owner_id not in vps_data or vps_number < 1 or vps_number > len(vps_data[owner_id]):
        await ctx.send(embed=create_error_embed("Invalid VPS", "Invalid VPS number or owner doesn't have a RathamCloud VPS."))
        return
    vps = vps_data[owner_id][vps_number - 1]
    if user_id not in vps.get("shared_with", []):
        await ctx.send(embed=create_error_embed("Access Denied", "You do not have access to this RathamCloud VPS."))
        return
    view = ManageView(user_id, [vps], is_shared=True, owner_id=owner_id)
    embed = await view.get_initial_embed()
    await ctx.send(embed=embed, view=view)

@bot.command(name='share-user')
async def share_user(ctx, shared_user: discord.Member, vps_number: int):
    """Share RathamCloud VPS access with another user"""
    user_id = str(ctx.author.id)
    shared_user_id = str(shared_user.id)
    if user_id not in vps_data or vps_number < 1 or vps_number > len(vps_data[user_id]):
        await ctx.send(embed=create_error_embed("Invalid VPS", "Invalid VPS number or you don't have a RathamCloud VPS."))
        return
    vps = vps_data[user_id][vps_number - 1]

    if "shared_with" not in vps:
        vps["shared_with"] = []

    if shared_user_id in vps["shared_with"]:
        await ctx.send(embed=create_error_embed("Already Shared", f"{shared_user.mention} already has access to this RathamCloud VPS!"))
        return
    vps["shared_with"].append(shared_user_id)
    save_data()
    await ctx.send(embed=create_success_embed("VPS Shared", f"RathamCloud VPS #{vps_number} shared with {shared_user.mention}!"))
    try:
        await shared_user.send(embed=create_embed("RathamCloud VPS Access Granted", f"You have access to VPS #{vps_number} from {ctx.author.mention}. Use `!manage-shared {ctx.author.mention} {vps_number}`", 0x00ff88))
    except discord.Forbidden:
        await ctx.send(embed=create_info_embed("Notification Failed", f"Could not DM {shared_user.mention}"))

@bot.command(name='share-ruser')
async def revoke_share(ctx, shared_user: discord.Member, vps_number: int):
    """Revoke shared RathamCloud VPS access"""
    user_id = str(ctx.author.id)
    shared_user_id = str(shared_user.id)
    if user_id not in vps_data or vps_number < 1 or vps_number > len(vps_data[user_id]):
        await ctx.send(embed=create_error_embed("Invalid VPS", "Invalid VPS number or you don't have a RathamCloud VPS."))
        return
    vps = vps_data[user_id][vps_number - 1]

    if "shared_with" not in vps:
        vps["shared_with"] = []

    if shared_user_id not in vps["shared_with"]:
        await ctx.send(embed=create_error_embed("Not Shared", f"{shared_user.mention} doesn't have access to this RathamCloud VPS!"))
        return
    vps["shared_with"].remove(shared_user_id)
    save_data()
    await ctx.send(embed=create_success_embed("Access Revoked", f"Access to RathamCloud VPS #{vps_number} revoked from {shared_user.mention}!"))
    try:
        await shared_user.send(embed=create_embed("RathamCloud VPS Access Revoked", f"Your access to VPS #{vps_number} by {ctx.author.mention} has been revoked.", 0xff3366))
    except discord.Forbidden:
        await ctx.send(embed=create_info_embed("Notification Failed", f"Could not DM {shared_user.mention}"))

@bot.hybrid_command(name='delete-vps')
@is_admin()
@commands.guild_only()
async def delete_vps(ctx, user: discord.Member, vps_number: int, *, reason: str = "No reason"):
    """Delete a user's RathamCloud VPS (Admin only)"""
    user_id = str(user.id)
    if user_id not in vps_data or vps_number < 1 or vps_number > len(vps_data[user_id]):
        await ctx.send(embed=create_error_embed("Invalid VPS", "Invalid VPS number or user doesn't have a RathamCloud VPS."))
        return
    vps = vps_data[user_id][vps_number - 1]
    container_name = vps["container_name"]

    await ctx.send(embed=create_info_embed("Deleting RathamCloud VPS", f"Removing VPS #{vps_number}..."))

    try:
        # Force stop the container before deletion to ensure it's removed cleanly
        try:
            await execute_RTC(f"RTC stop {container_name} --force")
        except Exception:
            pass # Ignore errors if container is already stopped
        await execute_RTC(f"RTC delete {container_name} --force")
        del vps_data[user_id][vps_number - 1]
        if not vps_data[user_id]:
            del vps_data[user_id]
            # Remove VPS role if user has no more VPS
            if ctx.guild:
                vps_role = await get_or_create_vps_role(ctx.guild)
                if vps_role and vps_role in user.roles:
                    try:
                        await user.remove_roles(vps_role, reason="No RathamCloud VPS ownership")
                    except discord.Forbidden:
                        logger.warning(f"Failed to remove RathamCloud VPS role from {user.name}")
        save_data()

        embed = create_success_embed("RathamCloud VPS Deleted Successfully")
        add_field(embed, "Owner", user.mention, True)
        add_field(embed, "VPS ID", f"#{vps_number}", True)
        add_field(embed, "Container", f"`{container_name}`", True)
        add_field(embed, "Reason", reason, False)
        await ctx.send(embed=embed)

    except Exception as e:
        await ctx.send(embed=create_error_embed("Deletion Failed", f"Error: {str(e)}"))

@bot.command(name='add-resources')
@is_admin()
async def add_resources(ctx, vps_id: str, ram: int = None, cpu: int = None, disk: int = None):
    """Add resources to a RathamCloud VPS (Admin only)"""
    if ram is None and cpu is None and disk is None:
        await ctx.send(embed=create_error_embed("Missing Parameters", "Please specify at least one resource to add (ram, cpu, or disk)"))
        return
    
    # Find the VPS in our database
    found_vps = None
    user_id = None
    vps_index = None
    
    for uid, vps_list in vps_data.items():
        for i, vps in enumerate(vps_list):
            if vps['container_name'] == vps_id:
                found_vps = vps
                user_id = uid
                vps_index = i
                break
        if found_vps:
            break
    
    if not found_vps:
        await ctx.send(embed=create_error_embed("VPS Not Found", f"No RathamCloud VPS found with ID: `{vps_id}`"))
        return
    
    was_running = found_vps.get('status') == 'running' and not found_vps.get('suspended', False)
    if was_running:
        await ctx.send(embed=create_info_embed("Stopping VPS", f"Stopping RathamCloud VPS `{vps_id}` to apply resource changes..."))
        try:
            await execute_RTC(f"RTC stop {vps_id}")
            found_vps['status'] = 'stopped'
            save_data()
        except Exception as e:
            await ctx.send(embed=create_error_embed("Stop Failed", f"Error stopping VPS: {str(e)}"))
            return
    
    changes = []
    
    try:
        current_ram_gb = int(found_vps['ram'].replace('GB', ''))
        current_cpu = int(found_vps['cpu'])
        current_disk_gb = int(found_vps['storage'].replace('GB', ''))
        
        new_ram_gb = current_ram_gb
        new_cpu = current_cpu
        new_disk_gb = current_disk_gb
        
        # Add RAM if specified
        if ram is not None and ram > 0:
            new_ram_gb += ram
            ram_mb = new_ram_gb * 1024
            await execute_RTC(f"RTC config set {vps_id} limits.memory {ram_mb}MB")
            changes.append(f"RAM: +{ram}GB (New total: {new_ram_gb}GB)")
        
        # Add CPU if specified
        if cpu is not None and cpu > 0:
            new_cpu += cpu
            await execute_RTC(f"RTC config set {vps_id} limits.cpu {new_cpu}")
            changes.append(f"CPU: +{cpu} cores (New total: {new_cpu} cores)")
        
        # Add disk if specified
        if disk is not None and disk > 0:
            new_disk_gb += disk
            await execute_RTC(f"RTC config device set {vps_id} root size {new_disk_gb}GB")
            changes.append(f"Disk: +{disk}GB (New total: {new_disk_gb}GB)")
        
        # Update VPS data
        found_vps['ram'] = f"{new_ram_gb}GB"
        found_vps['cpu'] = str(new_cpu)
        found_vps['storage'] = f"{new_disk_gb}GB"
        found_vps['config'] = f"{new_ram_gb}GB RAM / {new_cpu} CPU / {new_disk_gb}GB Disk"
        
        # Save changes to database
        vps_data[user_id][vps_index] = found_vps
        save_data()
        
        # Start the VPS if it was running before
        if was_running:
            await execute_RTC(f"RTC start {vps_id}")
            found_vps['status'] = 'running'
            save_data()
        
        embed = create_success_embed("Resources Added", f"Successfully added resources to RathamCloud VPS `{vps_id}`")
        add_field(embed, "Changes Applied", "\n".join(changes), False)
        await ctx.send(embed=embed)
        
    except Exception as e:
        await ctx.send(embed=create_error_embed("Resource Addition Failed", f"Error: {str(e)}"))

@bot.command(name='admin-add')
@is_main_admin()
async def admin_add(ctx, user: discord.Member):
    """Add RathamCloud admin (Main admin only)"""
    user_id = str(user.id)
    if user_id == str(MAIN_ADMIN_ID):
        await ctx.send(embed=create_error_embed("Already Admin", "This user is already the main RathamCloud admin!"))
        return

    if user_id in admin_data.get("admins", []):
        await ctx.send(embed=create_error_embed("Already Admin", f"{user.mention} is already a RathamCloud admin!"))
        return

    if "admins" not in admin_data:
        admin_data["admins"] = []

    admin_data["admins"].append(user_id)
    save_data()
    await ctx.send(embed=create_success_embed("Admin Added", f"{user.mention} is now a RathamCloud admin!"))
    try:
        await user.send(embed=create_embed("🎉 RathamCloud Admin Role Granted", f"You are now a RathamCloud admin by {ctx.author.mention}", 0x00ff88))
    except discord.Forbidden:
        await ctx.send(embed=create_info_embed("Notification Failed", f"Could not DM {user.mention}"))

@bot.command(name='admin-remove')
@is_main_admin()
async def admin_remove(ctx, user: discord.Member):
    """Remove RathamCloud admin (Main admin only)"""
    user_id = str(user.id)
    if user_id == str(MAIN_ADMIN_ID):
        await ctx.send(embed=create_error_embed("Cannot Remove", "You cannot remove the main RathamCloud admin!"))
        return

    if user_id not in admin_data.get("admins", []):
        await ctx.send(embed=create_error_embed("Not Admin", f"{user.mention} is not a RathamCloud admin!"))
        return

    admin_data["admins"].remove(user_id)
    save_data()
    await ctx.send(embed=create_success_embed("Admin Removed", f"{user.mention} is no longer a RathamCloud admin!"))
    try:
        await user.send(embed=create_embed("⚠️ RathamCloud Admin Role Revoked", f"Your admin role was removed by {ctx.author.mention}", 0xff3366))
    except discord.Forbidden:
        await ctx.send(embed=create_info_embed("Notification Failed", f"Could not DM {user.mention}"))

@bot.command(name='admin-list')
@is_main_admin()
async def admin_list(ctx):
    """List all RathamCloud admins (Main admin only)"""
    admins = admin_data.get("admins", [])
    main_admin = await bot.fetch_user(MAIN_ADMIN_ID)

    embed = create_embed("👑 RathamCloud Admin Team", "Current RathamCloud administrators:", 0x1a1a1a)
    add_field(embed, "🔰 Main Admin", f"{main_admin.mention} (ID: {MAIN_ADMIN_ID})", False)

    if admins:
        admin_list = []
        for admin_id in admins:
            try:
                admin_user = await bot.fetch_user(int(admin_id))
                admin_list.append(f"• {admin_user.mention} (ID: {admin_id})")
            except:
                admin_list.append(f"• Unknown User (ID: {admin_id})")

        admin_text = "\n".join(admin_list)
        add_field(embed, "🛡️ Admins", admin_text, False)
    else:
        add_field(embed, "🛡️ Admins", "No additional RathamCloud admins", False)

    await ctx.send(embed=embed)

@bot.command(name='userinfo')
@is_admin()
async def user_info(ctx, user: discord.Member):
    """Get detailed information about a RathamCloud user (Admin only)"""
    user_id = str(user.id)

    # Get user's VPS
    vps_list = vps_data.get(user_id, [])

    embed = create_embed(f"RathamCloud User Information - {user.name}", f"Detailed information for {user.mention}", 0x1a1a1a)

    # User details
    add_field(embed, "👤 User Details", f"**Name:** {user.name}\n**ID:** {user.id}\n**Joined:** {user.joined_at.strftime('%Y-%m-%d %H:%M:%S')}", False)

    # VPS info
    if vps_list:
        vps_info = []
        total_ram = 0
        total_cpu = 0
        total_storage = 0
        running_count = 0
        suspended_count = 0

        for i, vps in enumerate(vps_list):
            status_emoji = "🟢" if vps.get('status') == 'running' and not vps.get('suspended', False) else "🟡" if vps.get('suspended', False) else "🔴"
            status_text = vps.get('status', 'unknown').upper()
            if vps.get('suspended', False):
                status_text += " (SUSPENDED)"
                suspended_count += 1
            else:
                running_count += 1 if vps.get('status') == 'running' else 0
            vps_info.append(f"{status_emoji} VPS {i+1}: `{vps['container_name']}` - {status_text}")

            # Calculate totals
            ram_gb = int(vps['ram'].replace('GB', ''))
            storage_gb = int(vps['storage'].replace('GB', ''))
            total_ram += ram_gb
            total_cpu += int(vps['cpu'])
            total_storage += storage_gb

        vps_summary = f"**Total VPS:** {len(vps_list)}\n**Running:** {running_count}\n**Suspended:** {suspended_count}\n**Total RAM:** {total_ram}GB\n**Total CPU:** {total_cpu} cores\n**Total Storage:** {total_storage}GB"
        add_field(embed, "🖥️ RathamCloud VPS Information", vps_summary, False)
        
        # Create additional embeds if VPS list is too long
        if len(vps_info) > 10:
            # First embed with first 10 VPS
            first_embed = embed
            add_field(first_embed, "📋 VPS List (1-10)", "\n".join(vps_info[:10]), False)
            await ctx.send(embed=first_embed)
            
            # Additional embeds for remaining VPS
            for i in range(10, len(vps_info), 10):
                chunk = vps_info[i:i+10]
                additional_embed = create_embed(f"RathamCloud VPS List ({i+1}-{min(i+10, len(vps_info))})", f"More VPS for {user.mention}", 0x1a1a1a)
                add_field(additional_embed, "📋 VPS List", "\n".join(chunk), False)
                await ctx.send(embed=additional_embed)
        else:
            add_field(embed, "📋 VPS List", "\n".join(vps_info), False)
            await ctx.send(embed=embed)
    else:
        add_field(embed, "🖥️ RathamCloud VPS Information", "**No VPS owned**", False)
        await ctx.send(embed=embed)

    # Check if user is admin
    is_admin_user = user_id == str(MAIN_ADMIN_ID) or user_id in admin_data.get("admins", [])
    add_field(embed, "🛡️ RathamCloud Admin Status", f"**{'Yes' if is_admin_user else 'No'}**", False)

@bot.command(name='serverstats')
@is_admin()
async def server_stats(ctx):
    """Show RathamCloud server statistics (Admin only)"""
    total_users = len(vps_data)
    total_vps = sum(len(vps_list) for vps_list in vps_data.values())

    # Calculate resources
    total_ram = 0
    total_cpu = 0
    total_storage = 0
    running_vps = 0
    suspended_vps = 0

    for vps_list in vps_data.values():
        for vps in vps_list:
            ram_gb = int(vps['ram'].replace('GB', ''))
            storage_gb = int(vps['storage'].replace('GB', ''))
            total_ram += ram_gb
            total_cpu += int(vps['cpu'])
            total_storage += storage_gb
            if vps.get('status') == 'running':
                if vps.get('suspended', False):
                    suspended_vps += 1
                else:
                    running_vps += 1

    embed = create_embed("📊 RathamCloud Server Statistics", "Current RathamCloud server overview", 0x1a1a1a)
    add_field(embed, "👥 Users", f"**Total Users:** {total_users}\n**Total Admins:** {len(admin_data.get('admins', [])) + 1}", False)
    add_field(embed, "🖥️ VPS", f"**Total VPS:** {total_vps}\n**Running:** {running_vps}\n**Suspended:** {suspended_vps}\n**Stopped:** {total_vps - running_vps - suspended_vps}", False)
    add_field(embed, "📈 Resources", f"**Total RAM:** {total_ram}GB\n**Total CPU:** {total_cpu} cores\n**Total Storage:** {total_storage}GB", False)

    await ctx.send(embed=embed)

@bot.command(name='vpsinfo')
@is_admin()
async def vps_info(ctx, container_name: str = None):
    """Get detailed RathamCloud VPS information (Admin only)"""
    if not container_name:
        # Show all VPS
        all_vps = []
        for user_id, vps_list in vps_data.items():
            try:
                user = await bot.fetch_user(int(user_id))
                for i, vps in enumerate(vps_list):
                    status_text = vps.get('status', 'unknown').upper()
                    if vps.get('suspended', False):
                        status_text += " (SUSPENDED)"
                    all_vps.append(f"**{user.name}** - RathamCloud VPS {i+1}: `{vps['container_name']}` - {status_text}")
            except:
                pass

        # Create multiple embeds if needed to avoid character limit
        for i in range(0, len(all_vps), 20):
            chunk = all_vps[i:i+20]
            embed = create_embed(f"🖥️ All RathamCloud VPS ({i+1}-{min(i+20, len(all_vps))})", f"List of all RathamCloud VPS deployments", 0x1a1a1a)
            add_field(embed, "VPS List", "\n".join(chunk), False)
            await ctx.send(embed=embed)
    else:
        # Show specific VPS info
        found_vps = None
        found_user = None

        for user_id, vps_list in vps_data.items():
            for vps in vps_list:
                if vps['container_name'] == container_name:
                    found_vps = vps
                    found_user = await bot.fetch_user(int(user_id))
                    break
            if found_vps:
                break

        if not found_vps:
            await ctx.send(embed=create_error_embed("VPS Not Found", f"No RathamCloud VPS found with container name: `{container_name}`"))
            return

        suspended_text = " (SUSPENDED)" if found_vps.get('suspended', False) else ""
        embed = create_embed(f"🖥️ RathamCloud VPS Information - {container_name}", f"Details for VPS owned by {found_user.mention}{suspended_text}", 0x1a1a1a)
        add_field(embed, "👤 Owner", f"**Name:** {found_user.name}\n**ID:** {found_user.id}", False)
        add_field(embed, "📊 Specifications", f"**RAM:** {found_vps['ram']}\n**CPU:** {found_vps['cpu']} Cores\n**Storage:** {found_vps['storage']}", False)
        add_field(embed, "📈 Status", f"**Current:** {found_vps.get('status', 'unknown').upper()}{suspended_text}\n**Suspended:** {found_vps.get('suspended', False)}\n**Created:** {found_vps.get('created_at', 'Unknown')}", False)

        if 'config' in found_vps:
            add_field(embed, "⚙️ Configuration", f"**Config:** {found_vps['config']}", False)

        if found_vps.get('shared_with'):
            shared_users = []
            for shared_id in found_vps['shared_with']:
                try:
                    shared_user = await bot.fetch_user(int(shared_id))
                    shared_users.append(f"• {shared_user.mention}")
                except:
                    shared_users.append(f"• Unknown User ({shared_id})")
            shared_text = "\n".join(shared_users)
            add_field(embed, "🔗 Shared With", shared_text, False)

        await ctx.send(embed=embed)

@bot.command(name='restart-vps')
@is_admin()
async def restart_vps(ctx, container_name: str):
    """Restart a RathamCloud VPS (Admin only)"""
    await ctx.send(embed=create_info_embed("Restarting VPS", f"Restarting RathamCloud VPS `{container_name}`..."))

    try:
        await execute_RTC(f"RTC restart {container_name}")

        # Update status in database
        for user_id, vps_list in vps_data.items():
            for vps in vps_list:
                if vps['container_name'] == container_name:
                    vps['status'] = 'running'
                    vps['suspended'] = False
                    save_data()
                    break

        await ctx.send(embed=create_success_embed("VPS Restarted", f"RathamCloud VPS `{container_name}` has been restarted successfully!"))

    except Exception as e:
        await ctx.send(embed=create_error_embed("Restart Failed", f"Error: {str(e)}"))

@bot.command(name='backup-vps')
@is_admin()
async def backup_vps(ctx, container_name: str):
    """Create a snapshot of a RathamCloud VPS (Admin only)"""
    snapshot_name = f"RathamCloud-{container_name}-backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    await ctx.send(embed=create_info_embed("Creating RathamCloud Backup", f"Creating snapshot of `{container_name}`..."))

    try:
        await execute_RTC(f"RTC snapshot {container_name} {snapshot_name}")
        await ctx.send(embed=create_success_embed("Backup Created", f"RathamCloud Snapshot `{snapshot_name}` created successfully!"))

    except Exception as e:
        await ctx.send(embed=create_error_embed("Backup Failed", f"Error: {str(e)}"))

@bot.command(name='restore-vps')
@is_admin()
async def restore_vps(ctx, container_name: str, snapshot_name: str):
    """Restore a RathamCloud VPS from snapshot (Admin only)"""
    await ctx.send(embed=create_info_embed("Restoring VPS", f"Restoring `{container_name}` from RathamCloud snapshot `{snapshot_name}`..."))

    try:
        await execute_RTC(f"RTC restore {container_name} {snapshot_name}")
        await ctx.send(embed=create_success_embed("VPS Restored", f"RathamCloud VPS `{container_name}` has been restored from snapshot!"))

    except Exception as e:
        await ctx.send(embed=create_error_embed("Restore Failed", f"Error: {str(e)}"))

@bot.command(name='list-snapshots')
@is_admin()
async def list_snapshots(ctx, container_name: str):
    """List all snapshots for a RathamCloud VPS (Admin only)"""
    try:
        # Improved parsing for RTC list --type snapshot
        proc = await asyncio.create_subprocess_exec(
            RTC_EXECUTABLE, "list", "--type", "snapshot", "--columns", "n",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise Exception(stderr.decode())

        snapshots = [line.strip() for line in stdout.decode().splitlines() if line.strip() and container_name in line]
        snapshots = [snap.split()[0] for snap in snapshots if snap]  # Extract names

        if snapshots:
            # Create multiple embeds if needed to avoid character limit
            for i in range(0, len(snapshots), 20):
                chunk = snapshots[i:i+20]
                embed = create_embed(f"📸 RathamCloud Snapshots for {container_name} ({i+1}-{min(i+20, len(snapshots))})", f"List of snapshots", 0x1a1a1a)
                add_field(embed, "Snapshots", "\n".join([f"• {snap}" for snap in chunk]), False)
                await ctx.send(embed=embed)
        else:
            await ctx.send(embed=create_info_embed("No Snapshots", f"No RathamCloud snapshots found for `{container_name}`"))

    except Exception as e:
        await ctx.send(embed=create_error_embed("Error", f"Error listing snapshots: {str(e)}"))

@bot.command(name='exec')
@is_admin()
async def execute_command(ctx, container_name: str, *, command: str):
    """Execute a command inside a RathamCloud VPS (Admin only)"""
    await ctx.send(embed=create_info_embed("Executing Command", f"Running command in RathamCloud VPS `{container_name}`..."))

    try:
        proc = await asyncio.create_subprocess_exec(
            RTC_EXECUTABLE, "exec", container_name, "--", "bash", "-c", command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()

        output = stdout.decode() if stdout else "No output"
        error = stderr.decode() if stderr else ""

        embed = create_embed(f"Command Output - {container_name}", f"Command: `{command}`", 0x1a1a1a)

        if output.strip():
            # Split output if too long
            if len(output) > 1000:
                output = output[:1000] + "\n... (truncated)"
            add_field(embed, "📤 Output", f"```\n{output}\n```", False)

        if error.strip():
            if len(error) > 1000:
                error = error[:1000] + "\n... (truncated)"
            add_field(embed, "⚠️ Error", f"```\n{error}\n```", False)

        add_field(embed, "🔄 Exit Code", f"**{proc.returncode}**", False)

        await ctx.send(embed=embed)

    except Exception as e:
        await ctx.send(embed=create_error_embed("Execution Failed", f"Error: {str(e)}"))

@bot.command(name='stop-vps-all')
@is_admin()
async def stop_all_vps(ctx):
    """Stop all RathamCloud VPS using RTC stop --all --force (Admin only)"""
    await ctx.send(embed=create_warning_embed("Stopping All RathamCloud VPS", "⚠️ **WARNING:** This will stop ALL running VPS on the RathamCloud server.\n\nThis action cannot be undone. Continue?"))

    class ConfirmView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=60)

        @discord.ui.button(label="Stop All VPS", style=discord.ButtonStyle.danger)
        async def confirm(self, interaction: discord.Interaction, item: discord.ui.Button):
            await interaction.response.defer()

            try:
                # Execute the RTC stop --all --force command
                proc = await asyncio.create_subprocess_exec(
                    RTC_EXECUTABLE, "stop", "--all", "--force",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await proc.communicate()

                if proc.returncode == 0:
                    # Update all VPS status in database to stopped
                    stopped_count = 0
                    for user_id, vps_list in vps_data.items():
                        for vps in vps_list:
                            if vps.get('status') == 'running':
                                vps['status'] = 'stopped'
                                vps['suspended'] = False
                                stopped_count += 1

                    save_data()

                    embed = create_success_embed("All RathamCloud VPS Stopped", f"Successfully stopped {stopped_count} VPS using `RTC stop --all --force`")
                    output_text = stdout.decode() if stdout else 'No output'
                    add_field(embed, "Command Output", f"```\n{output_text}\n```", False)
                    await interaction.followup.send(embed=embed)
                else:
                    error_msg = stderr.decode() if stderr else "Unknown error"
                    embed = create_error_embed("Stop Failed", f"Failed to stop RathamCloud VPS: {error_msg}")
                    await interaction.followup.send(embed=embed)

            except Exception as e:
                embed = create_error_embed("Error", f"Error stopping VPS: {str(e)}")
                await interaction.followup.send(embed=embed)

        @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
        async def cancel(self, interaction: discord.Interaction, item: discord.ui.Button):
            await interaction.response.edit_message(embed=create_info_embed("Operation Cancelled", "The stop all RathamCloud VPS operation has been cancelled."))

    await ctx.send(view=ConfirmView())

@bot.command(name='cpu-monitor')
@is_admin()
async def cpu_monitor_control(ctx, action: str = "status"):
    """Control RathamCloud CPU monitoring system (Admin only)"""
    global cpu_monitor_active
    
    if action.lower() == "status":
        status = "Active" if cpu_monitor_active else "Inactive"
        embed = create_embed("RathamCloud CPU Monitor Status", f"RathamCloud CPU monitoring is currently **{status}**", 0x00ccff if cpu_monitor_active else 0xffaa00)
        add_field(embed, "Threshold", f"{CPU_THRESHOLD}% CPU usage", True)
        add_field(embed, "Check Interval", f"60 seconds (host)", True)
        await ctx.send(embed=embed)
    elif action.lower() == "enable":
        cpu_monitor_active = True
        await ctx.send(embed=create_success_embed("CPU Monitor Enabled", "RathamCloud CPU monitoring has been enabled."))
    elif action.lower() == "disable":
        cpu_monitor_active = False
        await ctx.send(embed=create_warning_embed("CPU Monitor Disabled", "RathamCloud CPU monitoring has been disabled."))
    else:
        await ctx.send(embed=create_error_embed("Invalid Action", "Use: `!cpu-monitor <status|enable|disable>`"))

@bot.command(name='resize-vps')
@is_admin()
async def resize_vps(ctx, container_name: str, ram: int = None, cpu: int = None, disk: int = None):
    """Resize RathamCloud VPS resources (Admin only)"""
    if ram is None and cpu is None and disk is None:
        await ctx.send(embed=create_error_embed("Missing Parameters", "Please specify at least one resource to resize (ram, cpu, or disk)"))
        return
    
    # Find the VPS in our database
    found_vps = None
    user_id = None
    vps_index = None
    
    for uid, vps_list in vps_data.items():
        for i, vps in enumerate(vps_list):
            if vps['container_name'] == container_name:
                found_vps = vps
                user_id = uid
                vps_index = i
                break
        if found_vps:
            break
    
    if not found_vps:
        await ctx.send(embed=create_error_embed("VPS Not Found", f"No RathamCloud VPS found with container name: `{container_name}`"))
        return
    
    was_running = found_vps.get('status') == 'running' and not found_vps.get('suspended', False)
    if was_running:
        await ctx.send(embed=create_info_embed("Stopping VPS", f"Stopping RathamCloud VPS `{container_name}` to apply resource changes..."))
        try:
            await execute_RTC(f"RTC stop {container_name}")
            found_vps['status'] = 'stopped'
            save_data()
        except Exception as e:
            await ctx.send(embed=create_error_embed("Stop Failed", f"Error stopping VPS: {str(e)}"))
            return
    
    changes = []
    
    try:
        new_ram = int(found_vps['ram'].replace('GB', ''))
        new_cpu = int(found_vps['cpu'])
        new_disk = int(found_vps['storage'].replace('GB', ''))
        
        # Resize RAM if specified
        if ram is not None and ram > 0:
            new_ram = ram
            ram_mb = ram * 1024
            await execute_RTC(f"RTC config set {container_name} limits.memory {ram_mb}MB")
            changes.append(f"RAM: {ram}GB")
        
        # Resize CPU if specified
        if cpu is not None and cpu > 0:
            new_cpu = cpu
            await execute_RTC(f"RTC config set {container_name} limits.cpu {cpu}")
            changes.append(f"CPU: {cpu} cores")
        
        # Resize disk if specified
        if disk is not None and disk > 0:
            new_disk = disk
            await execute_RTC(f"RTC config device set {container_name} root size {disk}GB")
            changes.append(f"Disk: {disk}GB")
        
        # Update VPS data
        found_vps['ram'] = f"{new_ram}GB"
        found_vps['cpu'] = str(new_cpu)
        found_vps['storage'] = f"{new_disk}GB"
        found_vps['config'] = f"{new_ram}GB RAM / {new_cpu} CPU / {new_disk}GB Disk"
        
        # Save changes to database
        vps_data[user_id][vps_index] = found_vps
        save_data()
        
        # Start the VPS if it was running before
        if was_running:
            await execute_RTC(f"RTC start {container_name}")
            found_vps['status'] = 'running'
            save_data()
        
        embed = create_success_embed("VPS Resized", f"Successfully resized resources for RathamCloud VPS `{container_name}`")
        add_field(embed, "Changes Applied", "\n".join(changes), False)
        await ctx.send(embed=embed)
        
    except Exception as e:
        await ctx.send(embed=create_error_embed("Resize Failed", f"Error: {str(e)}"))

@bot.command(name='clone-vps')
@is_admin()
async def clone_vps(ctx, container_name: str, new_name: str = None):
    """Clone a RathamCloud VPS (Admin only)"""
    if not new_name:
        # Generate a new name if not provided
        timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        new_name = f"RathamCloud-{container_name}-clone-{timestamp}"
    
    await ctx.send(embed=create_info_embed("Cloning VPS", f"Cloning RathamCloud VPS `{container_name}` to `{new_name}`..."))
    
    try:
        # Find the original VPS in our database
        found_vps = None
        user_id = None
        
        for uid, vps_list in vps_data.items():
            for vps in vps_list:
                if vps['container_name'] == container_name:
                    found_vps = vps
                    user_id = uid
                    break
            if found_vps:
                break
        
        if not found_vps:
            await ctx.send(embed=create_error_embed("VPS Not Found", f"No RathamCloud VPS found with container name: `{container_name}`"))
            return
        
        # Clone the container
        await execute_RTC(f"RTC copy {container_name} {new_name}")
        
        # Start the new container
        await execute_RTC(f"RTC start {new_name}")
        
        # Create a new VPS entry in the database
        if user_id not in vps_data:
            vps_data[user_id] = []
        
        new_vps = found_vps.copy()
        new_vps['container_name'] = new_name
        new_vps['status'] = 'running'
        new_vps['suspended'] = False
        new_vps['suspension_history'] = []
        new_vps['created_at'] = datetime.now().isoformat()
        new_vps['shared_with'] = []
        
        vps_data[user_id].append(new_vps)
        save_data()
        
        embed = create_success_embed("VPS Cloned", f"Successfully cloned RathamCloud VPS `{container_name}` to `{new_name}`")
        add_field(embed, "New VPS Details", f"**RAM:** {new_vps['ram']}\n**CPU:** {new_vps['cpu']} Cores\n**Storage:** {new_vps['storage']}", False)
        await ctx.send(embed=embed)
        
    except Exception as e:
        await ctx.send(embed=create_error_embed("Clone Failed", f"Error: {str(e)}"))

@bot.command(name='migrate-vps')
@is_admin()
async def migrate_vps(ctx, container_name: str, target_pool: str):
    """Migrate a RathamCloud VPS to a different storage pool (Admin only)"""
    await ctx.send(embed=create_info_embed("Migrating VPS", f"Migrating RathamCloud VPS `{container_name}` to storage pool `{target_pool}`..."))
    
    try:
        # Stop the container first
        await execute_RTC(f"RTC stop {container_name}")
        
        # Create a temporary name for migration
        temp_name = f"RathamCloud-{container_name}-temp-{int(time.time())}"
        
        # Copy to new pool with temp name
        await execute_RTC(f"RTC copy {container_name} {temp_name} --storage {target_pool}")
        
        # Delete the old container
        await execute_RTC(f"RTC delete {container_name} --force")
        
        # Rename temp to original name
        await execute_RTC(f"RTC rename {temp_name} {container_name}")
        
        # Start the container again
        await execute_RTC(f"RTC start {container_name}")
        
        # Update status in database
        for user_id, vps_list in vps_data.items():
            for vps in vps_list:
                if vps['container_name'] == container_name:
                    vps['status'] = 'running'
                    vps['suspended'] = False
                    save_data()
                    break
        
        await ctx.send(embed=create_success_embed("VPS Migrated", f"Successfully migrated RathamCloud VPS `{container_name}` to storage pool `{target_pool}`"))
        
    except Exception as e:
        await ctx.send(embed=create_error_embed("Migration Failed", f"Error: {str(e)}"))

@bot.command(name='vps-stats')
@is_admin()
async def vps_stats(ctx, container_name: str):
    """Show detailed resource usage statistics for a RathamCloud VPS (Admin only)"""
    await ctx.send(embed=create_info_embed("Gathering Statistics", f"Collecting statistics for RathamCloud VPS `{container_name}`..."))
    
    try:
        status = await get_container_status(container_name)
        cpu_usage = await get_container_cpu(container_name)
        memory_usage = await get_container_memory(container_name)
        disk_usage = await get_container_disk(container_name)
        network_usage = "N/A"  # Simplified for now
        
        # Create embed with statistics
        embed = create_embed(f"📊 RathamCloud VPS Statistics - {container_name}", f"Resource usage statistics", 0x1a1a1a)
        add_field(embed, "📈 Status", f"**{status}**", False)
        add_field(embed, "💻 CPU Usage", f"**{cpu_usage}**", True)
        add_field(embed, "🧠 Memory Usage", f"**{memory_usage}**", True)
        add_field(embed, "💾 Disk Usage", f"**{disk_usage}**", True)
        add_field(embed, "🌐 Network Usage", f"**{network_usage}**", False)
        
        # Find the VPS in our database
        found_vps = None
        for vps_list in vps_data.values():
            for vps in vps_list:
                if vps['container_name'] == container_name:
                    found_vps = vps
                    break
            if found_vps:
                break
        
        if found_vps:
            suspended_text = " (SUSPENDED)" if found_vps.get('suspended', False) else ""
            add_field(embed, "📋 Allocated Resources", 
                           f"**RAM:** {found_vps['ram']}\n**CPU:** {found_vps['cpu']} Cores\n**Storage:** {found_vps['storage']}\n**Status:** {found_vps.get('status', 'unknown').upper()}{suspended_text}", 
                           False)
        
        await ctx.send(embed=embed)
        
    except Exception as e:
        await ctx.send(embed=create_error_embed("Statistics Failed", f"Error: {str(e)}"))

@bot.command(name='vps-network')
@is_admin()
async def vps_network(ctx, container_name: str, action: str, value: str = None):
    """Manage RathamCloud VPS network settings (Admin only)"""
    if action.lower() not in ["list", "add", "remove", "limit"]:
        await ctx.send(embed=create_error_embed("Invalid Action", "Use: `!vps-network <container> <list|add|remove|limit> [value]`"))
        return
    
    try:
        if action.lower() == "list":
            # List network interfaces
            proc = await asyncio.create_subprocess_exec(
                RTC_EXECUTABLE, "exec", container_name, "--", "ip", "addr",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            
            if proc.returncode == 0:
                output = stdout.decode()
                # Split output if too long
                if len(output) > 1000:
                    output = output[:1000] + "\n... (truncated)"
                
                embed = create_embed(f"🌐 RathamCloud Network Interfaces - {container_name}", "Network configuration", 0x1a1a1a)
                add_field(embed, "Interfaces", f"```\n{output}\n```", False)
                await ctx.send(embed=embed)
            else:
                await ctx.send(embed=create_error_embed("Error", f"Failed to list network interfaces: {stderr.decode()}"))
        
        elif action.lower() == "limit" and value:
            # Set network limit
            await execute_RTC(f"RTC config device set {container_name} eth0 limits.egress {value}")
            await execute_RTC(f"RTC config device set {container_name} eth0 limits.ingress {value}")
            await ctx.send(embed=create_success_embed("Network Limited", f"Set RathamCloud network limit to {value} for `{container_name}`"))
        
        elif action.lower() in ["add", "remove"]:
            await ctx.send(embed=create_info_embed("Not Implemented", f"RathamCloud Network {action} is not yet implemented. Use list or limit for now."))
        
        else:
            await ctx.send(embed=create_error_embed("Invalid Parameters", "Please provide valid parameters for the action"))
    
    except Exception as e:
        await ctx.send(embed=create_error_embed("Network Management Failed", f"Error: {str(e)}"))

@bot.command(name='vps-processes')
@is_admin()
async def vps_processes(ctx, container_name: str):
    """Show running processes in a RathamCloud VPS (Admin only)"""
    await ctx.send(embed=create_info_embed("Gathering Processes", f"Listing processes in RathamCloud VPS `{container_name}`..."))
    
    try:
        proc = await asyncio.create_subprocess_exec(
            RTC_EXECUTABLE, "exec", container_name, "--", "ps", "aux",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        
        if proc.returncode == 0:
            output = stdout.decode()
            # Split output if too long
            if len(output) > 1000:
                output = output[:1000] + "\n... (truncated)"
            
            embed = create_embed(f"⚙️ RathamCloud Processes - {container_name}", "Running processes", 0x1a1a1a)
            add_field(embed, "Process List", f"```\n{output}\n```", False)
            await ctx.send(embed=embed)
        else:
            await ctx.send(embed=create_error_embed("Error", f"Failed to list processes: {stderr.decode()}"))
    
    except Exception as e:
        await ctx.send(embed=create_error_embed("Process Listing Failed", f"Error: {str(e)}"))

@bot.command(name='vps-logs')
@is_admin()
async def vps_logs(ctx, container_name: str, lines: int = 50):
    """Show recent logs from a RathamCloud VPS (Admin only)"""
    await ctx.send(embed=create_info_embed("Gathering Logs", f"Fetching last {lines} lines from RathamCloud VPS `{container_name}`..."))
    
    try:
        proc = await asyncio.create_subprocess_exec(
            RTC_EXECUTABLE, "exec", container_name, "--", "journalctl", "-n", str(lines),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        
        if proc.returncode == 0:
            output = stdout.decode()
            # Split output if too long
            if len(output) > 1000:
                output = output[:1000] + "\n... (truncated)"
            
            embed = create_embed(f"📋 RathamCloud Logs - {container_name}", f"Last {lines} log lines", 0x1a1a1a)
            add_field(embed, "System Logs", f"```\n{output}\n```", False)
            await ctx.send(embed=embed)
        else:
            await ctx.send(embed=create_error_embed("Error", f"Failed to fetch logs: {stderr.decode()}"))
    
    except Exception as e:
        await ctx.send(embed=create_error_embed("Log Retrieval Failed", f"Error: {str(e)}"))

@bot.command(name='setup-node')
@is_admin()
async def setup_node(ctx, container_name: str, version: str = "20"):
    """Install Node.js inside a RathamCloud VPS (Admin only)"""
    await ctx.send(embed=create_info_embed("Installing Node.js", f"Setting up Node.js v{version}.x in `{container_name}`..."))
    
    # Script to add NodeSource repo and install nodejs
    setup_cmd = f"curl -fsSL https://deb.nodesource.com/setup_{version}.x | sudo -E bash - && sudo apt-get install -y nodejs"
    
    try:
        proc = await asyncio.create_subprocess_exec(
            RTC_EXECUTABLE, "exec", container_name, "--", "bash", "-c", setup_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode == 0:
            version_proc = await execute_RTC(f"RTC exec {container_name} -- node -v")
            await ctx.send(embed=create_success_embed("Node.js Installed", f"Successfully installed Node.js in `{container_name}`\n**Version:** `{version_proc}`"))
        else:
            error_output = stderr.decode().strip() or stdout.decode().strip()
            await ctx.send(embed=create_error_embed("Installation Failed", f"```\n{error_output[:1000]}\n```"))
            
    except Exception as e:
        await ctx.send(embed=create_error_embed("Execution Error", str(e)))

@bot.command(name='ports')
async def ports_command(ctx, action: str = "list", arg1: int = None, arg2: int = None):
    """Manage port forwards (TCP/UDP) - !ports [add <vps_num> <port> | list | remove <id>]"""
    user_id = str(ctx.author.id)
    
    if action == "list":
        active = port_data["active_ports"].get(user_id, [])
        slots = port_data["users"].get(user_id, {}).get("slots", 0)
        
        embed = create_info_embed("🔌 Port Forwarding", f"Manage your port forwards. Available slots: **{len(active)}/{slots}**")
        if not active:
            add_field(embed, "Active Forwards", "No active port forwards.", False)
        else:
            text = []
            for p in active:
                text.append(f"ID: `{p['host_port']}` | VPS: `{p['container']}` | `{p['host_port']}` → `{p['internal_port']}`")
            add_field(embed, "Active Forwards", "\n".join(text), False)
        await ctx.send(embed=embed)

    elif action == "add":
        if arg1 is None or arg2 is None:
            return await ctx.send(embed=create_error_embed("Usage", "Usage: `!ports add <vps_num> <port>`"))
        
        vps_list = vps_data.get(user_id, [])
        if arg1 < 1 or arg1 > len(vps_list):
            return await ctx.send(embed=create_error_embed("Invalid VPS", "Invalid VPS number."))
        
        vps = vps_list[arg1-1]
        container_name = vps["container_name"]
        
        slots = port_data["users"].get(user_id, {}).get("slots", 0)
        active = port_data["active_ports"].get(user_id, [])
        if len(active) >= slots:
            return await ctx.send(embed=create_error_embed("No Slots", "You have no available port slots. Contact an admin."))
        
        host_port = get_next_available_port()
        if not host_port:
            return await ctx.send(embed=create_error_embed("System Error", "No available ports on host."))
        
        await ctx.send(embed=create_info_embed("Adding Port Forward", f"Forwarding host port `{host_port}` to `{container_name}:{arg2}`..."))
        
        try:
            await execute_RTC(f"RTC config device add {container_name} port-{host_port}-tcp proxy listen=tcp:0.0.0.0:{host_port} connect=tcp:127.0.0.1:{arg2}")
            await execute_RTC(f"RTC config device add {container_name} port-{host_port}-udp proxy listen=udp:0.0.0.0:{host_port} connect=udp:127.0.0.1:{arg2}")
            
            if user_id not in port_data["active_ports"]:
                port_data["active_ports"][user_id] = []
            
            port_data["active_ports"][user_id].append({
                "container": container_name,
                "internal_port": arg2,
                "host_port": host_port
            })
            save_data()
            await ctx.send(embed=create_success_embed("Port Forward Added", f"Successfully forwarded `{host_port}` (TCP/UDP) to `{container_name}:{arg2}`"))
        except Exception as e:
            await ctx.send(embed=create_error_embed("Failed", str(e)))

    elif action == "remove":
        if arg1 is None:
            return await ctx.send(embed=create_error_embed("Usage", "Usage: `!ports remove <id>`"))
        
        active = port_data["active_ports"].get(user_id, [])
        found = None
        for p in active:
            if p["host_port"] == arg1:
                found = p
                break
        
        if not found:
            return await ctx.send(embed=create_error_embed("Not Found", "Port forward ID not found in your list."))
        
        try:
            await execute_RTC(f"RTC config device remove {found['container']} port-{arg1}-tcp")
            await execute_RTC(f"RTC config device remove {found['container']} port-{arg1}-udp")
            active.remove(found)
            save_data()
            await ctx.send(embed=create_success_embed("Port Forward Removed", f"Successfully removed port forward `{arg1}`"))
        except Exception as e:
            await ctx.send(embed=create_error_embed("Failed", str(e)))

@bot.command(name='ports-add-user')
@is_admin()
async def ports_add_user(ctx, amount: int, user: discord.Member):
    """Allocate port slots to user (Admin only)"""
    user_id = str(user.id)
    if user_id not in port_data["users"]:
        port_data["users"][user_id] = {"slots": 0}
    
    port_data["users"][user_id]["slots"] += amount
    save_data()
    await ctx.send(embed=create_success_embed("Slots Allocated", f"Allocated {amount} port slots to {user.mention}. Total: {port_data['users'][user_id]['slots']}"))

@bot.command(name='snap-status')
@is_admin()
async def snap_status(ctx):
    """Check the status of snap packages on the host (Admin only)"""
    await ctx.send(embed=create_info_embed("Checking Snap Status", "Fetching list of installed snap packages on the host..."))
    
    try:
        proc = await asyncio.create_subprocess_exec(
            'snap', 'list',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode == 0:
            output = stdout.decode().strip()
            if not output:
                output = "No snap packages found."
            
            embed = create_embed("Host Snap Status", "List of installed snap packages on the host machine", 0x00ccff)
            add_field(embed, "Installed Snaps", f"```\n{output}\n```", False)
            await ctx.send(embed=embed)
        else:
            error_output = stderr.decode().strip() or "Snap command failed"
            await ctx.send(embed=create_error_embed("Snap Check Failed", f"```\n{error_output}\n```"))
            
    except Exception as e:
        await ctx.send(embed=create_error_embed("Execution Error", str(e)))

@bot.command(name='suspend-vps')
@is_admin()
async def suspend_vps(ctx, container_name: str, *, reason: str = "Admin action"):
    """Suspend a RathamCloud VPS (Admin only)"""
    found = False
    for uid, lst in vps_data.items():
        for vps in lst:
            if vps['container_name'] == container_name:
                if vps.get('status') != 'running':
                    await ctx.send(embed=create_error_embed("Cannot Suspend", "RathamCloud VPS must be running to suspend."))
                    return
                try:
                    await execute_RTC(f"RTC stop {container_name}")
                    vps['status'] = 'suspended'
                    vps['suspended'] = True
                    if 'suspension_history' not in vps:
                        vps['suspension_history'] = []
                    vps['suspension_history'].append({
                        'time': datetime.now().isoformat(),
                        'reason': reason,
                        'by': f"{ctx.author.name} ({ctx.author.id})"
                    })
                    save_data()
                except Exception as e:
                    await ctx.send(embed=create_error_embed("Suspend Failed", str(e)))
                    return
                # DM owner
                try:
                    owner = await bot.fetch_user(int(uid))
                    embed = create_warning_embed("🚨 RathamCloud VPS Suspended", f"Your VPS `{container_name}` has been suspended by an admin.\n\n**Reason:** {reason}\n\nContact a RathamCloud admin to unsuspend.")
                    await owner.send(embed=embed)
                except Exception as dm_e:
                    logger.error(f"Failed to DM owner {uid}: {dm_e}")
                await ctx.send(embed=create_success_embed("VPS Suspended", f"RathamCloud VPS `{container_name}` suspended. Reason: {reason}"))
                found = True
                break
        if found:
            break
    if not found:
        await ctx.send(embed=create_error_embed("Not Found", f"RathamCloud VPS `{container_name}` not found."))

@bot.command(name='unsuspend-vps')
@is_admin()
async def unsuspend_vps(ctx, container_name: str):
    """Unsuspend a RathamCloud VPS (Admin only)"""
    found = False
    for uid, lst in vps_data.items():
        for vps in lst:
            if vps['container_name'] == container_name:
                if not vps.get('suspended', False):
                    await ctx.send(embed=create_error_embed("Not Suspended", "RathamCloud VPS is not suspended."))
                    return
                try:
                    vps['suspended'] = False
                    vps['status'] = 'running'
                    await execute_RTC(f"RTC start {container_name}")
                    save_data()
                    await ctx.send(embed=create_success_embed("VPS Unsuspended", f"RathamCloud VPS `{container_name}` unsuspended and started."))
                    found = True
                except Exception as e:
                    await ctx.send(embed=create_error_embed("Start Failed", str(e)))
                break
        if found:
            break
    if not found:
        await ctx.send(embed=create_error_embed("Not Found", f"RathamCloud VPS `{container_name}` not found."))

@bot.command(name='suspension-logs')
@is_admin()
async def suspension_logs(ctx, container_name: str = None):
    """View RathamCloud suspension logs (Admin only)"""
    if container_name:
        # Specific VPS
        found = None
        for lst in vps_data.values():
            for vps in lst:
                if vps['container_name'] == container_name:
                    found = vps
                    break
            if found:
                break
        if not found:
            await ctx.send(embed=create_error_embed("Not Found", f"RathamCloud VPS `{container_name}` not found."))
            return
        history = found.get('suspension_history', [])
        if not history:
            await ctx.send(embed=create_info_embed("No Suspensions", f"No RathamCloud suspension history for `{container_name}`."))
            return
        embed = create_embed("RathamCloud Suspension History", f"For `{container_name}`")
        text = []
        for h in sorted(history, key=lambda x: x['time'], reverse=True)[:10]:  # Last 10
            t = datetime.fromisoformat(h['time']).strftime('%Y-%m-%d %H:%M:%S')
            text.append(f"**{t}** - {h['reason']} (by {h['by']})")
        add_field(embed, "History", "\n".join(text), False)
        if len(history) > 10:
            add_field(embed, "Note", "Showing last 10 entries.")
        await ctx.send(embed=embed)
    else:
        # All logs
        all_logs = []
        for uid, lst in vps_data.items():
            for vps in lst:
                h = vps.get('suspension_history', [])
                for event in sorted(h, key=lambda x: x['time'], reverse=True):
                    t = datetime.fromisoformat(event['time']).strftime('%Y-%m-%d %H:%M')
                    all_logs.append(f"**{t}** - VPS `{vps['container_name']}` (Owner: <@{uid}>) - {event['reason']} (by {event['by']})")
        if not all_logs:
            await ctx.send(embed=create_info_embed("No Suspensions", "No RathamCloud suspension events recorded."))
            return
        # Split into embeds
        for i in range(0, len(all_logs), 10):
            chunk = all_logs[i:i+10]
            embed = create_embed(f"RathamCloud Suspension Logs ({i+1}-{min(i+10, len(all_logs))})", f"Global suspension events (newest first)")
            add_field(embed, "Events", "\n".join(chunk), False)
            await ctx.send(embed=embed)

class HelpView(discord.ui.View):
    def __init__(self, author, is_admin, is_main_admin):
        super().__init__(timeout=180)
        self.author = author
        
        options = [
            discord.SelectOption(label="User Commands", description="Basic commands for all users", emoji="👤", value="user")
        ]
        if is_admin:
            options.append(discord.SelectOption(label="Admin Commands", description="VPS management for staff", emoji="🛡️", value="admin"))
        if is_main_admin:
            options.append(discord.SelectOption(label="Main Admin Commands", description="Bot ownership commands", emoji="👑", value="main"))
            
        self.select = discord.ui.Select(placeholder="Select a command category...", options=options)
        self.select.callback = self.select_callback
        self.add_item(self.select)

    async def select_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.author.id:
            return await interaction.response.send_message("This menu is only for the person who used the command.", ephemeral=True)
            
        selection = self.select.values[0]
        if selection == "user":
            embed = self.get_user_embed()
        elif selection == "admin":
            embed = self.get_admin_embed()
        else:
            embed = self.get_main_admin_embed()
            
        await interaction.response.edit_message(embed=embed, view=self)

    def get_user_embed(self):
        embed = create_embed("Command Help", "Select a category from the menu to see available commands.", 0x1a1a1a)
        user_cmds = [
            ("!ping", "Check bot latency"),
            ("!uptime", "Show host uptime"),
            ("!myvps", "List your RathamCloud VPS"),
            ("!manage", "Manage your VPS (Start/Stop/SSH)"),
            ("!share-user @user <num>", "Share VPS access"),
            ("!share-ruser @user <num>", "Revoke VPS access"),
            ("!manage-shared @owner <num>", "Manage shared VPS"),
            ("!ports [add|list|remove]", "Manage port forwards")
        ]
        cmd_text = "\n".join([f"**{cmd}** - {desc}" for cmd, desc in user_cmds])
        add_field(embed, "👤 User Commands", cmd_text, False)
        return embed

    def get_admin_embed(self):
        embed = create_embed("Admin Help", "Advanced VPS management commands.", 0x1a1a1a)
        
        mgmt_cmds = [
            ("!create <ram> <cpu> <disk> @user", "Deploy new VPS"),
            ("!delete-vps @user <num>", "Remove a user's VPS"),
            ("!suspend-vps <id>", "Suspend a VPS"),
            ("!unsuspend-vps <id>", "Unsuspend a VPS"),
            ("!resize-vps <id> [specs]", "Change VPS resources"),
            ("!clone-vps <id>", "Clone an existing VPS")
        ]
        
        sys_cmds = [
            ("!RTC-list", "List all containers"),
            ("!serverstats", "Global resource overview"),
            ("!vpsinfo [id]", "Detailed VPS data"),
            ("!exec <id> <cmd>", "Run command in VPS"),
            ("!stop-vps-all", "Emergency stop all VPS"),
            ("!snap-status", "Check host snap status"),
            ("!node", "Node setup instructions")
        ]
        
        add_field(embed, "🛡️ Management", "\n".join([f"**{c}** - {d}" for c, d in mgmt_cmds]), False)
        add_field(embed, "⚙️ System Tools", "\n".join([f"**{c}** - {d}" for c, d in sys_cmds]), False)
        return embed

    def get_main_admin_embed(self):
        embed = create_embed("Main Admin Help", "Bot configuration and ownership.", 0x1a1a1a)
        main_cmds = [
            ("!admin-add @user", "Promote to admin"),
            ("!admin-remove @user", "Demote from admin"),
            ("!admin-list", "View admin team"),
            ("!sync [guild_id]", "Sync slash commands")
        ]
        cmd_text = "\n".join([f"**{cmd}** - {desc}" for cmd, desc in main_cmds])
        add_field(embed, "👑 Ownership Commands", cmd_text, False)
        return embed

@bot.command(name='help')
async def show_help(ctx):
    """Show RathamCloud help information with a menu"""
    user_id = str(ctx.author.id)
    is_user_admin = user_id == str(MAIN_ADMIN_ID) or user_id in admin_data.get("admins", [])
    is_user_main_admin = user_id == str(MAIN_ADMIN_ID)

    view = HelpView(ctx.author, is_user_admin, is_user_main_admin)
    embed = view.get_user_embed()
    await ctx.send(embed=embed, view=view)

# Command aliases for typos
@bot.command(name='mangage')
async def manage_typo(ctx):
    """Handle typo in manage command"""
    await ctx.send(embed=create_info_embed("Command Correction", "Did you mean `!manage`? Use the correct RathamCloud command."))

@bot.command(name='stats')
async def stats_alias(ctx):
    """Alias for serverstats command"""
    if str(ctx.author.id) == str(MAIN_ADMIN_ID) or str(ctx.author.id) in admin_data.get("admins", []):
        await server_stats(ctx)
    else:
        await ctx.send(embed=create_error_embed("Access Denied", "This RathamCloud command requires admin privileges."))

@bot.command(name='info')
async def info_alias(ctx):
    """Alias for userinfo command"""
    if str(ctx.author.id) == str(MAIN_ADMIN_ID) or str(ctx.author.id) in admin_data.get("admins", []):
        await ctx.send(embed=create_error_embed("Usage", "Please specify a user: `!info @user`"))
    else:
        await ctx.send(embed=create_error_embed("Access Denied", "This RathamCloud command requires admin privileges."))

# Run the bot with your token
if __name__ == "__main__":
    if DISCORD_TOKEN:
        bot.run(DISCORD_TOKEN)
    else:
        logger.error("No Discord token found in DISCORD_TOKEN environment variable.")
