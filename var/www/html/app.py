from flask import Flask, request, make_response
from werkzeug.security import generate_password_hash, check_password_hash
import pymysql
import secrets
import time
import math
import sys
import logging

MAX_FLOAT = sys.float_info.max # ~1.7976931348623157e+308

app = Flask(__name__)

logging.basicConfig(filename='/var/www/html/response_log.txt', level=logging.INFO)

@app.after_request
def log_response(response):
    try:
        # --- START IP CHECK ---
        # Get the real IP from behind the proxy
        if request.headers.get('X-Forwarded-For'):
            real_ip = request.headers.getlist('X-Forwarded-For')[0]
        else:
            real_ip = request.remote_addr
        # --- END IP CHECK ---

        # Get the response body
        body = response.get_data(as_text=True)

        # Get the request details (now with IP)
        request_details = f"REQUEST from {real_ip}: {request.method} {request.full_path}"
        response_details = f"RESPONSE: {body.strip()}"

        # Write both to the file
        app.logger.info(f"{request_details}\n")
        app.logger.info(f"{response_details}\n---\n") # Add a separator

    except Exception as e:
        app.logger.info(f"LOGGER FAILED: {str(e)}\n")

    return response

app.config['SESSION_COOKIE_NAME'] = 'session'
app.config['SESSION_COOKIE_DOMAIN'] = 'blueserver'
app.config['SESSION_COOKIE_PATH'] = '/'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SECURE'] = True

DB_HOST = "localhost"
DB_USER = "root"
DB_PASS = "root"
DB_NAME = "bank"

def connect_db():
    return pymysql.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASS,
        db=DB_NAME,
        cursorclass=pymysql.cursors.DictCursor
    )

# -------------------------------------------------------
# REGISTER
# -------------------------------------------------------
@app.route('/register', methods=['GET'])
def register():
    user = request.args.get('user', '')
    passwd = request.args.get('pass', '')

    if not user or not passwd:
        return "Error: must provide ?user=USER&pass=PASS\n"

    try:
        conn = connect_db()
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE name=%s", (user,))
            if cur.fetchone():
                return f"Error: user {user} already exists\n"

            # Hash and salt the password
            hashed = generate_password_hash(passwd)

            cur.execute("INSERT INTO users (name, pass, balance) VALUES (%s, %s, 0)", (user, hashed))
            conn.commit()
        conn.close()
        return f"Account created for user {user}\n"
    except Exception as e:
        return f"Database error: {e}\n"

# -------------------------------------------------------
# LOGIN
# -------------------------------------------------------

@app.route('/login', methods=['GET'])
def login():
    user = request.args.get('user', '')
    passwd = request.args.get('pass', '')
    if not user or not passwd:
        return "Error: must provide ?user=USER&pass=PASS\n"

    conn = connect_db()
    with conn.cursor() as cur:
        # Get password hash
        cur.execute("SELECT pass FROM users WHERE name=%s", (user,))
        row = cur.fetchone()

        # --- START OF PASSWORD HASH FIX ---
        # (This is the fix from before, make sure it's still here)
        if not row:
            conn.close()
            return "Error: invalid username or password\n"

        db_pass = row['pass']
        is_hash = '$' in db_pass or ':' in db_pass

        if is_hash:
            if not check_password_hash(db_pass, passwd):
                conn.close()
                return "Error: invalid username or password\n"
        else:
            if db_pass != passwd:
                conn.close()
                return "Error: invalid username or password\n"
            else:
                new_hash = generate_password_hash(passwd)
                cur.execute("UPDATE users SET pass=%s WHERE name=%s", (new_hash, user))
        # --- END OF PASSWORD HASH FIX ---


        # --- START OF NEW LOGIN FIX ---
        #
        # This is the new logic. Instead of checking for old sessions,
        # we just invalidate all of them. This logs the user
        # out from everywhere else and fixes any "stuck" accounts.
        #
        cur.execute("UPDATE sessions SET valid=FALSE WHERE username=%s", (user,))
        #
        # --- END OF NEW LOGIN FIX ---


        # Otherwise create a new session
        session_id = secrets.token_hex(32)

        # Get the real IP from behind the proxy
        if request.headers.get('X-Forwarded-For'):
            real_ip = request.headers.getlist('X-Forwarded-For')[0]
        else:
            real_ip = request.remote_addr

        cur.execute("""
            INSERT INTO sessions (id, username, valid, ip, user_agent, last_used)
            VALUES (%s, %s, TRUE, %s, %s, NOW())
        """, (session_id, user, real_ip, request.headers.get('User-Agent')))

        conn.commit() # This commits the new session AND the new hash/logout
    conn.close()

    resp = make_response(f"Login successful for {user}\n")
    resp.set_cookie('session_id', session_id, httponly=True, secure=True, samesite='Strict', path='/')
    return resp

# -------------------------------------------------------
# MANAGE
# -------------------------------------------------------
@app.route('/manage', methods=['GET'])
def manage():
    session_id = request.cookies.get('session_id')
    if not session_id:
        return "Error: not logged in\n"

    try:
        conn = connect_db()
        with conn.cursor() as cur:

            # This is the fix that validates the session without checking the IP
            cur.execute("""
                SELECT username, last_used
                FROM sessions
                WHERE id=%s AND valid=TRUE
                  AND last_used > NOW() - INTERVAL 15 MINUTE
            """, (session_id,))

            row = cur.fetchone()
            if not row:
                return "Error: session expired or invalid. Please log in again.\n"
            user = row['username']

            cur.execute("UPDATE sessions SET last_used=NOW() WHERE id=%s", (session_id,))

            action = request.args.get('action', '').lower()
            amount = request.args.get('amount', '')

            cur.execute("SELECT balance FROM users WHERE name=%s", (user,))
            row = cur.fetchone()
            if not row:
                return "Error: user not found\n"

            # --- LOGIC STILL USES FLOATS (This is safe) ---
            balance = float(row['balance'])

            if action == "deposit":
                if not amount:
                    return "Error: must specify amount\n"
                try:
                    amt = float(amount)
                except ValueError:
                    return "Error: amount must be numeric\n"

                if not math.isfinite(amt) or amt < 0:
                    return "Error: invalid amount\n"
                if amt > MAX_FLOAT:
                    return "Error: amount exceeds maximum allowed\n"
                if balance + amt > MAX_FLOAT:
                    return "Error: balance overflow\n"

                balance += amt
                cur.execute("UPDATE users SET balance=%s WHERE name=%s", (balance, user))

                # --- START OF FIX: Cast to int() for the response string ---
                msg = f"Deposited {int(amt)}. balance={int(balance)}\n"

            elif action == "withdraw":
                if not amount:
                    return "Error: must specify amount\n"
                try:
                    amt = float(amount)
                except ValueError:
                    return "Error: amount must be numeric\n"

                if not math.isfinite(amt) or amt <= 0:
                    return "Error: invalid amount\n"
                if amt > MAX_FLOAT:
                    return "Error: amount exceeds maximum allowed\n"

                if amt > balance:
                    # Cast to int() for the response string
                    msg = f"Error: insufficient funds. balance={int(balance)}\n"
                else:
                    balance -= amt
                    cur.execute("UPDATE users SET balance=%s WHERE name=%s", (balance, user))
                    # Cast to int() for the response string
                    msg = f"Withdrew {int(amt)}. balance={int(balance)}\n"

            elif action == "balance":
                # Cast to int() for the response string
                msg = f"balance={int(balance)}\n"
            # --- END OF FIX ---

            elif action == "close":
                cur.execute("DELETE FROM users WHERE name=%s", (user,))
                msg = f"Account for {user} closed.\n"
            else:
                msg = "Error: invalid action\n"

            conn.commit()
            return msg

    except Exception as e:
        return f"Database error: {e}\n"
    finally:
        if 'conn' in locals() and conn:
            conn.close()

# -------------------------------------------------------
# LOGOUT
# -------------------------------------------------------
@app.route('/logout', methods=['GET'])
def logout():
    session_id = request.cookies.get('session_id')
    if session_id:
        conn = connect_db()
        with conn.cursor() as cur:
            cur.execute("UPDATE sessions SET valid=FALSE WHERE id=%s", (session_id,))
            conn.commit()
        conn.close()
    resp = make_response("Logged out\n")
    resp.delete_cookie('session_id', path='/')
    return resp

# -------------------------------------------------------
# INDEX
# -------------------------------------------------------
@app.route('/')
def index():
    return "Welcome to the bank app. Use /register, /login, /manage, /logout\n"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)
