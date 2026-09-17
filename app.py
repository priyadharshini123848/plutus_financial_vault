import os, sqlite3, hashlib, secrets, html, mimetypes, webbrowser, json
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse, parse_qs
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "plutus.db")
STATIC = os.path.join(BASE, "static")
HOST, PORT = "0.0.0.0", 5000
SESSIONS = {}


def db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def hash_password(password):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120000).hex()
    return salt + "$" + digest


def verify_password(password, stored):
    try:
        salt, digest = stored.split("$", 1)
        check = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120000).hex()
        return secrets.compare_digest(check, digest)
    except Exception:
        return False


def setup_database():
    conn = db()
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        role TEXT DEFAULT 'user',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        last_login TEXT)""")
    # Add last_login to older databases created by previous versions.
    try:
        cur.execute("ALTER TABLE users ADD COLUMN last_login TEXT")
    except sqlite3.OperationalError:
        pass
    cur.execute("""CREATE TABLE IF NOT EXISTS accounts(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER UNIQUE,
        account_number TEXT,
        account_type TEXT DEFAULT 'Savings',
        balance REAL DEFAULT 0)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS transactions(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        transaction_type TEXT,
        amount REAL,
        description TEXT,
        recipient_user_id INTEGER,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    try:
        cur.execute("ALTER TABLE transactions ADD COLUMN recipient_user_id INTEGER")
    except sqlite3.OperationalError:
        pass
    cur.execute("""CREATE TABLE IF NOT EXISTS goals(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        title TEXT,
        target REAL,
        saved REAL DEFAULT 0)""")
    # Administrator credentials
    admin_email = "vijayplutus@gmail.com"
    admin_password = "vijay123"
    target = cur.execute("SELECT id FROM users WHERE email=?", (admin_email,)).fetchone()
    if target:
        admin_id = target["id"]
        cur.execute("UPDATE users SET name=?, password=?, role=? WHERE id=?",
                    ("Vijay Plutus", hash_password(admin_password), "admin", admin_id))
        # Keep the requested account as the only administrator.
        cur.execute("UPDATE users SET role='user' WHERE role='admin' AND id<>?", (admin_id,))
    else:
        old_admin = cur.execute("SELECT id FROM users WHERE role='admin' ORDER BY id LIMIT 1").fetchone()
        if old_admin:
            admin_id = old_admin["id"]
            cur.execute("UPDATE users SET name=?, email=?, password=?, role=? WHERE id=?",
                        ("Vijay Plutus", admin_email, hash_password(admin_password), "admin", admin_id))
        else:
            cur.execute("INSERT INTO users(name,email,password,role) VALUES(?,?,?,?)",
                        ("Vijay Plutus", admin_email, hash_password(admin_password), "admin"))
            admin_id = cur.lastrowid
    # Ensure the administrator has an account record.
    admin_account = cur.execute("SELECT id FROM accounts WHERE user_id=?", (admin_id,)).fetchone()
    if not admin_account:
        cur.execute("INSERT INTO accounts(user_id,account_number,balance) VALUES(?,?,?)",
                    (admin_id, "PLTADMIN001", 250000))
    conn.commit()
    conn.close()


def E(value):
    return html.escape(str(value if value is not None else ""))


def display_time(value):
    """Display SQLite UTC timestamps in India Standard Time (IST)."""
    if not value:
        return "Never"
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone(timedelta(hours=5, minutes=30))).strftime("%d %b %Y, %I:%M:%S %p")
    except Exception:
        return str(value)


def layout(title, body, user=None, active=""):
    links = []
    for path, label in [("/dashboard", "Dashboard"), ("/transactions", "Transactions"), ("/goals", "Goals")]:
        cls = "active" if active == path else ""
        links.append(f"<a class='{cls}' href='{path}'>{label}</a>")
    # Keep the Admin entry visible in the portal. Access is still protected server-side.
    cls = "active" if active == "/admin" else ""
    admin_label = "Admin" if user and user["role"] == "admin" else "Admin Login"
    links.append(f"<a class='nav-admin {cls}' href='/admin'>🔐 {admin_label}</a>")
    if user:
        links.append("<a class='nav-logout' href='/logout'>Logout</a>")
    else:
        links.append("<a href='/login'>Login</a>")
        links.append("<a class='nav-cta' href='/register'>Register</a>")

    brand = (
        "<a class='brand' href='/' aria-label='Plutus Financial Vault home'>"
        "<span class='brand-mark'><img src='/static/logo.png' alt='Plutus Financial Vault logo'></span>"
        "<span class='brand-copy'><b>PLUTUS</b><small>FINANCIAL VAULT</small></span></a>"
    )
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{E(title)} • Plutus Financial Vault</title>"
        "<link rel='icon' type='image/png' href='/static/logo.png'>"
        "<link rel='stylesheet' href='/static/style.css'></head>"
        "<body><div id='page-loader'><div class='loader-vault'><span>PL</span></div>"
        "<strong>Securing your vault</strong><small>PLUTUS FINANCIAL VAULT</small><div class='loader-line'><i></i></div></div>"
        "<header class='topbar'><div class='nav-inner'>" + brand +
        "<nav class='nav-links'>" + "".join(links) + "</nav>"
        "<button class='menu-btn' onclick='toggleMenu()' aria-label='Open menu'>☰</button>"
        "</div></header><main>" + body +
        "</main><footer><div class='footer-brand'><img src='/static/logo.png' alt='Plutus Financial Vault logo'><div><b>PLUTUS FINANCIAL VAULT</b><span>Your wealth. Fully protected.</span></div></div>"
        "<div class='footer-copy'>© 2026 PLUTUS FINANCIAL VAULT • All rights reserved.</div>"
        "<p class='footer-tech'>Educational financial portal • Python standard library • SQLite</p></footer>"
        "<script src='/static/app.js'></script></body></html>"
    )


def auth_page(register=False, error=""):
    title = "Create your vault" if register else "Welcome back"
    subtitle = "Open your personal financial vault" if register else "Sign in to continue to your secure dashboard"
    name_field = "<label>Full name<input name='name' autocomplete='name' required></label>" if register else ""
    button = "Create Secure Account" if register else "Unlock Dashboard"
    switch = (
        "Already have an account? <a href='/login'>Sign in</a>"
        if register else "New to Plutus? <a href='/register'>Create an account</a>"
    )
    alert = f"<div class='alert'>{E(error)}</div>" if error else ""
    extra = ""
    body = f"""
    <section class='auth-shell'>
      <div class='auth-art'>
        <div class='art-orbit orbit-a'></div><div class='art-orbit orbit-b'></div>
        <img src='/static/logo.png' alt='Plutus Financial Vault' class='auth-main-logo'>
        <div class='auth-chip'><span class='status-dot'></span> VAULT SYSTEM ONLINE</div>
      </div>
      <div class='auth-card panel'>
        <span class='eyebrow'>SECURE ACCESS</span><h1>{title}</h1><p class='muted'>{subtitle}</p>
        {alert}<form method='post' action='/{'register' if register else 'login'}'>
          {name_field}<label>Email address<input type='email' name='email' autocomplete='email' required></label>
          <label>Password<input type='password' name='password' minlength='6' autocomplete='current-password' required></label>
          <button class='btn btn-primary full' type='submit'><span>◈</span> {button}</button>
        </form><p class='switch'>{switch}</p>{extra}
      </div>
    </section>
    """
    return layout("Register" if register else "Login", body)


def home_page():
    body = """
    <section class='hero-section'>
      <div class='hero-copy reveal'>
        <div class='eyebrow'><span class='status-dot'></span> SECURE • SMART • SIMPLE</div>
        <h1>Your wealth.<br><span>Fully protected.</span></h1>
        <p class='hero-text'>A modern financial vault experience for accounts, transactions, savings goals and an intelligent assistant — wrapped in one consistent Plutus identity.</p>
        <div class='hero-actions'><a class='btn btn-primary' href='/register'>Open Your Vault <span>→</span></a><a class='btn btn-ghost' href='/login'>Sign In</a></div>
        <div class='trust-row'><span>◉ Local SQLite</span><span>◉ Password hashing</span><span>◉ Responsive</span></div>
      </div>
      <div class='hero-vault reveal'>
        <div class='glow'></div><div class='orbit orbit-1'></div><div class='orbit orbit-2'></div>
        <div class='vault-3d' id='heroVault'>
          <div class='vault-body'>
            <div class='vault-door' id='vaultDoor'><div class='door-logo'><img src='/static/logo.png' alt='Plutus logo'></div><div class='handle'><span></span></div><div class='bolt bolt-1'></div><div class='bolt bolt-2'></div><div class='bolt bolt-3'></div><div class='bolt bolt-4'></div></div>
            <div class='vault-side'></div><div class='vault-top'></div>
          </div>
        </div>
        <div class='vault-caption'><span class='security-dot'></span><b>3D VAULT ACTIVE</b><small>Move your pointer to rotate</small></div>
      </div>
    </section>

    <section class='security-sequence' id='securitySequence'>
      <div class='sequence-copy reveal'><span class='eyebrow'>SECURITY SEQUENCE</span><h2>Every layer has a purpose.</h2><p>Scroll through the vault sequence to activate each protection layer.</p></div>
      <div class='sequence-steps'>
        <div class='security-step active'><span>01</span><div><b>Identity</b><small>Authenticated access</small></div><i>✓</i></div>
        <div class='security-step'><span>02</span><div><b>Encryption</b><small>Protected credentials</small></div><i>✓</i></div>
        <div class='security-step'><span>03</span><div><b>Vault</b><small>Personal financial data</small></div><i>✓</i></div>
        <div class='security-step'><span>04</span><div><b>Intelligence</b><small>AI-style guidance</small></div><i>✓</i></div>
      </div>
    </section>

    <section class='feature-grid'>
      <article class='feature-card reveal'><div class='feature-icon'>▣</div><h3>Dashboard</h3><p>See balance, account information, recent activity and savings goals in one view.</p></article>
      <article class='feature-card reveal'><div class='feature-icon'>↔</div><h3>Transactions</h3><p>Record deposits and withdrawals and keep a clear local transaction history.</p></article>
      <article class='feature-card reveal'><div class='feature-icon'>◎</div><h3>Goals</h3><p>Create financial targets and watch your progress with animated indicators.</p></article>
    </section>

    <section class='ai-section reveal'>
      <div class='ai-intro'><div class='ai-orb'><span>AI</span></div><span class='eyebrow'>PLUTUS AI</span><h2>Your vault, with an assistant.</h2><p>Ask about saving, goals, transactions or your dashboard.</p><div class='ai-tags'><button onclick="quickAI('How can I save money?')">Saving</button><button onclick="quickAI('Explain my dashboard')">Dashboard</button><button onclick="quickAI('How do goals work?')">Goals</button></div></div>
      <div class='chat-card'><div class='chat-head'><span class='ai-status'></span><b>Plutus AI Assistant</b><small>Online</small></div><div id='messages' class='messages'><div class='bot-message'>Hello! I’m Plutus AI. Ask me a financial-portal question.</div></div><div class='chat-input'><input id='q' placeholder='Ask Plutus AI...' onkeydown="if(event.key==='Enter')askAI()"><button class='btn btn-primary' onclick='askAI()'>Ask</button></div></div>
    </section>
    """
    return layout("Home", body)


def current_user(handler):
    sid = handler.cookies.get("sid")
    uid = SESSIONS.get(sid)
    if not uid:
        return None
    conn = db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    conn.close()
    return user


def dashboard_page(user):
    conn = db()
    account = conn.execute("SELECT * FROM accounts WHERE user_id=?", (user["id"],)).fetchone()
    goals = conn.execute("SELECT * FROM goals WHERE user_id=? ORDER BY id DESC LIMIT 4", (user["id"],)).fetchall()

    if user["role"] == "admin":
        # ADMIN VIEW: the dashboard balance is the LIVE combined balance of
        # every regular user. The administrator's own account is intentionally
        # excluded, so a user deposit of ₹1000 immediately makes this card ₹1000.
        balance_row = conn.execute(
            "SELECT COALESCE(SUM(a.balance),0) AS total FROM accounts a JOIN users u ON u.id=a.user_id WHERE u.role='user'"
        ).fetchone()
        count_row = conn.execute("SELECT COUNT(*) AS total FROM users WHERE role='user'").fetchone()
        balance = float(balance_row["total"] or 0)
        user_count = int(count_row["total"] or 0)
        account_type = "All User Accounts"
        account_no = f"{user_count} REGISTERED USERS"
        tx = conn.execute(
            """SELECT t.*, u.name AS user_name, u.email AS user_email,
                      a.account_number AS account_number
               FROM transactions t
               JOIN users u ON u.id=t.user_id
               LEFT JOIN accounts a ON a.user_id=u.id
               WHERE u.role='user'
               ORDER BY t.id DESC LIMIT 10"""
        ).fetchall()
        tx_rows = "".join(
            f"<tr><td><span class='tx-dot {E(t['transaction_type'])}'></span>{E(t['transaction_type']).title()}</td>"
            f"<td><b>{E(t['user_name'])}</b><br><small>Account: {E(t['account_number'] or '—')}</small><br><small>{E(t['user_email'])}</small><br>{E(t['description'])}</td>"
            f"<td><b>₹{float(t['amount'] or 0):,.2f}</b></td><td><small>{E(display_time(t['created_at']))}</small></td></tr>"
            for t in tx
        ) or "<tr><td colspan='4' class='empty'>No user transactions yet.</td></tr>"
        goals = []
        goal_cards = "<div class='empty'>User financial goals are available from the Admin control center.</div>"
        page_label = "BANK OVERVIEW"
        heading = "Hello, Admin"
        subtitle = "Live overview of all registered users and their money activity."
    else:
        balance = account["balance"] if account else 0
        account_type = account["account_type"] if account else "Savings"
        account_no = account["account_number"] if account else "—"
        tx = conn.execute("SELECT * FROM transactions WHERE user_id=? ORDER BY id DESC LIMIT 6", (user["id"],)).fetchall()
        tx_rows = "".join(
            f"<tr><td><span class='tx-dot {E(t['transaction_type'])}'></span>{E(t['transaction_type']).title()}</td><td>{E(t['description'])}</td><td>₹{t['amount']:,.2f}</td><td><small>{E(display_time(t['created_at']))}</small></td></tr>"
            for t in tx
        ) or "<tr><td colspan='4' class='empty'>No transactions yet.</td></tr>"
        goal_cards = "".join(
            f"<div class='goal-item'><div><b>{E(g['title'])}</b><span>₹{g['saved']:,.0f} / ₹{g['target']:,.0f}</span></div><div class='progress'><i style='width:{min(100, (g['saved']/g['target']*100) if g['target'] else 0):.1f}%'></i></div></div>"
            for g in goals
        ) or "<div class='empty'>No goals yet. Create your first target.</div>"
        page_label = "PERSONAL VAULT"
        heading = f"Hello, {E(user['name'])} <span class='accent'>✦</span>"
        subtitle = "Your financial overview is ready."
    conn.close()
    body = f"""
    <section class='page-head container reveal'><div><span class='eyebrow'>{page_label}</span><h1>{heading}</h1><p class='muted'>{subtitle}</p></div><div class='secure-badge'><span class='status-dot'></span> VAULT SECURED</div></section>
    <section class='container stats-grid'>
      <div class='stat-card primary-stat'><div class='stat-icon'>₹</div><small>{'CURRENT BALANCE • ALL USERS' if user['role']=='admin' else 'Available Balance'}</small><strong>₹{balance:,.2f}</strong><span>{'Live sum of every user current balance' if user['role']=='admin' else 'Current local balance'}</span></div>
      <div class='stat-card'><div class='stat-icon'>👥</div><small>{'TOTAL USERS' if user['role']=='admin' else 'Account Type'}</small><strong>{user_count if user['role']=='admin' else E(account_type)}</strong><span>{'Registered user accounts' if user['role']=='admin' else E(account_no)}</span></div>
      <div class='stat-card'><div class='stat-icon'>✓</div><small>Security Status</small><strong>Protected</strong><span>Session authenticated</span></div>
    </section>
    <section class='container dashboard-grid'>
      <div class='panel table-panel'><div class='panel-head'><div><span class='eyebrow'>ACTIVITY</span><h2>{'Recent User Transactions' if user['role']=='admin' else 'Recent Transactions'}</h2></div><a href={'/admin' if user['role']=='admin' else '/transactions'}>View all →</a></div><div class='table-wrap'><table><thead><tr><th>Type</th><th>Description</th><th>Amount</th><th>Date &amp; Time (IST)</th></tr></thead><tbody>{tx_rows}</tbody></table></div></div>
      <div class='panel goals-panel'><div class='panel-head'><div><span class='eyebrow'>TARGETS</span><h2>Financial Goals</h2></div><a href='/goals'>Manage →</a></div>{goal_cards}</div>
    </section>
    <section class='container mini-ai'><div class='mini-ai-icon'>AI</div><div><span class='eyebrow'>PLUTUS AI</span><h2>Need a quick explanation?</h2><p class='muted'>Use the AI assistant on the home page for saving, dashboard and goal guidance.</p></div><a class='btn btn-primary' href='/'>Open AI →</a></section>
    """
    return layout("Dashboard", body, user, "/dashboard")


def transactions_page(user, query):
    conn = db()
    account = conn.execute("SELECT * FROM accounts WHERE user_id=?", (user["id"],)).fetchone()
    txs = conn.execute("""SELECT t.*, u.name AS recipient_name, u.email AS recipient_email
                         FROM transactions t LEFT JOIN users u ON u.id=t.recipient_user_id
                         WHERE t.user_id=? ORDER BY t.id DESC""", (user["id"],)).fetchall()
    recipients = conn.execute("SELECT id,name,email FROM users WHERE id<>? AND role='user' ORDER BY name", (user["id"],)).fetchall()
    conn.close()
    msg = query.get("msg", [""])[0]
    balance = account["balance"] if account else 0
    rows = "".join(
        f"<tr><td>{E(display_time(t['created_at']))}</td><td><span class='tx-dot {E(t['transaction_type'])}'></span>{E(t['transaction_type']).title()}</td><td>₹{t['amount']:,.2f}</td><td>{E(t['description'])}"
        f"{('<br><small>To: '+E(t['recipient_name'])+' ('+E(t['recipient_email'])+')</small>') if t['recipient_user_id'] else ''}</td></tr>"
        for t in txs
    ) or "<tr><td colspan='4' class='empty'>No transactions yet.</td></tr>"
    recipient_options = "".join(f"<option value='{r['id']}'>{E(r['name'])} — {E(r['email'])}</option>" for r in recipients)
    alert = f"<div class='alert'>{E(msg)}</div>" if msg else ""
    body = f"""
    <section class='container page-head reveal'><div><span class='eyebrow'>MONEY FLOW</span><h1>Transactions</h1><p class='muted'>Current balance: <b class='accent'>₹{balance:,.2f}</b> • All transaction times are shown in IST.</p></div></section>
    <section class='container dashboard-grid'>
      <div class='panel form-panel'><span class='eyebrow'>NEW ACTIVITY</span><h2>Add Money Activity</h2>{alert}
      <form method='post'>
      <label>Type<select name='type' id='txType' onchange='toggleTransfer()'><option value='deposit'>Deposit</option><option value='withdraw'>Withdraw</option><option value='transfer'>Transfer</option></select></label>
      <div id='transferBox' style='display:none'><label>Transfer to<select name='recipient_id'><option value=''>Select user</option>{recipient_options}</select></label></div>
      <label>Amount<input type='number' name='amount' min='0.01' step='0.01' placeholder='0.00' required></label>
      <label>Description<input name='description' placeholder='e.g. Salary / Shopping / Transfer' required></label>
      <button class='btn btn-primary full' type='submit'>Save Transaction →</button></form></div>
      <div class='panel table-panel'><div class='panel-head'><div><span class='eyebrow'>HISTORY</span><h2>All Transactions</h2></div></div><div class='table-wrap'><table><thead><tr><th>Date &amp; Time (IST)</th><th>Type</th><th>Amount</th><th>Description</th></tr></thead><tbody>{rows}</tbody></table></div></div>
    </section>
    """
    return layout("Transactions", body, user, "/transactions")


def goals_page(user):
    conn = db()
    goals = conn.execute("SELECT * FROM goals WHERE user_id=? ORDER BY id DESC", (user["id"],)).fetchall()
    conn.close()
    cards = "".join(
        f"<div class='goal-large'><div class='goal-top'><div><span class='eyebrow'>GOAL</span><h3>{E(g['title'])}</h3></div><b>{min(100, (g['saved']/g['target']*100) if g['target'] else 0):.0f}%</b></div><div class='progress large'><i style='width:{min(100, (g['saved']/g['target']*100) if g['target'] else 0):.1f}%'></i></div><div class='goal-numbers'><span>Saved ₹{g['saved']:,.0f}</span><span>Target ₹{g['target']:,.0f}</span></div></div>"
        for g in goals
    ) or "<div class='empty'>No goals yet. Add one to start tracking.</div>"
    body = f"""
    <section class='container page-head reveal'><div><span class='eyebrow'>FUTURE PLANS</span><h1>Financial Goals</h1><p class='muted'>Turn a target into a visible progress path.</p></div></section>
    <section class='container dashboard-grid'><div class='panel form-panel'><span class='eyebrow'>CREATE TARGET</span><h2>New Goal</h2><form method='post'><label>Goal title<input name='title' placeholder='Emergency fund' required></label><label>Target amount<input name='target' type='number' min='1' step='0.01' placeholder='50000' required></label><button class='btn btn-primary full' type='submit'>Add Goal →</button></form></div><div class='panel goals-panel'><div class='panel-head'><div><span class='eyebrow'>YOUR TARGETS</span><h2>Progress</h2></div></div>{cards}</div></section>
    """
    return layout("Goals", body, user, "/goals")


def admin_page(user):
    conn = db()
    users = conn.execute(
        """SELECT u.*, a.balance, a.account_number, a.account_type,
                  COALESCE((SELECT SUM(amount) FROM transactions WHERE user_id=u.id AND transaction_type='deposit'),0) AS total_deposits,
                  COALESCE((SELECT SUM(amount) FROM transactions WHERE user_id=u.id AND transaction_type='withdraw'),0) AS total_withdrawals,
                  COALESCE((SELECT SUM(amount) FROM transactions WHERE user_id=u.id AND transaction_type='transfer'),0) AS total_transfers_sent,
                  (SELECT COUNT(*) FROM transactions WHERE user_id=u.id) AS transaction_count,
                  (SELECT created_at FROM transactions WHERE user_id=u.id AND transaction_type='deposit' ORDER BY id DESC LIMIT 1) AS last_deposit,
                  (SELECT created_at FROM transactions WHERE user_id=u.id AND transaction_type='withdraw' ORDER BY id DESC LIMIT 1) AS last_withdraw,
                  (SELECT created_at FROM transactions WHERE user_id=u.id AND transaction_type='transfer' ORDER BY id DESC LIMIT 1) AS last_transfer
           FROM users u LEFT JOIN accounts a ON a.user_id=u.id
           WHERE u.role='user'
           ORDER BY u.id DESC"""
    ).fetchall()

    all_transactions = conn.execute(
        """SELECT t.*, u.name, u.email,
                  ru.name AS recipient_name, ru.email AS recipient_email
           FROM transactions t
           JOIN users u ON u.id=t.user_id
           LEFT JOIN users ru ON ru.id=t.recipient_user_id
           WHERE u.role='user'
           ORDER BY t.id DESC LIMIT 200"""
    ).fetchall()

    # Bank-style totals for registered users only. The admin's own account is separate.
    totals = conn.execute(
        """SELECT
             (SELECT COALESCE(SUM(a.balance),0) FROM accounts a JOIN users u ON u.id=a.user_id WHERE u.role='user') AS user_funds,
             (SELECT COALESCE(SUM(t.amount),0) FROM transactions t JOIN users u ON u.id=t.user_id WHERE u.role='user' AND t.transaction_type='deposit') AS deposits,
             (SELECT COALESCE(SUM(t.amount),0) FROM transactions t JOIN users u ON u.id=t.user_id WHERE u.role='user' AND t.transaction_type='withdraw') AS withdrawals,
             (SELECT COALESCE(SUM(t.amount),0) FROM transactions t JOIN users u ON u.id=t.user_id WHERE u.role='user' AND t.transaction_type='transfer') AS transfers"""
    ).fetchone()
    conn.close()

    active_ids = set(SESSIONS.values())
    row_parts = []
    regular_users = 0
    logged_in_now = 0
    for x in users:
        if x["role"] == "user":
            regular_users += 1
        is_online = x["id"] in active_ids
        if x["role"] == "user" and is_online:
            logged_in_now += 1
        status_class = "online" if is_online else "offline"
        status_text = "Logged in now" if is_online else "Offline"
        balance = float(x["balance"] or 0)
        account_number = E(x["account_number"] or ("PLT" + str(100000 + x["id"])))
        account_type = E(x["account_type"] or "Savings")
        deposited = float(x["total_deposits"] or 0)
        withdrawn = float(x["total_withdrawals"] or 0)
        transfers_sent = float(x["total_transfers_sent"] or 0)
        net_total = deposited - withdrawn - transfers_sent
        role_label = "ADMIN" if x["role"] == "admin" else "USER"
        row_parts.append(
            f"<tr>"
            f"<td><div class='user-cell'><div class='user-avatar'>{E((x['name'] or 'U')[:1]).upper()}</div>"
            f"<div><b>{E(x['name'])}</b><small>User ID #{x['id']}</small></div></div></td>"
            f"<td><b>{E(x['email'])}</b><small>Created: {E(display_time(x['created_at']))}</small></td>"
            f"<td><span class='role'>{role_label}</span></td>"
            f"<td><span class='login-status {status_class}'><i></i>{status_text}</span>"
            f"<small class='last-login'>Last login: {E(display_time(x['last_login']))}</small></td>"
            f"<td><div class='account-main'><b>₹{balance:,.2f}</b><small>{account_number} • {account_type}</small></div>"
            f"<div class='money-mini'><span>Deposited ₹{deposited:,.2f}</span><span>Withdrawn ₹{withdrawn:,.2f}</span></div>"
            f"<div class='money-mini'><span>Transfer out ₹{transfers_sent:,.2f}</span><span>Net ₹{net_total:,.2f}</span></div>"
            f"<div class='admin-times'><span>Deposit: {E(display_time(x['last_deposit']))}</span><span>Withdraw: {E(display_time(x['last_withdraw']))}</span><span>Transfer: {E(display_time(x['last_transfer']))}</span></div></td>"
            f"<td><details class='edit-details'><summary>Edit User Details</summary><form method='post' action='/admin/{x['id']}' class='admin-edit-form'>"
            f"<label>Name<input name='name' value='{E(x['name'])}' required></label>"
            f"<label>Email ID<input name='email' type='email' value='{E(x['email'])}' required></label>"
            f"<label>Account No.<input name='account_number' value='{account_number}' required></label>"
            f"<label>Account Type<input name='account_type' value='{account_type}' required></label>"
            f"<label>Balance<input name='balance' type='number' step='0.01' min='0' value='{balance:.2f}' required></label>"
            f"<button class='btn btn-small' type='submit'>Save User Details</button></form></details></td></tr>"
        )
    rows = "".join(row_parts) or "<tr><td colspan='6' class='empty'>No users registered yet.</td></tr>"

    money_parts = []
    for t in all_transactions:
        typ = E(t['transaction_type']).title()
        recipient = ""
        if t['transaction_type'] == 'transfer' and t['recipient_name']:
            recipient = f"<small>To: {E(t['recipient_name'])} ({E(t['recipient_email'])})</small>"
        money_parts.append(
            f"<tr><td><b>{E(display_time(t['created_at']))}</b></td>"
            f"<td><b>{E(t['name'])}</b><small>{E(t['email'])}</small></td>"
            f"<td><span class='tx-dot {E(t['transaction_type'])}'></span>{typ}</td>"
            f"<td><b>₹{float(t['amount'] or 0):,.2f}</b>{recipient}</td>"
            f"<td>{E(t['description'])}</td></tr>"
        )
    money_rows = "".join(money_parts) or "<tr><td colspan='5' class='empty'>No user transactions recorded yet.</td></tr>"

    admin_count = sum(1 for x in users if x["role"] == "admin")
    user_funds = float(totals["user_funds"] or 0)
    total_deposits = float(totals["deposits"] or 0)
    total_withdrawals = float(totals["withdrawals"] or 0)
    total_transfers = float(totals["transfers"] or 0)

    body = f"""
    <section class='container page-head reveal'>
      <div><span class='eyebrow'>ADMIN CONTROL CENTER</span><h1>Bank &amp; User Management</h1>
      <p class='muted'>The administrator sees the total user funds and each user's complete account and transaction activity.</p></div>
      <div class='admin-key'>🔐 ADMIN</div>
    </section>
    <section class='container admin-stats'>
      <div class='admin-stat admin-money'><span class='stat-icon'>🏦</span><div><small>TOTAL USER FUNDS</small><strong>₹{user_funds:,.2f}</strong><em>Current balances of all users</em></div></div>
      <div class='admin-stat'><span class='stat-icon'>↓</span><div><small>TOTAL DEPOSITS</small><strong>₹{total_deposits:,.2f}</strong></div></div>
      <div class='admin-stat'><span class='stat-icon'>↑</span><div><small>TOTAL WITHDRAWALS</small><strong>₹{total_withdrawals:,.2f}</strong></div></div>
      <div class='admin-stat'><span class='stat-icon'>⇄</span><div><small>TRANSFERRED</small><strong>₹{total_transfers:,.2f}</strong></div></div>
    </section>
    <section class='container admin-stats'>
      <div class='admin-stat'><span class='stat-icon'>👥</span><div><small>REGISTERED USERS</small><strong>{regular_users}</strong></div></div>
      <div class='admin-stat'><span class='stat-icon'>●</span><div><small>USERS ONLINE</small><strong>{logged_in_now}</strong></div></div>
      <div class='admin-stat'><span class='stat-icon'>✉</span><div><small>USER EMAILS</small><strong>{regular_users}</strong></div></div>
      <div class='admin-stat'><span class='stat-icon'>🔐</span><div><small>ADMIN ACCOUNTS</small><strong>{admin_count}</strong></div></div>
    </section>
    <section class='container'>
      <div class='panel table-panel'>
        <div class='panel-head'><div><span class='eyebrow'>REGISTERED USERS</span><h2>Users, Amounts &amp; Account Details</h2></div><span class='count-pill'>{regular_users} users</span></div>
        <p class='admin-note'><b>LIVE BANK VIEW:</b> If any user deposits ₹1,000, the Admin Dashboard <b>Current Balance • All Users</b> immediately becomes ₹1,000 (or the combined current balance of all users). The Admin account's separate fixed balance is not used for this total. Each user below shows name, email, account number, current balance, deposit/withdraw/transfer totals and the latest date &amp; time.</p>
        <div class='table-wrap'><table class='admin-table'><thead><tr><th>User</th><th>Email ID</th><th>Role</th><th>Login Activity</th><th>Money &amp; Transaction Times</th><th>Change User Details</th></tr></thead><tbody>{rows}</tbody></table></div>
      </div>
    </section>
    <section class='container'>
      <div class='panel table-panel'>
        <div class='panel-head'><div><span class='eyebrow'>MONEY ACTIVITY</span><h2>All User Deposits, Withdrawals &amp; Transfers</h2></div><span class='count-pill'>Latest 200</span></div>
        <p class='admin-note'><b>USER TRANSACTION HISTORY:</b> Every deposit, withdrawal and transfer made by users is listed with user name, account number, exact amount, description and date &amp; time in IST.</p>
        <div class='table-wrap'><table class='admin-table'><thead><tr><th>Date &amp; Time (IST)</th><th>User</th><th>Type</th><th>Amount</th><th>Description</th></tr></thead><tbody>{money_rows}</tbody></table></div>
      </div>
    </section>
    <section class='container'>
      <div class='panel admin-settings'>
        <div class='panel-head'><div><span class='eyebrow'>ADMIN SECURITY</span><h2>Administrator Login Settings</h2></div></div>
        <p class='muted'>Current administrator email: <b class='accent'>{E(user['email'])}</b>. Change it below if needed.</p>
        <form method='post' action='/admin-settings' class='settings-form'>
          <label>Admin email<input type='email' name='email' value='{E(user['email'])}' required></label>
          <label>New password<input type='password' name='password' minlength='6' placeholder='Enter new password (optional)'></label>
          <button class='btn btn-primary' type='submit'>Update Admin Login</button>
        </form>
      </div>
    </section>
    """
    return layout("Admin", body, user, "/admin")

def access_denied_page(user):
    body = f"""
    <section class='container page-head reveal'>
      <div><span class='eyebrow'>ADMIN AREA</span><h1>Admin access required</h1>
      <p class='muted'>Hello, {E(user['name'])}. This area is available only to administrator accounts.</p></div>
      <div class='admin-key'>🔒 PROTECTED</div>
    </section>
    <section class='container'>
      <div class='panel access-panel'>
        <div class='access-icon'>🔐</div>
        <h2>Administrator Login</h2>
        <p>Sign out and sign in with the administrator account to view registered users, email IDs, login status, last login time and account details.</p>
        <a class='btn btn-primary' href='/logout'>Go to Admin Login</a>
      </div>
    </section>
    """
    return layout("Admin Access", body, user, "/admin")


class Handler(BaseHTTPRequestHandler):
    def parse_request(self):
        # BaseHTTPRequestHandler must parse the HTTP request first.
        # Without this call, self.path does not exist and the browser can
        # receive ERR_EMPTY_RESPONSE.
        if not super().parse_request():
            return False
        parsed = urlparse(self.path)
        self.path_only = parsed.path
        self.query = parse_qs(parsed.query)
        self.cookies = {}
        for part in self.headers.get("Cookie", "").split(";"):
            if "=" in part:
                key, value = part.strip().split("=", 1)
                self.cookies[key] = value
        return True

    def form_data(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8", "ignore")
        return {k: v[0] for k, v in parse_qs(raw).items()}

    def send_html(self, content, code=200, headers=None):
        headers = headers or []
        data = content.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        for key, value in headers:
            self.send_header(key, value)
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            return

    def redirect(self, location, headers=None):
        headers = headers or []
        self.send_response(302)
        self.send_header("Location", location)
        for key, value in headers:
            self.send_header(key, value)
        self.end_headers()

    def do_GET(self):
        if self.path_only == "/favicon.ico":
            path = os.path.join(STATIC, "logo.png")
            data = open(path, "rb").read()
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if self.path_only.startswith("/static/"):
            relative = self.path_only[8:].replace("..", "")
            path = os.path.join(STATIC, relative)
            if not os.path.isfile(path):
                self.send_html("Not found", 404)
                return
            data = open(path, "rb").read()
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(path)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        user = current_user(self)
        if self.path_only == "/":
            return self.send_html(home_page())
        if self.path_only == "/login":
            return self.send_html(auth_page(False))
        if self.path_only == "/register":
            return self.send_html(auth_page(True))
        if self.path_only == "/logout":
            SESSIONS.pop(self.cookies.get("sid"), None)
            return self.redirect("/")
        if self.path_only == "/dashboard":
            return self.send_html(dashboard_page(user)) if user else self.redirect("/login")
        if self.path_only == "/transactions":
            return self.send_html(transactions_page(user, self.query)) if user else self.redirect("/login")
        if self.path_only == "/goals":
            return self.send_html(goals_page(user)) if user else self.redirect("/login")
        if self.path_only == "/admin":
            if not user:
                return self.redirect("/login")
            if user["role"] == "admin":
                return self.send_html(admin_page(user))
            return self.send_html(access_denied_page(user), 403)
        self.send_html("<h1>404</h1><p>Page not found.</p>", 404)

    def do_POST(self):
        data = self.form_data()
        user = current_user(self)

        if self.path_only == "/login":
            email = data.get("email", "").strip().lower()
            password = data.get("password", "")
            conn = db()
            found = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
            conn.close()
            if found and verify_password(password, found["password"]):
                conn = db()
                conn.execute("UPDATE users SET last_login=CURRENT_TIMESTAMP WHERE id=?", (found["id"],))
                conn.commit()
                conn.close()
                sid = secrets.token_urlsafe(24)
                SESSIONS[sid] = found["id"]
                return self.redirect("/dashboard", [("Set-Cookie", f"sid={sid}; HttpOnly; SameSite=Lax; Path=/")])
            return self.send_html(auth_page(False, "Invalid email or password."))

        if self.path_only == "/register":
            name = data.get("name", "").strip()
            email = data.get("email", "").strip().lower()
            password = data.get("password", "")
            if len(name) < 2 or len(password) < 6 or "@" not in email:
                return self.send_html(auth_page(True, "Please enter a valid name, email and password (6+ characters)."))
            try:
                conn = db()
                cur = conn.cursor()
                cur.execute("INSERT INTO users(name,email,password) VALUES(?,?,?)", (name, email, hash_password(password)))
                uid = cur.lastrowid
                cur.execute("INSERT INTO accounts(user_id,account_number,account_type,balance) VALUES(?,?,?,?)", (uid, "PLT" + str(100000 + uid), "Savings", 0))
                conn.commit()
                conn.close()
                return self.redirect("/login")
            except sqlite3.IntegrityError:
                return self.send_html(auth_page(True, "That email is already registered."))

        if not user:
            return self.redirect("/login")

        if self.path_only == "/transactions":
            try:
                amount = float(data.get("amount", "0"))
            except ValueError:
                amount = 0
            kind = data.get("type", "deposit").lower()
            description = data.get("description", "Transaction").strip() or "Transaction"
            recipient_id = None
            conn = db()
            account = conn.execute("SELECT * FROM accounts WHERE user_id=?", (user["id"],)).fetchone()
            if amount <= 0 or not account or kind not in ("deposit", "withdraw", "transfer"):
                conn.close()
                return self.redirect("/transactions?msg=Invalid transaction details")
            if kind == "transfer":
                try:
                    recipient_id = int(data.get("recipient_id", "0"))
                except ValueError:
                    recipient_id = 0
                recipient = conn.execute("SELECT u.id,u.name,a.id AS account_id,a.balance FROM users u JOIN accounts a ON a.user_id=u.id WHERE u.id=? AND u.role='user'", (recipient_id,)).fetchone()
                if not recipient or recipient_id == user["id"] or amount > account["balance"]:
                    conn.close()
                    return self.redirect("/transactions?msg=Invalid recipient or insufficient balance")
                sender_new = account["balance"] - amount
                recipient_new = recipient["balance"] + amount
                conn.execute("UPDATE accounts SET balance=? WHERE id=?", (sender_new, account["id"]))
                conn.execute("UPDATE accounts SET balance=? WHERE id=?", (recipient_new, recipient["account_id"]))
                conn.execute("INSERT INTO transactions(user_id,transaction_type,amount,description,recipient_user_id) VALUES(?,?,?,?,?)", (user["id"], "transfer", amount, description, recipient_id))
                conn.execute("INSERT INTO transactions(user_id,transaction_type,amount,description,recipient_user_id) VALUES(?,?,?,?,?)", (recipient_id, "deposit", amount, "Transfer received: " + description, user["id"]))
            else:
                if kind == "withdraw" and amount > account["balance"]:
                    conn.close()
                    return self.redirect("/transactions?msg=Insufficient balance")
                new_balance = account["balance"] + amount if kind == "deposit" else account["balance"] - amount
                conn.execute("UPDATE accounts SET balance=? WHERE id=?", (new_balance, account["id"]))
                conn.execute("INSERT INTO transactions(user_id,transaction_type,amount,description) VALUES(?,?,?,?)", (user["id"], kind, amount, description))
            conn.commit()
            conn.close()
            return self.redirect("/transactions?msg=Transaction saved successfully")

        if self.path_only == "/goals":
            try:
                target = float(data.get("target", "0"))
            except ValueError:
                target = 0
            title = data.get("title", "Goal").strip() or "Goal"
            if target <= 0:
                return self.redirect("/goals")
            conn = db()
            conn.execute("INSERT INTO goals(user_id,title,target,saved) VALUES(?,?,?,0)", (user["id"], title, target))
            conn.commit()
            conn.close()
            return self.redirect("/goals")

        if self.path_only == "/admin-settings" and user["role"] == "admin":
            new_email = data.get("email", "").strip().lower()
            new_password = data.get("password", "")
            if "@" not in new_email:
                return self.redirect("/admin")
            conn = db()
            try:
                if new_password:
                    if len(new_password) < 6:
                        conn.close()
                        return self.redirect("/admin")
                    conn.execute("UPDATE users SET email=?, password=? WHERE id=?",
                                 (new_email, hash_password(new_password), user["id"]))
                else:
                    conn.execute("UPDATE users SET email=? WHERE id=?", (new_email, user["id"]))
                conn.commit()
            except sqlite3.IntegrityError:
                pass
            finally:
                conn.close()
            return self.redirect("/admin")

        if self.path_only.startswith("/admin/") and user["role"] == "admin":
            try:
                uid = int(self.path_only.rsplit("/", 1)[-1])
                balance = max(0, float(data.get("balance", "0")))
            except (ValueError, TypeError):
                return self.redirect("/admin")
            name = data.get("name", "").strip()
            email = data.get("email", "").strip().lower()
            account_number = data.get("account_number", "").strip()
            account_type = data.get("account_type", "Savings").strip() or "Savings"
            if len(name) < 2 or "@" not in email or not account_number:
                return self.redirect("/admin")
            conn = db()
            try:
                conn.execute("UPDATE users SET name=?, email=? WHERE id=?", (name, email, uid))
                account = conn.execute("SELECT id FROM accounts WHERE user_id=?", (uid,)).fetchone()
                if account:
                    old_row = conn.execute("SELECT balance FROM accounts WHERE id=?", (account["id"],)).fetchone()
                    old_balance = float(old_row["balance"] or 0) if old_row else 0.0
                    conn.execute("UPDATE accounts SET account_number=?, account_type=?, balance=? WHERE id=?",
                                 (account_number, account_type, balance, account["id"]))
                    # When Admin changes a user's balance, record the change as a dated
                    # deposit/withdrawal so the amount and exact IST time appear in
                    # both the user's transaction history and Admin Money Activity.
                    difference = round(balance - old_balance, 2)
                    if difference > 0.00:
                        conn.execute(
                            "INSERT INTO transactions(user_id,transaction_type,amount,description) VALUES(?,?,?,?)",
                            (uid, "deposit", difference, "Admin balance credit")
                        )
                    elif difference < 0.00:
                        conn.execute(
                            "INSERT INTO transactions(user_id,transaction_type,amount,description) VALUES(?,?,?,?)",
                            (uid, "withdraw", abs(difference), "Admin balance adjustment")
                        )
                else:
                    conn.execute("INSERT INTO accounts(user_id,account_number,account_type,balance) VALUES(?,?,?,?)",
                                 (uid, account_number, account_type, balance))
                    if balance > 0.00:
                        conn.execute(
                            "INSERT INTO transactions(user_id,transaction_type,amount,description) VALUES(?,?,?,?)",
                            (uid, "deposit", balance, "Initial balance added by Admin")
                        )
                conn.commit()
            except sqlite3.IntegrityError:
                pass
            finally:
                conn.close()
            return self.redirect("/admin")

        self.send_html("Not found", 404)

    def log_message(self, fmt, *args):
        print("%s - - [%s] %s" % (self.address_string(), self.log_date_time_string(), fmt % args))


def main():
    setup_database()
    import socket
    try:
        local_ip = socket.gethostbyname(socket.gethostname())
    except Exception:
        local_ip = "YOUR-PC-IP"
    print("\n" + "=" * 70)
    print("  PLUTUS FINANCIAL VAULT • PYTHON IDLE EDITION")
    print("  PC:     http://127.0.0.1:5000")
    print(f"  MOBILE: http://{local_ip}:5000")
    print("  Keep your phone and PC on the same Wi-Fi for mobile access.")
    print("  If Windows Firewall asks, allow Python on Private networks.")
    print("=" * 70 + "\n")
    webbrowser.open("http://127.0.0.1:5000")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
