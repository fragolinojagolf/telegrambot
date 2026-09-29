import os
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
ADMIN_ID = 5785266634
DB_NAME = os.environ.get("BONUSBOT_DB", "bonusbot.db")


# =========================
# DATABASE
# =========================

def db():
    conn = sqlite3.connect(DB_NAME, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS bonuses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT NOT NULL,
            amount TEXT NOT NULL,
            active INTEGER DEFAULT 1
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS completions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            bonus_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER,
            referred_id INTEGER UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()


def save_user(user):
    conn = db()
    conn.execute(
        """
        INSERT INTO users (id, username, first_name)
        VALUES (?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            username=excluded.username,
            first_name=excluded.first_name
        """,
        (user.id, user.username, user.first_name),
    )
    conn.commit()
    conn.close()


# =========================
# UTILITÀ
# =========================

async def safe_edit(query, text, reply_markup=None):
    try:
        await query.edit_message_text(
            text=text,
            reply_markup=reply_markup
        )
    except BadRequest as e:
        if "Message is not modified" not in str(e):
            raise


def main_keyboard(user_id):
    buttons = [
        [InlineKeyboardButton("🎁 Bonus disponibili", callback_data="bonus")],
        [InlineKeyboardButton("📋 Come funziona", callback_data="come_funziona")],
        [InlineKeyboardButton("✅ Ho completato", callback_data="completato")],
        [InlineKeyboardButton("🆘 Assistenza", callback_data="assistenza")],
        [InlineKeyboardButton("👥 Invita un amico", callback_data="invita")],
    ]

    if user_id == ADMIN_ID:
        buttons.append([
            InlineKeyboardButton("👑 Pannello Admin", callback_data="admin")
        ])

    return InlineKeyboardMarkup(buttons)


def admin_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Statistiche", callback_data="admin_stats")],
        [InlineKeyboardButton("🎁 Gestione bonus", callback_data="admin_bonus")],
        [InlineKeyboardButton("🔗 Referral", callback_data="admin_referrals")],
        [InlineKeyboardButton("👥 Utenti", callback_data="admin_users")],
        [InlineKeyboardButton("🏠 Menu", callback_data="menu")],
    ])


def bonus_keyboard(bonuses):
    buttons = []

    for bonus in bonuses:
        buttons.append([
            InlineKeyboardButton(
                f"🎁 {bonus['name']} — {bonus['amount']}",
                callback_data=f"bonus_{bonus['id']}"
            )
        ])

    buttons.append([
        InlineKeyboardButton("🏠 Menu", callback_data="menu")
    ])

    return InlineKeyboardMarkup(buttons)


# =========================
# START
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_user(user)

    # Referral
    if context.args:
        arg = context.args[0]

        if arg.startswith("ref_"):
            try:
                referrer_id = int(arg.replace("ref_", ""))

                if referrer_id != user.id:
                    conn = db()

                    existing = conn.execute(
                        "SELECT id FROM referrals WHERE referred_id = ?",
                        (user.id,)
                    ).fetchone()

                    if not existing:
                        conn.execute(
                            """
                            INSERT OR IGNORE INTO referrals
                            (referrer_id, referred_id)
                            VALUES (?, ?)
                            """,
                            (referrer_id, user.id)
                        )
                        conn.commit()

                    conn.close()

            except ValueError:
                pass

    text = (
        f"👋 Ciao {user.first_name}!\n\n"
        "🎁 Benvenuto nel nostro sistema bonus.\n\n"
        "Da qui puoi vedere le promozioni disponibili, "
        "iniziare una procedura e ricevere assistenza."
    )

    await update.message.reply_text(
        text,
        reply_markup=main_keyboard(user.id)
    )


async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"🆔 Il tuo ID Telegram è:\n\n{update.effective_user.id}"
    )


# =========================
# CALLBACK
# =========================

async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = query.from_user
    save_user(user)

    data = query.data

    # MENU
    if data == "menu":
        await safe_edit(
            query,
            (
                f"👋 Ciao {user.first_name}!\n\n"
                "🎁 Benvenuto nel nostro sistema bonus.\n\n"
                "Scegli un'opzione:"
            ),
            main_keyboard(user.id)
        )
        return

    # BONUS
    if data == "bonus":
        conn = db()
        bonuses = conn.execute(
            "SELECT * FROM bonuses WHERE active = 1 ORDER BY id DESC"
        ).fetchall()
        conn.close()

        if not bonuses:
            await safe_edit(
                query,
                "😔 Al momento non ci sono bonus disponibili.",
                InlineKeyboardMarkup([
                    [InlineKeyboardButton("🏠 Menu", callback_data="menu")]
                ])
            )
            return

        await safe_edit(
            query,
            "🎁 **Bonus disponibili**\n\nScegli una promozione:",
            bonus_keyboard(bonuses)
        )
        return

    # DETTAGLIO BONUS
    if data.startswith("bonus_"):
        try:
            bonus_id = int(data.split("_")[1])
        except ValueError:
            return

        conn = db()
        bonus = conn.execute(
            "SELECT * FROM bonuses WHERE id = ? AND active = 1",
            (bonus_id,)
        ).fetchone()
        conn.close()

        if not bonus:
            await safe_edit(
                query,
                "❌ Questo bonus non è più disponibile.",
                InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "🎁 Torna ai bonus",
                        callback_data="bonus"
                    )]
                ])
            )
            return

        text = (
            f"🎁 **{bonus['name']}**\n\n"
            f"💰 Bonus: **{bonus['amount']}**\n\n"
            f"ℹ️ {bonus['description']}\n\n"
            "Quando hai completato la procedura, premi "
            "«Ho completato»."
        )

        await safe_edit(
            query,
            text,
            InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "✅ Ho completato",
                    callback_data=f"done_{bonus_id}"
                )],
                [InlineKeyboardButton(
                    "⬅️ Torna ai bonus",
                    callback_data="bonus"
                )],
            ])
        )
        return

    # COMPLETATO
    if data == "completato":
        conn = db()
        bonuses = conn.execute(
            "SELECT * FROM bonuses WHERE active = 1 ORDER BY id DESC"
        ).fetchall()
        conn.close()

        if not bonuses:
            await safe_edit(
                query,
                "Non ci sono bonus disponibili.",
                InlineKeyboardMarkup([
                    [InlineKeyboardButton("🏠 Menu", callback_data="menu")]
                ])
            )
            return

        buttons = [
            [
                InlineKeyboardButton(
                    f"✅ {b['name']}",
                    callback_data=f"done_{b['id']}"
                )
            ]
            for b in bonuses
        ]

        buttons.append([
            InlineKeyboardButton("🏠 Menu", callback_data="menu")
        ])

        await safe_edit(
            query,
            "✅ Seleziona il bonus che hai completato:",
            InlineKeyboardMarkup(buttons)
        )
        return

    # CONFERMA COMPLETAMENTO
    if data.startswith("done_"):
        try:
            bonus_id = int(data.split("_")[1])
        except ValueError:
            return

        conn = db()

        bonus = conn.execute(
            "SELECT * FROM bonuses WHERE id = ?",
            (bonus_id,)
        ).fetchone()

        if bonus:
            conn.execute(
                """
                INSERT INTO completions (user_id, bonus_id)
                VALUES (?, ?)
                """,
                (user.id, bonus_id)
            )
            conn.commit()

        conn.close()

        await safe_edit(
            query,
            (
                "✅ **Segnalazione ricevuta!**\n\n"
                "Abbiamo registrato che hai completato la procedura.\n"
                "L'amministratore potrà verificare la richiesta."
            ),
            InlineKeyboardMarkup([
                [InlineKeyboardButton("🏠 Menu", callback_data="menu")]
            ])
        )

        try:
            await context.bot.send_message(
                ADMIN_ID,
                (
                    "🔔 **Nuovo completamento!**\n\n"
                    f"👤 {user.first_name}\n"
                    f"🆔 `{user.id}`\n"
                    f"🎁 {bonus['name'] if bonus else 'Bonus'}"
                )
            )
        except Exception:
            pass

        return

    # COME FUNZIONA
    if data == "come_funziona":
        await safe_edit(
            query,
            (
                "📋 **Come funziona**\n\n"
                "1️⃣ Scegli uno dei bonus disponibili.\n\n"
                "2️⃣ Segui le istruzioni indicate.\n\n"
                "3️⃣ Completa la procedura richiesta.\n\n"
                "4️⃣ Premi «Ho completato» per segnalare "
                "la conclusione.\n\n"
                "5️⃣ Attendi la verifica."
            ),
            InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "🎁 Vedi i bonus",
                    callback_data="bonus"
                )],
                [InlineKeyboardButton(
                    "🏠 Menu",
                    callback_data="menu"
                )]
            ])
        )
        return

    # ASSISTENZA 
       if data == "assistenza":
    # ADMIN
    if data == "admin":
        if user.id != ADMIN_ID:
            return

        await safe_edit(
            query,
            "👑 **Pannello Admin**\n\nScegli un'opzione:",
            admin_keyboard()
        )
        return

    # STATISTICHE
    if data == "admin_stats":
        if user.id != ADMIN_ID:
            return

        conn = db()

        users = conn.execute(
            "SELECT COUNT(*) AS c FROM users"
        ).fetchone()["c"]

        completions = conn.execute(
            "SELECT COUNT(*) AS c FROM completions"
        ).fetchone()["c"]

        referrals = conn.execute(
            "SELECT COUNT(*) AS c FROM referrals"
        ).fetchone()["c"]

        bonuses = conn.execute(
            "SELECT COUNT(*) AS c FROM bonuses WHERE active = 1"
        ).fetchone()["c"]

        conn.close()

        await safe_edit(
            query,
            (
                "📊 **Statistiche**\n\n"
                f"👥 Utenti: **{users}**\n"
                f"🎁 Bonus attivi: **{bonuses}**\n"
                f"✅ Completamenti: **{completions}**\n"
                f"🔗 Referral: **{referrals}**"
            ),
            InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "⬅️ Admin",
                    callback_data="admin"
                )]
            ])
        )
        return

    # REFERRAL ADMIN
    if data == "admin_referrals":
        if user.id != ADMIN_ID:
            return

        conn = db()

        rows = conn.execute("""
            SELECT referrer_id, COUNT(*) AS total
            FROM referrals
            GROUP BY referrer_id
            ORDER BY total DESC
            LIMIT 20
        """).fetchall()

        conn.close()

        if not rows:
            text = "🔗 **Referral**\n\nNessun referral registrato."
        else:
            text = "🔗 **Referral**\n\n"

            for row in rows:
                text += (
                    f"🆔 {row['referrer_id']} → "
                    f"**{row['total']}**\n"
                )

        await safe_edit(
            query,
            text,
            InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "⬅️ Admin",
                    callback_data="admin"
                )]
            ])
        )
        return

    # UTENTI
    if data == "admin_users":
        if user.id != ADMIN_ID:
            return

        conn = db()

        users = conn.execute("""
            SELECT * FROM users
            ORDER BY created_at DESC
            LIMIT 20
        """).fetchall()

        total = conn.execute(
            "SELECT COUNT(*) AS c FROM users"
        ).fetchone()["c"]

        conn.close()

        text = f"👥 **Utenti** — Totale: {total}\n\n"

        for u in users:
            username = f"@{u['username']}" if u["username"] else "senza username"
            text += f"• {u['first_name']} — {username} — `{u['id']}`\n"

        await safe_edit(
            query,
            text,
            InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "⬅️ Admin",
                    callback_data="admin"
                )]
            ])
        )
        return

    # GESTIONE BONUS
    if data == "admin_bonus":
        if user.id != ADMIN_ID:
            return

        conn = db()
        bonuses = conn.execute(
            "SELECT * FROM bonuses ORDER BY id DESC"
        ).fetchall()
        conn.close()

        buttons = [
            [
                InlineKeyboardButton(
                    f"{'🟢' if b['active'] else '🔴'} {b['name']}",
                    callback_data=f"admin_bonus_view_{b['id']}"
                )
            ]
            for b in bonuses
        ]

        buttons.append([
            InlineKeyboardButton(
                "➕ Aggiungi bonus",
                callback_data="admin_add_bonus"
            )
        ])

        buttons.append([
            InlineKeyboardButton(
                "⬅️ Admin",
                callback_data="admin"
            )
        ])

        await safe_edit(
            query,
            "🎁 **Gestione bonus**\n\nSeleziona un bonus:",
            InlineKeyboardMarkup(buttons)
        )
        return

    # VISUALIZZA BONUS ADMIN
    if data.startswith("admin_bonus_view_"):
        if user.id != ADMIN_ID:
            return

        try:
            bonus_id = int(data.split("_")[-1])
        except ValueError:
            return

        conn = db()
        bonus = conn.execute(
            "SELECT * FROM bonuses WHERE id = ?",
            (bonus_id,)
        ).fetchone()
        conn.close()

        if not bonus:
            return

        status = "🟢 Attivo" if bonus["active"] else "🔴 Disattivato"

        await safe_edit(
            query,
            (
                f"🎁 **{bonus['name']}**\n\n"
                f"💰 {bonus['amount']}\n\n"
                f"📝 {bonus['description']}\n\n"
                f"Stato: {status}"
            ),
            InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "🔄 Attiva/Disattiva",
                    callback_data=f"toggle_{bonus_id}"
                )],
                [InlineKeyboardButton(
                    "🗑 Elimina",
                    callback_data=f"delete_{bonus_id}"
                )],
                [InlineKeyboardButton(
                    "⬅️ Torna ai bonus",
                    callback_data="admin_bonus"
                )]
            ])
        )
        return

    # TOGGLE
    if data.startswith("toggle_"):
        if user.id != ADMIN_ID:
            return

        try:
            bonus_id = int(data.split("_")[1])
        except ValueError:
            return

        conn = db()

        bonus = conn.execute(
            "SELECT active FROM bonuses WHERE id = ?",
            (bonus_id,)
        ).fetchone()

        if bonus:
            conn.execute(
                "UPDATE bonuses SET active = ? WHERE id = ?",
                (0 if bonus["active"] else 1, bonus_id)
            )
            conn.commit()

        conn.close()

        await safe_edit(
            query,
            "✅ Stato del bonus aggiornato.",
            InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "⬅️ Gestione bonus",
                    callback_data="admin_bonus"
                )]
            ])
        )
        return

    # DELETE
    if data.startswith("delete_"):
        if user.id != ADMIN_ID:
            return

        try:
            bonus_id = int(data.split("_")[1])
        except ValueError:
            return

        conn = db()
        conn.execute(
            "DELETE FROM bonuses WHERE id = ?",
            (bonus_id,)
        )
        conn.commit()
        conn.close()

        await safe_edit(
            query,
            "🗑 Bonus eliminato.",
            InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "⬅️ Gestione bonus",
                    callback_data="admin_bonus"
                )]
            ])
        )
        return

    # AGGIUNGI BONUS
    if data == "admin_add_bonus":
        if user.id != ADMIN_ID:
            return

        context.user_data["admin_state"] = "bonus_name"

        await safe_edit(
            query,
            (
                "➕ **Nuovo bonus**\n\n"
                "Scrivi il **nome** del bonus."
            ),
            InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "❌ Annulla",
                    callback_data="admin_bonus"
                )]
            ])
        )
        return


# =========================
# MESSAGGI TESTUALI
# =========================

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_user(user)

    text = update.message.text.strip()

    # Creazione bonus admin
    if user.id == ADMIN_ID and context.user_data.get("admin_state"):
        state = context.user_data["admin_state"]

        if state == "bonus_name":
            context.user_data["bonus_name"] = text
            context.user_data["admin_state"] = "bonus_amount"

            await update.message.reply_text(
                "💰 Ora scrivi l'importo del bonus.\n\n"
                "Esempio: `80€`"
            )
            return

        if state == "bonus_amount":
            context.user_data["bonus_amount"] = text
            context.user_data["admin_state"] = "bonus_description"

            await update.message.reply_text(
                "📝 Ora scrivi la descrizione del bonus."
            )
            return

        if state == "bonus_description":
            name = context.user_data["bonus_name"]
            amount = context.user_data["bonus_amount"]

            conn = db()
            conn.execute(
                """
                INSERT INTO bonuses (name, description, amount, active)
                VALUES (?, ?, ?, 1)
                """,
                (name, text, amount)
            )
            conn.commit()
            conn.close()

            context.user_data.pop("admin_state", None)
            context.user_data.pop("bonus_name", None)
            context.user_data.pop("bonus_amount", None)

            await update.message.reply_text(
                "✅ **Bonus creato correttamente!**",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "🎁 Gestione bonus",
                        callback_data="admin_bonus"
                    )],
                    [InlineKeyboardButton(
                        "🏠 Menu",
                        callback_data="menu"
                    )]
                ])
            )
            return

    # ASSISTENZA
    if context.user_data.get("support_mode"):
        context.user_data["support_mode"] = False

        try:
            await context.bot.send_message(
                ADMIN_ID,
                (
                    "🆘 **Nuova richiesta di assistenza**\n\n"
                    f"👤 {user.first_name}\n"
                    f"🆔 `{user.id}`\n"
                    f"💬 {text}"
                )
            )

            await update.message.reply_text(
                "✅ Messaggio inviato all'amministratore.\n\n"
                "Ti risponderà appena possibile.",
                reply_markup=main_keyboard(user.id)
            )

        except Exception:
            await update.message.reply_text(
                "❌ Non è stato possibile inviare il messaggio.",
                reply_markup=main_keyboard(user.id)
            )

        return

    await update.message.reply_text(
        "Usa il menu qui sotto per scegliere un'opzione.",
        reply_markup=main_keyboard(user.id)
    )


# =========================
# HEALTH SERVER RENDER
# =========================

class HealthHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"BonusBot OK")

    def log_message(self, format, *args):
        return


def start_health_server():
    port = int(os.environ.get("PORT", "10000"))

    server = HTTPServer(
        ("0.0.0.0", port),
        HealthHandler
    )

    print(f"Health server attivo sulla porta {port}")
    server.serve_forever()


# =========================
# AVVIO
# =========================

def main():

    if not TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN non impostato."
        )

    init_db()

    threading.Thread(
        target=start_health_server,
        daemon=True
    ).start()

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myid", myid))

    app.add_handler(
        CallbackQueryHandler(callback)
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_handler
        )
    )

    print("BonusBot avviato")

    app.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
