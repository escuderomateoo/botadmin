import asyncio
import subprocess
import json
import os
import psutil
import shutil
import time
from dotenv import load_dotenv
from telegram import Update, constants
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# --- CONFIGURACIÓN ---
load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
ALLOWED_USERS = [int(x) for x in os.getenv("ALLOWED_USERS", "").split(",") if x]
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "60"))


# --- FUNCIONES DE SISTEMA ASÍNCRONAS ---
def run_cmd_sync(cmd: str) -> str:
    """Ejecuta un comando en bash y devuelve su salida (sincrónico)."""
    try:
        output = subprocess.check_output(
            cmd, shell=True, stderr=subprocess.STDOUT, text=True
        )
        return output.strip()
    except subprocess.CalledProcessError as e:
        return e.output.strip()


async def run_cmd(cmd: str) -> str:
    """Ejecuta run_cmd_sync en un hilo separado para no bloquear el loop."""
    return await asyncio.to_thread(run_cmd_sync, cmd)


async def get_pm2_status() -> list:
    """Obtiene la lista de procesos PM2 en formato JSON."""
    try:
        output = await run_cmd("pm2 jlist")
        return json.loads(output)
    except Exception as e:
        print(f"[ERROR] No se pudo obtener estado de PM2: {e}")
        return []


# --- DECORADOR DE SEGURIDAD ---
def restricted(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id not in ALLOWED_USERS:
            if update.message:
                await update.message.reply_text(
                    "🚫 No estás autorizado para usar este bot."
                )
            return
        return await func(update, context)

    return wrapper


# --- COMANDOS PRINCIPALES ---
@restricted
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muestra el estado de los procesos PM2."""
    data = await get_pm2_status()
    lines = ["📊 *PM2 STATUS:*"]

    if not data:
        lines.append("No hay procesos PM2 activos o PM2 no está disponible.")
    else:
        lines.append("```")
        lines.append(" ID | Nombre       | CPU  | MEMORIA | Estado")
        lines.append("----+--------------+------+----------+---------")

        for p in data:
            name = p["name"][:12].ljust(12)
            pm_id = str(p["pm_id"]).ljust(2)
            cpu = str(p["monit"].get("cpu", 0)).rjust(3) + "%"
            mem_mb = round(p["monit"].get("memory", 0) / (1024 * 1024), 1)
            status_text = p["pm2_env"]["status"]

            if status_text == "online":
                emoji = "🟢"
            elif status_text == "stopped":
                emoji = "🛑"
            elif status_text == "errored":
                emoji = "🔴"
            else:
                emoji = "🟡"

            lines.append(
                f" {pm_id} | {name} | {cpu} | {str(mem_mb).rjust(6)}M | {emoji} {status_text}"
            )
        lines.append("```")

    msg = "\n".join(lines)
    if len(msg) > 4000:
        msg = msg[:3900] + "\n... (salida truncada por límite de Telegram)"
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


@restricted
async def restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usá /restart <nombre_proceso>")
        return
    name = context.args[0]
    result = await run_cmd(f"pm2 restart {name}")
    await update.message.reply_text(
        f"🔁 *Reinicio de {name}:*\n```\n{result}\n```",
        parse_mode=ParseMode.MARKDOWN,
    )


@restricted
async def logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usá /logs <nombre_proceso> [lineas]")
        return
    name = context.args[0]
    lines = context.args[1] if len(context.args) > 1 else "30"
    result = await run_cmd(f"pm2 logs {name} --lines {lines} --nostream")

    if len(result) > 4000:
        result = result[:3900] + "\n... (logs truncados por límite de Telegram)"

    await update.message.reply_text(
        f"📜 *Logs de {name}:*\n```\n{result}\n```",
        parse_mode=ParseMode.MARKDOWN,
    )


@restricted
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🤖 *Comandos disponibles:*\n\n"
        "/status - Ver procesos PM2\n"
        "/restart <nombre> - Reiniciar proceso\n"
        "/logs <nombre> [lineas] - Ver logs\n"
        "/system - Info del sistema\n"
        "/about - Info del bot\n"
        "/help - Muestra esta ayuda"
        "/gitpull Pullea Automaticamente los cambios en el Bot BanksRate"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


# --- NUEVOS COMANDOS ---
@restricted
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 *Bienvenido al Bot de Administración PM2*\n\n"
        "Este bot te permite monitorear y controlar procesos en tu servidor.\n"
        "Usá /help para ver todos los comandos disponibles.\n\n"
        "⚙️ _Desarrollado para admins que aman el control._"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


@restricted
async def about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = [
        "🤖 *PM2 Admin Bot*",
        "",
        "• Versión: `1.1`",
        "• Lenguaje: `Python 3`",
        "• Framework: `python-telegram-bot`",
        "• Autor: DAMIAN, AGUSTIN, MATEO",
        "",
        "💡 Este bot se conecta con *PM2* para:",
        "  - Ver el estado de los procesos",
        "  - Reiniciar servicios",
        "  - Ver logs en tiempo real",
        "  - Monitorear cambios automáticamente",
        "",
        "🚀 _Administra tus procesos con estilo._",
    ]
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


@restricted
async def system(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muestra información general del sistema."""
    cpu = psutil.cpu_percent(interval=1)
    mem = psutil.virtual_memory()
    disk = shutil.disk_usage("/")
    uptime = time.time() - psutil.boot_time()

    lines = ["🖥 *System Info:*", "```"]
    lines.append(f"CPU:      {cpu}%")
    lines.append(f"RAM:      {mem.percent}% ({mem.used // (1024 ** 2)} MB usados)")
    lines.append(
        f"DISK:     {disk.used // (1024 ** 3)} / {disk.total // (1024 ** 3)} GB"
    )
    lines.append(f"UPTIME:   {int(uptime // 3600)}h {int((uptime % 3600) // 60)}m")
    lines.append("```")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


@restricted
async def git_pull_repo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    repo_path = "/root/proyectofinalsic/"

    if not os.path.isdir(repo_path):
        await update.message.reply_text(f"🚫 No existe la carpeta: {repo_path}")
        return

    await update.message.reply_text(f"⏳ Actualizando repo en `{repo_path}`...")

    # Ejecutar git pull en esa carpeta
    git_result = await run_cmd(f"cd {repo_path} && git pull")

    # Limitar mensaje de Telegram si es muy largo
    if len(git_result) > 4000:
        git_result = git_result[:3900] + "\n... (resultado truncado)"

    await update.message.reply_text(
        f"📦 Resultado de git pull en `{repo_path}`:\n```\n{git_result}\n```",
        parse_mode=ParseMode.MARKDOWN,
    )


# --- MONITOREO AUTOMÁTICO ---
async def monitor_pm2(application):
    """Chequea el estado de PM2 cada intervalo y avisa cambios."""
    if not ALLOWED_USERS:
        print("⚠️ [Monitor] No hay usuarios autorizados para enviar alertas.")
        return

    chat_id = ALLOWED_USERS[0]
    last_status = {p["name"]: p["pm2_env"]["status"] for p in await get_pm2_status()}

    try:
        while True:
            await asyncio.sleep(CHECK_INTERVAL)
            current_data = await get_pm2_status()
            current_status = {p["name"]: p["pm2_env"]["status"] for p in current_data}

            # Cambios
            for name, status in current_status.items():
                old_status = last_status.get(name)
                if old_status != status:
                    msg = (
                        f"⚠️ *Cambio detectado en {name}:*\n`{old_status}` → `{status}`"
                    )
                    await application.bot.send_message(
                        chat_id=chat_id, text=msg, parse_mode=ParseMode.MARKDOWN
                    )

            # Eliminados
            for name in set(last_status) - set(current_status):
                await application.bot.send_message(
                    chat_id=chat_id,
                    text=f"🛑 *Proceso eliminado:* `{name}`",
                    parse_mode=ParseMode.MARKDOWN,
                )

            # Nuevos
            for name in set(current_status) - set(last_status):
                await application.bot.send_message(
                    chat_id=chat_id,
                    text=f"🟢 *Nuevo proceso detectado:* `{name}`",
                    parse_mode=ParseMode.MARKDOWN,
                )

            last_status = current_status.copy()

    except asyncio.CancelledError:
        print("🧹 Monitor PM2 detenido correctamente.")


# --- CALLBACK AL INICIAR EL BOT ---
async def on_startup(application):
    """Se ejecuta cuando el bot inicia completamente."""
    await asyncio.sleep(1)  # Espera a que el bot esté listo
    asyncio.create_task(monitor_pm2(application))
    print("✅ Tarea de monitoreo PM2 iniciada.")


# --- MAIN ---
def main():
    app = ApplicationBuilder().token(TOKEN).post_init(on_startup).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("about", about))
    app.add_handler(CommandHandler("system", system))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("restart", restart))
    app.add_handler(CommandHandler("logs", logs))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("gitpull", git_pull_repo))

    print("✅ Bot admin corriendo. Esperando comandos...")
    try:
        app.run_polling(
            allowed_updates=list(constants.UpdateType),
            drop_pending_updates=True,
        )
    except KeyboardInterrupt:
        print("\n🧹 Bot detenido manualmente.")


if __name__ == "__main__":
    main()
