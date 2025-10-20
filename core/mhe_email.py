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

import mysql.connector
import requests
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse

from config.env import st

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

app = FastAPI(title="MHE Email Service")

# --- Token sign/unsign (HMAC) ---
def _sign(payload: dict, secret: str) -> str:
    data = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    sig = hmac.new(secret.encode(), data, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(data + b"." + sig).decode()

def _unsign(token: str, secret: str):
    try:
        raw = base64.urlsafe_b64decode(token.encode())
        data, _, sig = raw.rpartition(b".")
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
def query_utmlogs_by_user_and_day(login, date_start, date_end):
    try:
        cnx = mysql.connector.connect(**st.mysql_config)
        cursor = cnx.cursor()
        cols = ", ".join(f"`{c}`" for c in EXTENDED_COLUMNS)
        cursor.execute(
            f"""
            SELECT {cols}
            FROM UTMLogs
            WHERE `user` = %s AND STR_TO_DATE(CONCAT(`date`, ' ', `time`), '%Y-%m-%d %H:%i:%s') BETWEEN %s AND %s
            ORDER BY `date` ASC, `time` ASC
            """,
            (login, date_start, date_end),
        )
        rows = cursor.fetchall()
        cursor.close()
        cnx.close()
        return rows
    except Exception as e:
        logger.error(f"DB query failed for {login}: {e}")
        return []

# --- HTML Table and Export ---
def render_html_table(rows):
    if not rows:
        return "<p>No records</p>"
    thead = "".join(f"<th>{h}</th>" for h in EXTENDED_COLUMNS)
    body = "".join("<tr>" + "".join(f"<td>{c or ''}</td>" for c in row) + "</tr>" for row in rows)
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
    tbody = "".join("<tr>" + "".join(f"<td>{c or ''}</td>" for c in row) + "</tr>" for row in rows)
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

def send_daily_reports():
    today = datetime.now().date()
    window_start = datetime.combine(today - timedelta(days=1), dt_time(8,0))
    window_end = window_start + timedelta(days=1)
    yest_str = (today - timedelta(days=1)).strftime("%Y-%m-%d")

    try:
        ldap_url = f"http://{st.MHE_LDAP_HOST}:{st.MHE_LDAP_PORT}/list"
        users = requests.get(ldap_url, timeout=10).json().get("users", [])
    except Exception as e:
        logger.error(f"LDAP list request failed: {e}")
        users = []

    sent = {}
    for item in users:
        login = str(item.get("login", "")).strip()
        emails = [str(e).strip() for e in item.get("emails", []) if str(e).strip()]
        if not login or not emails:
            continue
        rows = query_utmlogs_by_user_and_day(login, window_start, window_end)
        if not rows:
            subject = f"[UTM] Нет событий безопасности за {yest_str}"
            body = f"События безопасности для абонента {login} за {yest_str} отсутствуют."
        else:
            token = _sign({"login": login, "date": yest_str}, st.EMAIL_TOKEN)
            report_url = f"http://{st.MHE_EMAIL_HOST}:{st.MHE_EMAIL_PORT}/report?token={token}"
            subject = f"[UTM] Отчёт о событиях безопасности за {yest_str}"
            body = f"Отчёт о событиях безопасности для абонента {login} за {yest_str}: {report_url}"
        if send_email_smtp(emails, subject, body):
            sent[login] = subject
        else:
            logger.error(f"Failed to send email to {login}")

    return {"date": yest_str, "processed": len(users), "sent": sent}

async def daily_report_scheduler():
    logger.info("Daily report scheduler started")
    try:
        r = send_daily_reports()
        logger.info(f"Startup report sent: {r}")
    except Exception as e:
        logger.error(f"Error sending startup reports: {e}")
    while True:
        try:
            to_wait = (next_run_time() - datetime.now()).total_seconds()
            logger.info(f"Next report scheduled at {next_run_time().strftime('%Y-%m-%d %H:%M:%S')} (in {to_wait:.0f} seconds)")
            await asyncio.sleep(to_wait)
            logger.info("Sending scheduled daily reports...")
            r = send_daily_reports()
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
        day = datetime.strptime(date_str, "%Y-%m-%d")
    except Exception:
        return HTMLResponse("<h3>Invalid date</h3>", status_code=400)
    rows = query_utmlogs_by_user_and_day(login, day, day + timedelta(days=1))
    # Минимизируем: просто даём html-страницу со всеми controls (не только таблица)
    return HTMLResponse(render_html_page(login, date_str, rows, token))

@app.get("/download/csv")
def download_csv(token: str = Query(...)):
    payload = _unsign(token, st.EMAIL_TOKEN)
    if not payload: return JSONResponse({"error": "invalid token"}, status_code=400)
    login, date_str = payload.get("login"), payload.get("date")
    day = datetime.strptime(date_str, "%Y-%m-%d")
    rows = query_utmlogs_by_user_and_day(login, day, day + timedelta(days=1))
    csv_text = gen_csv(rows)
    return StreamingResponse([csv_text.encode("utf-8")], media_type="text/csv")

@app.get("/download/excel")
def download_excel(token: str = Query(...)):
    payload = _unsign(token, st.EMAIL_TOKEN)
    if not payload: return JSONResponse({"error": "invalid token"}, status_code=400)
    login, date_str = payload.get("login"), payload.get("date")
    day = datetime.strptime(date_str, "%Y-%m-%d")
    rows = query_utmlogs_by_user_and_day(login, day, day + timedelta(days=1))
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
