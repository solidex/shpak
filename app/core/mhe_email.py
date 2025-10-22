import asyncio
import base64
import hmac
import hashlib
import json
import logging
import smtplib
from logging.handlers import RotatingFileHandler
from pathlib import Path
from datetime import datetime, timedelta, time as dt_time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

import mysql.connector
from mysql.connector import pooling
import requests
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse

from app.config.env import st

EXTENDED_COLUMNS = [
    "action", "date", "dstcountry", "dstip", "dstport",
    "eventtype", "ipaddr", "msg", "srccountry", "srcip",
    "utmtype", "time", "user", "category", "hostname",
    "service", "url", "httpagent", "level", "threat"
]

# --- Simple Logging ---
def setup_logging():
    Path("logs").mkdir(exist_ok=True)
    handler = RotatingFileHandler("logs/mhe_email.log", maxBytes=10*1024*1024, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])

setup_logging()
logger = logging.getLogger(__name__)

# --- Connection Pool ---
# Reuse DB connections for better performance (saves ~15-20ms per query)
try:
    db_pool = pooling.MySQLConnectionPool(
        pool_name="starrocks_pool",
        pool_size=50,  # Max 50 concurrent connections (для 1000+ пользователей)
        pool_reset_session=True,
        **getattr(st, 'starrocks_config', st.mysql_config)
    )
    logger.info("Database connection pool created (size=50)")
except Exception as e:
    logger.error(f"Failed to create connection pool: {e}")
    db_pool = None

# --- Thread Pool for blocking I/O ---
# Used for parallel processing of DB queries and email sending
executor = ThreadPoolExecutor(max_workers=100, thread_name_prefix="email_worker")
logger.info("Thread pool executor created (max_workers=100)")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: resources are already initialized above
    yield
    # Shutdown: cleanup resources
    logger.info("Shutting down: cleaning up executor and connection pool")
    executor.shutdown(wait=True, cancel_futures=False)
    logger.info("Executor shut down successfully")

app = FastAPI(title="MHE Email Service", lifespan=lifespan)

# --- Token sign/unsign (HMAC) ---
def _sign(payload: dict, secret: str) -> str:
    data = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    sig = hmac.new(secret.encode(), data, hashlib.sha256).digest()
    combined = data + b":" + sig
    return base64.urlsafe_b64encode(combined).decode()

def _unsign(token: str, secret: str):
    try:
        raw = base64.urlsafe_b64decode(token.encode())
        data, _, sig = raw.rpartition(b":")
        if not sig:
            return None
        good = hmac.new(secret.encode(), data, hashlib.sha256).digest()
        if not hmac.compare_digest(sig, good):
            return None
        return json.loads(data.decode())
    except Exception:
        return None

# --- Email ---
def send_email_smtp(to_emails, subject, body) -> bool:
    if not to_emails:
        logger.warning("No recipients provided")
        return False
    try:
        from email.message import EmailMessage
        msg = EmailMessage()
        msg.set_content(body)
        msg["From"] = st.SMTP_FROM
        msg["To"] = ", ".join(to_emails)
        msg["Subject"] = subject

        if getattr(st, "SMTP_USE_SSL", False):
            server = smtplib.SMTP_SSL(st.SMTP_HOST, st.SMTP_PORT, timeout=getattr(st, "SMTP_TIMEOUT", 10))
        else:
            server = smtplib.SMTP(st.SMTP_HOST, st.SMTP_PORT, timeout=getattr(st, "SMTP_TIMEOUT", 10))
            if getattr(st, "SMTP_USE_TLS", False):
                server.starttls()

        if getattr(st, "SMTP_USER", None) and getattr(st, "SMTP_PASSWORD", None):
            server.login(st.SMTP_USER, st.SMTP_PASSWORD)

        server.send_message(msg)
        server.quit()
        logger.info(f"Email sent to {to_emails}: {subject}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email to {to_emails}: {e}")
        return False

# --- DB Query ---
def query_utmlogs_by_user_and_reporting_date(login, reporting_date):
    """Query UTM logs for user by reporting_date (8:00 AM - 8:00 AM window)
    
    Args:
        login: User login name
        reporting_date: Date in YYYY-MM-DD format (or date object)
    
    Returns:
        List of rows with all UTM log columns
    """
    try:
        # StarRocks (MySQL protocol) as primary storage
        # Uses connection pool for better performance (~15-20ms faster)
        if db_pool:
            cnx = db_pool.get_connection()
        else:
            cnx = mysql.connector.connect(**getattr(st, 'starrocks_config', st.mysql_config))
        
        cursor = cnx.cursor()
        cols = ", ".join(f"`{c}`" for c in EXTENDED_COLUMNS)
        cursor.execute(
            f"""
            SELECT {cols}
            FROM UTMLogs
            WHERE `user` = %s AND `reporting_date` = %s
            ORDER BY `event_time` ASC
            """,
            (login, reporting_date),
        )
        rows = cursor.fetchall()
        cursor.close()
        cnx.close()
        return rows
    except Exception as e:
        logger.error(f"DB query failed for {login}, reporting_date={reporting_date}: {e}")
        return []

# --- HTML Table and Export ---
def render_html_table(rows):
    if not rows:
        return "<p>No records</p>"
    thead = "".join(f"<th>{h}</th>" for h in EXTENDED_COLUMNS)
    # Optimized: use list comprehension + single join (O(n) instead of O(n²))
    body_parts = []
    for row in rows:
        body_parts.append("<tr>")
        body_parts.extend(f"<td>{c or ''}</td>" for c in row)
        body_parts.append("</tr>")
    body = "".join(body_parts)
    return f"<table border='1' cellpadding='4' cellspacing='0'><thead><tr>{thead}</tr></thead><tbody>{body}</tbody></table>"

def gen_csv(rows):
    import csv, io
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(EXTENDED_COLUMNS)
    for row in rows:
        writer.writerow([c if c is not None else "" for c in row])
    return output.getvalue()

def gen_excel(rows):
    thead = "".join(f"<th>{h}</th>" for h in EXTENDED_COLUMNS)
    # Optimized: use list + single join for better performance
    tbody_parts = []
    for row in rows:
        tbody_parts.append("<tr>")
        tbody_parts.extend(f"<td>{c or ''}</td>" for c in row)
        tbody_parts.append("</tr>")
    tbody = "".join(tbody_parts)
    html = f"""<html><head><meta charset='UTF-8'></head>
<body><table border='1'><thead><tr>{thead}</tr></thead><tbody>{tbody}</tbody></table></body></html>"""
    return html.encode("utf-8")

def render_html_page(login, date_str, rows, token):
    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8" />
  <title>Отчёт для {login}</title>
  <link rel="stylesheet" href="/static/report.css" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <style>body{{font-family:Arial,Helvetica,sans-serif;margin:20px}}</style>
</head>
<body>
  <h2>Отчёт о событиях безопасности для {login} ({date_str})</h2>
  <div class="controls">
    <a class="btn" href="/download/csv?token={token}">Скачать CSV</a>
    <a class="btn btn-primary" href="/download/excel?token={token}">Скачать Excel</a>
  </div>
  {render_html_table(rows)}
</body>
</html>"""

# --- Scheduling ---
def next_run_time():
    now = datetime.now()
    run = datetime.combine(now.date(), dt_time(8,0))
    return run if run > now else run + timedelta(days=1)

def process_single_user(item, reporting_date, yest_str):
    """Process single user: query DB → send email (sequential for this user)
    
    This function is thread-safe and can be called in parallel for different users.
    For each user, the sequence is maintained: DB query first, then email.
    """
    try:
        login = str(item.get("login", "")).strip()
        emails = [str(e).strip() for e in item.get("emails", []) if str(e).strip()]
        if not login or not emails:
            return None
        
        # Step 1: Query database (blocking I/O)
        rows = query_utmlogs_by_user_and_reporting_date(login, reporting_date)
        
        # Step 2: Send email based on DB result (blocking I/O)
        if not rows:
            subject = f"[UTM] Нет событий безопасности за {yest_str}"
            body = f"События безопасности для абонента {login} за {yest_str} отсутствуют."
        else:
            token = _sign({"login": login, "date": yest_str}, st.EMAIL_TOKEN)
            report_url = f"http://{st.MHE_EMAIL_HOST}:{st.MHE_EMAIL_PORT}/report?token={token}"
            subject = f"[UTM] Отчёт о событиях безопасности за {yest_str}"
            body = f"Отчёт о событиях безопасности для абонента {login} за {yest_str}: {report_url}"
        
        if send_email_smtp(emails, subject, body):
            return (login, subject)
        else:
            logger.error(f"Failed to send email to {login}")
            return None
    except Exception as e:
        logger.error(f"Error processing user {item.get('login')}: {e}")
        return None

async def send_daily_reports():
    """Send daily UTM reports for yesterday's reporting_date (8:00 AM - 8:00 AM)
    
    Users are processed in parallel using ThreadPoolExecutor.
    Each user: DB query → email sending (sequential).
    """
    today = datetime.now().date()
    # Yesterday's reporting_date covers events from yesterday 8:00 to today 8:00
    reporting_date = today - timedelta(days=1)
    yest_str = reporting_date.strftime("%Y-%m-%d")

    try:
        ldap_url = f"http://{st.MHE_LDAP_HOST}:{st.MHE_LDAP_PORT}/list"
        users = requests.get(ldap_url, timeout=10).json().get("users", [])
    except Exception as e:
        logger.error(f"LDAP list request failed: {e}")
        return {"error": str(e)}

    # Process users in parallel (each user: DB → Email sequentially)
    loop = asyncio.get_event_loop()
    tasks = [
        loop.run_in_executor(executor, process_single_user, item, reporting_date, yest_str)
        for item in users
    ]
    
    logger.info(f"Processing {len(users)} users in parallel...")
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Collect successful sends
    sent = {}
    for result in results:
        if isinstance(result, tuple) and len(result) == 2:
            login, subject = result
            sent[login] = subject
        elif isinstance(result, Exception):
            logger.error(f"Task failed with exception: {result}")
    
    logger.info(f"Sent {len(sent)}/{len(users)} emails")
    return {"date": yest_str, "processed": len(users), "sent": sent, "success_count": len(sent)}

async def daily_report_scheduler():
    logger.info("Daily report scheduler started (parallel mode)")
    try:
        r = await send_daily_reports()
        logger.info(f"Startup report sent: {r}")
    except Exception as e:
        logger.error(f"Error sending startup reports: {e}")
    while True:
        try:
            to_wait = (next_run_time() - datetime.now()).total_seconds()
            logger.info(f"Next report scheduled at {next_run_time().strftime('%Y-%m-%d %H:%M:%S')} (in {to_wait:.0f} seconds)")
            await asyncio.sleep(to_wait)
            logger.info("Sending scheduled daily reports (parallel processing)...")
            r = await send_daily_reports()
            logger.info(f"Daily reports sent: {r}")
        except Exception as e:
            logger.error(f"Error in daily scheduler: {e}")
            await asyncio.sleep(60)  # Retry if fail

@app.get("/report", response_class=HTMLResponse)
def report(token: str = Query(...)):
    payload = _unsign(token, st.EMAIL_TOKEN)
    if not payload: return HTMLResponse("<h3>Invalid token</h3>", status_code=400)
    login, date_str = payload.get("login"), payload.get("date")
    try:
        reporting_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except Exception:
        return HTMLResponse("<h3>Invalid date</h3>", status_code=400)
    # Query by reporting_date (covers 8:00 AM - 8:00 AM automatically)
    rows = query_utmlogs_by_user_and_reporting_date(login, reporting_date)
    return HTMLResponse(render_html_page(login, date_str, rows, token))

@app.get("/download/csv")
def download_csv(token: str = Query(...)):
    payload = _unsign(token, st.EMAIL_TOKEN)
    if not payload: return JSONResponse({"error": "invalid token"}, status_code=400)
    login, date_str = payload.get("login"), payload.get("date")
    reporting_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    rows = query_utmlogs_by_user_and_reporting_date(login, reporting_date)
    csv_text = gen_csv(rows)
    return StreamingResponse([csv_text.encode("utf-8")], media_type="text/csv")

@app.get("/download/excel")
def download_excel(token: str = Query(...)):
    payload = _unsign(token, st.EMAIL_TOKEN)
    if not payload: return JSONResponse({"error": "invalid token"}, status_code=400)
    login, date_str = payload.get("login"), payload.get("date")
    reporting_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    rows = query_utmlogs_by_user_and_reporting_date(login, reporting_date)
    data = gen_excel(rows)
    return StreamingResponse([data], media_type="application/vnd.ms-excel", headers={
        "Content-Disposition": f"attachment; filename=utm_report_{login}_{date_str}.xls"
    })

@app.get("/health")
def health():
    return {"status": "ok", "service": "mhe_email"}

if __name__ == "__main__":
    import uvicorn

    async def _run():
        config = uvicorn.Config(app, host="0.0.0.0", port=80, log_config=None, loop="asyncio")
        server = uvicorn.Server(config)
        server_task = asyncio.create_task(server.serve())
        scheduler_task = asyncio.create_task(daily_report_scheduler())
        done, pending = await asyncio.wait({server_task, scheduler_task}, return_when=asyncio.FIRST_EXCEPTION)
        for t in pending:
            t.cancel()

    asyncio.run(_run())
