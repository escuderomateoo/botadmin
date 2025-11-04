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


# --- FUNCIONES DE SISTEMA ---
def run_cmd(cmd: str) -> str:
    """Ejecuta un comando en bash y devuelve su salida."""
    try:
        output = subprocess.check_output(
            cmd, shell=True, stderr=subprocess.STDOUT, text=True
        )
        return output.strip()
    except subprocess.CalledProcessError as e:
        return e.output.strip()


def get_pm2_status() -> dict:
    """Devuelve un dict con los procesos y su estado."""
    try:
        output = run_cmd("pm2 jlist")
        data = json.loads(output)
        return {p["name"]: p["pm2_env"]["status"] for p in data}
    except Exception:
        return {}


# --- DECORADOR DE SEGURIDAD ---
def restricted(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id not in ALLOWED_USERS:
            await update.message.reply_text(
                "🚫 No estás autorizado para usar este bot."
            )
            return
        return await func(update, context)

    return wrapper


# --- COMANDOS ---
@restricted
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = run_cmd("pm2 list")
    await update.message.reply_text(
        f"📊 *PM2 STATUS:*\n``````", parse_mode=ParseMode.MARKDOWN
    )


@restricted
async def restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usá /restart <nombre_proceso>")
        return
    name = context.args[0]
    result = run_cmd(f"pm2 restart {name}")
    await update.message.reply_text(
        f"🔁 *Reinicio de {name}:*\n``````", parse_mode=ParseMode.MARKDOWN
    )


@restricted
async def logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usá /logs <nombre_proceso> [lineas]")
        return
    name = context.args[0]
    lines = context.args[1] if len(context.args) > 1 else "30"
    result = run_cmd(f"pm2 logs {name} --lines {lines} --nostream")
    await update.message.reply_text(
        f"📜 *Logs de {name}:*\n``````", parse_mode=ParseMode.MARKDOWN
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🤖 *Comandos disponibles:*\n\n"
        "/status - Ver procesos PM2\n"
        "/restart <nombre> - Reiniciar proceso\n"
        "/logs <nombre> [lineas] - Ver logs\n"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


# --- ALERTAS AUTOMÁTICAS ---
async def monitor_pm2(application):
    """Chequea el estado de PM2 cada intervalo y avisa cambios."""
    chat_id = ALLOWED_USERS[0]
    last_status = get_pm2_status()

    while True:
        await asyncio.sleep(CHECK_INTERVAL)
        current_status = get_pm2_status()

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


# --- MAIN ---
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("restart", restart))
    app.add_handler(CommandHandler("logs", logs))
    app.add_handler(CommandHandler("help", help_cmd))

    # El monitor se inicia como tarea dentro del event loop controlado por run_polling()
    app.create_task(monitor_pm2(app))

    print("✅ Bot admin corriendo. Esperando comandos...")
    app.run_polling(
        allowed_updates=list(constants.UpdateType), drop_pending_updates=True
    )


# Bloque de ejecución principal
if __name__ == "__main__":
    main()
