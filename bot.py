import os
import re
import sqlite3
import threading
from html import escape
from http.server import BaseHTTPRequestHandler, HTTPServer

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest
from telegram.ext import (
Application, CommandHandler, CallbackQueryHandler, ContextTypes,
MessageHandler, filters,
)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
ADMIN_ID = 5785266634
DB_NAME = os.environ.get("BONUSBOT_DB", "bonusbot.db")

# -------------------------------------------------

# DATABASE

# -------------------------------------------------

def db():
conn = sqlite3.connect(DB_NAME, timeout=15)
conn.row_factory = sqlite3.Row
conn.execute("PRAGMA foreign_keys = ON")
return conn

def init_db():
with db() as c:
c.executescript("""
CREATE TABLE IF NOT EXISTS users (
id INTEGER PRIMARY KEY,
username TEXT,
first_name TEXT,
joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
referrer_id INTEGER
);

```
    CREATE TABLE IF NOT EXISTS progress (
        user_id INTEGER PRIMARY KEY,
        completed INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS support (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        username TEXT,
        message TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS bonuses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        amount TEXT NOT NULL DEFAULT '',
        link TEXT NOT NULL DEFAULT '',
        instructions TEXT NOT NULL DEFAULT '',
        active INTEGER NOT NULL DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS completions (
        user_id INTEGER NOT NULL,
        bonus_id INTEGER NOT NULL,
        completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (user_id, bonus_id),
        FOREIGN KEY (bonus_id) REFERENCES bonuses(id) ON DELETE CASCADE
    );
    """)

    cols = {
        row[1]
        for row in c.execute("PRAGMA table_info(users)")
    }

    if "referrer_id" not in cols:
        c.execute(
            "ALTER TABLE users ADD COLUMN referrer_id INTEGER"
        )

    count = c.execute(
        "SELECT COUNT(*) FROM bonuses"
    ).fetchone()[0]

    if not count:
        c.execute(
            """
            INSERT INTO bonuses
            (title, amount, link, instructions)
            VALUES (?, ?, ?, ?)
            """,
            (
                "Bonus 80€",
                "80 €",
                "",
                "Registrati dal link ufficiale, completa i requisiti della promozione e attendi l'erogazione secondo i termini."
            )
        )

    first_bonus = c.execute(
        "SELECT id FROM bonuses ORDER BY id LIMIT 1"
    ).fetchone()

    if first_bonus:
        c.execute(
            """
            INSERT OR IGNORE INTO completions(user_id, bonus_id)
            SELECT user_id, ?
            FROM progress
            WHERE completed = 1
            """,
            (first_bonus["id"],)
        )
```

def save_user(user, referrer_id=None):
if not user:
return

```
with db() as c:
    row = c.execute(
        "SELECT referrer_id FROM users WHERE id=?",
        (user.id,)
    ).fetchone()

    ref = (
        referrer_id
        if referrer_id and referrer_id != user.id
        else None
    )

    if row is None:
        c.execute(
            """
            INSERT INTO users
            (id, username, first_name, referrer_id)
            VALUES (?, ?, ?, ?)
            """,
            (
                user.id,
                user.username,
                user.first_name or "",
                ref
            )
        )
    else:
        # Manteniamo il referral originale.
        c.execute(
            """
            UPDATE users
            SET username=?, first_name=?
            WHERE id=?
            """,
            (
                user.username,
                user.first_name or "",
                user.id
            )
        )
```

# -------------------------------------------------

# MENU

# -------------------------------------------------

def main_menu(uid):
rows = [
[
InlineKeyboardButton(
"🎁 Bonus disponibili",
callback_data="bonus"
)
],
[
InlineKeyboardButton(
"📋 Come funziona",
callback_data="come_funziona"
)
],
[
InlineKeyboardButton(
"✅ Ho completato",
callback_data="completato"
)
],
[
InlineKeyboardButton(
"🆘 Assistenza",
callback_data="assistenza"
)
],
[
InlineKeyboardButton(
"👥 Invita un amico",
callback_data="invita"
)
],
]

```
if uid == ADMIN_ID:
    rows.append([
        InlineKeyboardButton(
            "👑 Pannello Admin",
            callback_data="admin"
        )
    ])

return InlineKeyboardMarkup(rows)
```

def admin_menu():
return InlineKeyboardMarkup([
[
InlineKeyboardButton(
"📊 Statistiche",
callback_data="admin_stats"
),
InlineKeyboardButton(
"🎁 Gestione bonus",
callback_data="admin_bonus"
)
],
[
InlineKeyboardButton(
"🔗 Statistiche referral",
callback_data="admin_referrals"
)
],
[
InlineKeyboardButton(
"👥 Utenti",
callback_data="admin_users"
),
InlineKeyboardButton(
"📩 Assistenza",
callback_data="admin_support"
)
],
[
InlineKeyboardButton(
"🏠 Menu",
callback_data="menu"
)
],
])

def bonus_list_keyboard(rows, admin=False):
buttons = []

```
for b in rows:
    label = (
        f"{'🟢' if b['active'] else '⚪'} "
        f"{b['title']} · {b['amount']}"
    )[:60]

    buttons.append([
        InlineKeyboardButton(
            label,
            callback_data=(
                f"{'be' if admin else 'bv'}:{b['id']}"
            )
        )
    ])

if admin:
    buttons.append([
        InlineKeyboardButton(
            "➕ Aggiungi bonus",
            callback_data="ba"
        )
    ])

    buttons.append([
        InlineKeyboardButton(
            "⬅️ Admin",
            callback_data="admin"
        )
    ])
else:
    buttons.append([
        InlineKeyboardButton(
            "⬅️ Menu",
            callback_data="menu"
        )
    ])

return InlineKeyboardMarkup(buttons)
```

# -------------------------------------------------

# MODIFICA SICURA DEI MESSAGGI

# -------------------------------------------------

async def safe_edit(query, text, reply_markup=None):
"""
Modifica il messaggio senza far fallire il bot
quando il contenuto è già identico.
"""

```
try:
    await query.edit_message_text(
        text,
        reply_markup=reply_markup
    )

except BadRequest as e:
    if "Message is not modified" in str(e):
        return

    raise
```

# -------------------------------------------------

# COMANDI

# -------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
user = update.effective_user

```
ref = None

if context.args and context.args[0].startswith("ref_"):
    try:
        ref = int(context.args[0][4:])
    except ValueError:
        pass

save_user(user, ref)

await update.message.reply_text(
    f"👋 Ciao {escape(user.first_name or 'utente')}!\n\n"
    "🎁 Benvenuto nel sistema bonus.\n\n"
    "Scegli un'opzione dal menu:",
    reply_markup=main_menu(user.id)
)
```

async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
await update.message.reply_text(
f"Il tuo ID Telegram è: {update.effective_user.id}"
)

# -------------------------------------------------

# ADMIN

# -------------------------------------------------

async def prompt(update, context, stage, text):
context.user_data["admin_stage"] = stage

```
await safe_edit(
    update.callback_query,
    text,
    InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "Annulla",
                callback_data="admin_bonus"
            )
        ]
    ])
)
```

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
user = update.effective_user

```
if not user or user.id != ADMIN_ID:
    return

stage = context.user_data.get("admin_stage")

if not stage:
    return

value = (update.message.text or "").strip()

if not value:
    await update.message.reply_text(
        "Il testo è vuoto. Riprova oppure annulla dal pannello."
    )
    return

if len(value) > 3500:
    await update.message.reply_text(
        "Testo troppo lungo (massimo 3500 caratteri). Riprova."
    )
    return

kind, _, raw_id = stage.partition(":")

bonus_id = (
    int(raw_id)
    if raw_id.isdigit()
    else None
)

if kind == "new_title":
    with db() as c:
        cur = c.execute(
            "INSERT INTO bonuses(title) VALUES(?)",
            (value,)
        )
        bonus_id = cur.lastrowid

    context.user_data.pop("admin_stage", None)

    await update.message.reply_text(
        "Bonus creato. Ora puoi modificarne importo, link e istruzioni.",
        reply_markup=bonus_admin_keyboard(bonus_id)
    )
    return

fields = {
    "title": "title",
    "amount": "amount",
    "link": "link",
    "instructions": "instructions"
}

if kind not in fields or not bonus_id:
    context.user_data.pop("admin_stage", None)

    await update.message.reply_text(
        "Modifica annullata: stato non valido."
    )
    return

if (
    kind == "link"
    and value.lower() not in ("nessuno", "-", "rimuovi")
    and not re.match(r"^https?://\S+$", value)
):
    await update.message.reply_text(
        "Inserisci un link http/https completo, oppure scrivi 'nessuno'."
    )
    return

if (
    kind == "link"
    and value.lower() in ("nessuno", "-", "rimuovi")
):
    value = ""

with db() as c:
    c.execute(
        f"UPDATE bonuses SET {fields[kind]}=? WHERE id=?",
        (value, bonus_id)
    )

context.user_data.pop("admin_stage", None)

await update.message.reply_text(
    "✅ Bonus aggiornato.",
    reply_markup=bonus_admin_keyboard(bonus_id)
)
```

def bonus_admin_keyboard(bid):
return InlineKeyboardMarkup([
[
InlineKeyboardButton(
"✏️ Nome",
callback_data=f"bf:title:{bid}"
),
InlineKeyboardButton(
"💰 Importo",
callback_data=f"bf:amount:{bid}"
)
],
[
InlineKeyboardButton(
"🔗 Link",
callback_data=f"bf:link:{bid}"
),
InlineKeyboardButton(
"📋 Istruzioni",
callback_data=f"bf:instructions:{bid}"
)
],
[
InlineKeyboardButton(
"🟢/⚪ Attiva o disattiva",
callback_data=f"bt:{bid}"
)
],
[
InlineKeyboardButton(
"🗑️ Elimina",
callback_data=f"bd:{bid}"
)
],
[
InlineKeyboardButton(
"⬅️ Lista bonus",
callback_data="admin_bonus"
)
],
])

# -------------------------------------------------

# CALLBACK

# -------------------------------------------------

async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
q = update.callback_query

```
await q.answer()

user = q.from_user
save_user(user)

data = q.data or ""

if (
    data.startswith("admin")
    or data in ("admin", "ba")
    or data.startswith(("be:", "bf:", "bt:", "bd:", "bdel:"))
):
    if user.id != ADMIN_ID:
        return

if data == "menu":

    context.user_data.pop("selected_bonus", None)

    await safe_edit(
        q,
        "🏠 MENU PRINCIPALE",
        main_menu(user.id)
    )

elif data == "bonus":

    with db() as c:
        rows = c.execute(
            "SELECT * FROM bonuses WHERE active=1 ORDER BY id"
        ).fetchall()

    await safe_edit(
        q,
        "🎁 BONUS DISPONIBILI\nScegli una promozione:",
        bonus_list_keyboard(rows)
    )

elif data.startswith("bv:"):

    bid = int(data.split(":")[1])

    with db() as c:
        b = c.execute(
            """
            SELECT *
            FROM bonuses
            WHERE id=? AND active=1
            """,
            (bid,)
        ).fetchone()

    if not b:
        await safe_edit(
            q,
            "Questo bonus non è più disponibile.",
            main_menu(user.id)
        )
        return

    context.user_data["selected_bonus"] = bid

    buttons = []

    if b["link"]:
        buttons.append([
            InlineKeyboardButton(
                "🔗 Apri link",
                url=b["link"]
            )
        ])

    buttons += [
        [
            InlineKeyboardButton(
                "✅ Ho completato",
                callback_data="completato"
            )
        ],
        [
            InlineKeyboardButton(
                "⬅️ Bonus",
                callback_data="bonus"
            )
        ]
    ]

    await safe_edit(
        q,
        (
            f"🎁 {b['title']} · {b['amount']}\n\n"
            f"{b['instructions'] or 'Segui le istruzioni della promozione.'}"
        ),
        InlineKeyboardMarkup(buttons)
    )

elif data == "come_funziona":

    await safe_edit(
        q,
        "📋 Scegli un bonus, segui le istruzioni e segnalo come completato quando hai finito.",
        InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🎁 Bonus",
                    callback_data="bonus"
                )
            ],
            [
                InlineKeyboardButton(
                    "⬅️ Menu",
                    callback_data="menu"
                )
            ]
        ])
    )

elif data == "completato":

    bid = context.user_data.get("selected_bonus")

    if not bid:
        with db() as c:
            row = c.execute(
                """
                SELECT id
                FROM bonuses
                WHERE active=1
                ORDER BY id
                LIMIT 1
                """
            ).fetchone()

        bid = row["id"] if row else None

    if not bid:
        await safe_edit(
            q,
            "Al momento non ci sono bonus disponibili.",
            main_menu(user.id)
        )
        return

    with db() as c:

        cur = c.execute(
            """
            INSERT OR IGNORE INTO completions
            (user_id, bonus_id)
            VALUES (?, ?)
            """,
            (user.id, bid)
        )

        first_time = cur.rowcount == 1

        c.execute(
            """
            INSERT INTO progress(user_id, completed)
            VALUES (?, 1)
            ON CONFLICT(user_id)
            DO UPDATE SET completed=1
            """,
            (user.id,)
        )

        b = c.execute(
            "SELECT title FROM bonuses WHERE id=?",
            (bid,)
        ).fetchone()

        ref = c.execute(
            "SELECT referrer_id FROM users WHERE id=?",
            (user.id,)
        ).fetchone()

    if first_time:

        try:
            await context.bot.send_message(
                ADMIN_ID,
                (
                    "✅ Procedura completata\n"
                    f"👤 {user.first_name or 'utente'} "
                    f"(ID {user.id})\n"
                    f"🎁 {b['title'] if b else 'Bonus'}\n"
                    f"🔗 Referral di: "
                    f"{ref['referrer_id'] if ref and ref['referrer_id'] else 'nessuno'}"
                )
            )
        except Exception:
            pass

    await safe_edit(
        q,
        "✅ Completamento registrato.",
        InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🏠 Menu",
                    callback_data="menu"
                )
            ]
        ])
    )

elif data == "invita":

    me = await context.bot.get_me()

    link = (
        f"https://t.me/{me.username}"
        f"?start=ref_{user.id}"
    )

    await safe_edit(
        q,
        (
            "👥 Condividi il tuo link personale:\n\n"
            f"{link}\n\n"
            "Gli amici verranno associati al tuo profilo."
        ),
        InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "⬅️ Menu",
                    callback_data="menu"
                )
            ]
        ])
    )

elif data == "assistenza":

    await safe_edit(
        q,
        "🆘 Per assistenza, scrivi la tua richiesta qui.",
        InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "⬅️ Menu",
                    callback_data="menu"
                )
            ]
        ])
    )

elif data == "admin":

    await safe_edit(
        q,
        "👑 PANNELLO AMMINISTRATORE",
        admin_menu()
    )

elif data == "admin_stats":

    with db() as c:
        users = c.execute(
            "SELECT COUNT(*) FROM users"
        ).fetchone()[0]

        done = c.execute(
            "SELECT COUNT(*) FROM completions"
        ).fetchone()[0]

        refs = c.execute(
            """
            SELECT COUNT(*)
            FROM users
            WHERE referrer_id IS NOT NULL
            """
        ).fetchone()[0]

    await safe_edit(
        q,
        (
            "📊 STATISTICHE\n\n"
            f"👥 Utenti: {users}\n"
            f"✅ Completamenti: {done}\n"
            f"🔗 Utenti da referral: {refs}"
        ),
        admin_menu()
    )

elif data == "admin_referrals":

    with db() as c:
        rows = c.execute(
            """
            SELECT referrer_id, COUNT(*) AS n
            FROM users
            WHERE referrer_id IS NOT NULL
            GROUP BY referrer_id
            ORDER BY n DESC
            LIMIT 20
            """
        ).fetchall()

        entries = []

        for r in rows:
            done = c.execute(
                """
                SELECT COUNT(*)
                FROM completions x
                JOIN users y ON y.id=x.user_id
                WHERE y.referrer_id=?
                """,
                (r["referrer_id"],)
            ).fetchone()[0]

            entries.append(
                f"ID {r['referrer_id']}: "
                f"{r['n']} iscritti, "
                f"{done} completamenti"
            )

    text = (
        "🔗 REFERRAL (massimo 20)\n\n"
        + (
            "\n".join(entries)
            if entries
            else "Nessun referral registrato."
        )
    )

    await safe_edit(
        q,
        text[:4000],
        admin_menu()
    )

elif data == "admin_users":

    with db() as c:
        rows = c.execute(
            """
            SELECT id, first_name, username
            FROM users
            ORDER BY joined_at DESC
            LIMIT 10
            """
        ).fetchall()

    text = (
        "👥 ULTIMI UTENTI\n\n"
        + (
            "\n".join(
                f"{r['first_name']} "
                f"(@{r['username'] or 'nessuno'}) "
                f"· {r['id']}"
                for r in rows
            )
            if rows
            else "Nessun utente."
        )
    )

    await safe_edit(
        q,
        text,
        admin_menu()
    )

elif data == "admin_support":

    with db() as c:
        n = c.execute(
            "SELECT COUNT(*) FROM support"
        ).fetchone()[0]

    await safe_edit(
        q,
        f"📩 Richieste registrate: {n}",
        admin_menu()
    )

elif data == "admin_bonus":

    with db() as c:
        rows = c.execute(
            "SELECT * FROM bonuses ORDER BY id"
        ).fetchall()

    await safe_edit(
        q,
        "🎁 GESTIONE BONUS\nScegli un bonus da modificare:",
        bonus_list_keyboard(rows, True)
    )

elif data == "ba":

    await prompt(
        update,
        context,
        "new_title",
        "Invia il nome del nuovo bonus."
    )

elif data.startswith("be:"):

    bid = int(data.split(":")[1])

    with db() as c:
        b = c.execute(
            "SELECT * FROM bonuses WHERE id=?",
            (bid,)
        ).fetchone()

    if b:
        await safe_edit(
            q,
            (
                f"🎁 {b['title']} · {b['amount']}\n"
                f"Stato: {'attivo' if b['active'] else 'disattivo'}\n"
                f"Link: {b['link'] or 'nessuno'}\n\n"
                f"{b['instructions'][:800]}"
            ),
            bonus_admin_keyboard(bid)
        )

elif data.startswith("bf:"):

    _, kind, raw_id = data.split(":")

    labels = {
        "title": "nome",
        "amount": "importo",
        "link": "link http/https (o 'nessuno')",
        "instructions": "istruzioni"
    }

    if kind in labels:
        await prompt(
            update,
            context,
            f"{kind}:{raw_id}",
            f"Invia il nuovo {labels[kind]} del bonus."
        )

elif data.startswith("bt:"):

    bid = int(data.split(":")[1])

    with db() as c:
        c.execute(
            """
            UPDATE bonuses
            SET active=1-active
            WHERE id=?
            """,
            (bid,)
        )

    await safe_edit(
        q,
        "Stato del bonus aggiornato.",
        bonus_admin_keyboard(bid)
    )

elif data.startswith("bd:"):

    bid = int(data.split(":")[1])

    await safe_edit(
        q,
        "Eliminare questo bonus e i suoi completamenti?",
        InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "Conferma eliminazione",
                    callback_data=f"bdel:{bid}"
                )
            ],
            [
                InlineKeyboardButton(
                    "Annulla",
                    callback_data=f"be:{bid}"
                )
            ]
        ])
    )

elif data.startswith("bdel:"):

    bid = int(data.split(":")[1])

    with db() as c:
        c.execute(
            "DELETE FROM completions WHERE bonus_id=?",
            (bid,)
        )

        c.execute(
            "DELETE FROM bonuses WHERE id=?",
            (bid,)
        )

    await safe_edit(
        q,
        "Bonus eliminato.",
        InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🎁 Gestione bonus",
                    callback_data="admin_bonus"
                )
            ]
        ])
    )
```

# -------------------------------------------------

# RENDER HEALTH SERVER

# -------------------------------------------------

class HealthHandler(BaseHTTPRequestHandler):

```
def do_GET(self):
    self.send_response(200)
    self.send_header("Content-Type", "text/plain")
    self.end_headers()
    self.wfile.write(b"BonusBot OK")

def log_message(self, format, *args):
    return
```

def start_health_server():
port = int(os.environ.get("PORT", "10000"))

```
server = HTTPServer(
    ("0.0.0.0", port),
    HealthHandler
)

print(f"Health server attivo sulla porta {port}")

server.serve_forever()
```

# -------------------------------------------------

# AVVIO

# -------------------------------------------------

def main():

```
if not TOKEN or TOKEN == "INSERISCI_TOKEN":
    raise RuntimeError(
        "Token Telegram non configurato."
    )

init_db()

# Server HTTP per Render
threading.Thread(
    target=start_health_server,
    daemon=True
).start()

app = (
    Application
    .builder()
    .token(TOKEN)
    .build()
)

app.add_handler(
    CommandHandler("start", start)
)

app.add_handler(
    CommandHandler("myid", myid)
)

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

app.run_polling()
```

if **name** == "**main**":
main()

