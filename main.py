import asyncio
import subprocess
import json
import os
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


async def get_pm2_status() -> dict:
    """Obtiene el estado PM2 ejecutando run_cmd de forma asíncrona."""
    try:
        output = await run_cmd("pm2 jlist")
        data = json.loads(output)
        return {p["name"]: p["pm2_env"]["status"] for p in data}
    except Exception:
        return {}


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


# --- COMANDOS DE ADMINISTRACIÓN ---
@restricted
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 1. Obtenemos la salida en formato JSON
    json_result = await run_cmd("pm2 list --json")

    try:
        data = json.loads(json_result)
    except json.JSONDecodeError:
        # Esto ocurre si pm2 list --json falla (ej. pm2 no está instalado o no hay procesos)
        await update.message.reply_text(
            f"❌ *Error al obtener el estado de PM2:*\n```\n{json_result}\n```",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # 2. Construimos la tabla
    lines = ["📊 *PM2 STATUS:*"]

    if not data:
        lines.append("No hay procesos PM2 activos.")
    else:
        # Encabezado
        lines.append("```")
        lines.append(" ID | Nombre      | CPU  | MEMORIA | Status")
        lines.append("----+-------------+------+---------+---------")

        for p in data:
            name = p["name"][:11].ljust(11)  # Limita y rellena el nombre
            pm_id = str(p["pm_id"]).ljust(2)
            cpu = str(p["monit"]["cpu"]).rjust(3) + "%"
            memory = round(p["monit"]["memory"] / (1024 * 1024), 1)  # MB

            # Formato del estado con emojis
            status_text = p["pm2_env"]["status"]
            if status_text == "online":
                status_emoji = "🟢"
            elif status_text == "stopped":
                status_emoji = "🛑"
            elif status_text == "errored":
                status_emoji = "🔴"
            else:
                status_emoji = "🟡"

            status_line = f"{pm_id} | {name} | {cpu} | {str(memory).rjust(5)}M | {status_emoji} {status_text}"
            lines.append(status_line)

        lines.append("```")

    final_message = "\n".join(lines)

    await update.message.reply_text(final_message, parse_mode=ParseMode.MARKDOWN)


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


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🤖 *Comandos disponibles:*\n\n"
        "/status - Ver procesos PM2\n"
        "/restart <nombre> - Reiniciar proceso\n"
        "/logs <nombre> [lineas] - Ver logs\n"
        "/help - Muestra esta ayuda"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


# --- MONITOREO AUTOMÁTICO ---
async def monitor_pm2(application):
    """Chequea el estado de PM2 cada intervalo y avisa cambios."""
    if not ALLOWED_USERS:
        print("⚠️ [Monitor] No hay usuarios autorizados para enviar alertas.")
        return

    chat_id = ALLOWED_USERS[0]
    last_status = await get_pm2_status()

    while True:
        await asyncio.sleep(CHECK_INTERVAL)
        current_status = await get_pm2_status()

        # Cambios de estado
        for name, status in current_status.items():
            old_status = last_status.get(name)
            if old_status != status:
                msg = f"⚠️ *Cambio detectado en {name}:*\n`{old_status}` → `{status}`"
                await application.bot.send_message(
                    chat_id=chat_id, text=msg, parse_mode=ParseMode.MARKDOWN
                )

        # Procesos eliminados
        for name in set(last_status) - set(current_status):
            await application.bot.send_message(
                chat_id=chat_id,
                text=f"🛑 *Proceso eliminado:* `{name}`",
                parse_mode=ParseMode.MARKDOWN,
            )

        # Procesos nuevos
        for name in set(current_status) - set(last_status):
            await application.bot.send_message(
                chat_id=chat_id,
                text=f"🟢 *Nuevo proceso detectado:* `{name}`",
                parse_mode=ParseMode.MARKDOWN,
            )

        last_status = current_status.copy()


# --- CALLBACK AL INICIAR EL BOT ---
async def on_startup(application):
    application.create_task(monitor_pm2(application))
    print("✅ Tarea de monitoreo PM2 iniciada.")


# --- MAIN ---
def main():
    app = ApplicationBuilder().token(TOKEN).post_init(on_startup).build()

    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("restart", restart))
    app.add_handler(CommandHandler("logs", logs))
    app.add_handler(CommandHandler("help", help_cmd))

    print("✅ Bot admin corriendo. Esperando comandos...")
    app.run_polling(
        allowed_updates=list(constants.UpdateType),
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
