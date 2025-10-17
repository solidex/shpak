import asyncio
import base64
import hmac
import hashlib
import json
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta, time as dt_time

import mysql.connector
import requests
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse

from config.env import st
from core.mhe_log import EXTENDED_COLUMNS


def setup_logging() -> None:
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    handler = RotatingFileHandler(log_dir / "mhe_email.log", maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])


setup_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="MHE Email Service")


def _sign(payload: Dict, secret: str) -> str:
    data = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), data, hashlib.sha256).digest()
    token = base64.urlsafe_b64encode(data + b"." + sig).decode("utf-8")
    return token


def _unsign(token: str, secret: str) -> Optional[Dict]:
    try:
        raw = base64.urlsafe_b64decode(token.encode("utf-8"))
        data, _, sig = raw.rpartition(b".")
        good = hmac.new(secret.encode("utf-8"), data, hashlib.sha256).digest()
        if not hmac.compare_digest(sig, good):
            return None
        return json.loads(data.decode("utf-8"))
    except Exception:
        return None


def send_email_smtp(to_emails: List[str], subject: str, body: str) -> bool:
    """Send email via SMTP (supports SSL/TLS/plain)"""
    if not to_emails:
        logger.warning("No recipients provided")
        return False
    
    try:
        # Use EmailMessage for simpler API
        from email.message import EmailMessage
        msg = EmailMessage()
        msg.set_content(body)
        msg["From"] = st.SMTP_FROM
        msg["To"] = ", ".join(to_emails)
        msg["Subject"] = subject
        
        # Choose SMTP mode
        if getattr(st, "SMTP_USE_SSL", False):
            server = smtplib.SMTP_SSL(st.SMTP_HOST, st.SMTP_PORT, timeout=getattr(st, "SMTP_TIMEOUT", 10))
        else:
            server = smtplib.SMTP(st.SMTP_HOST, st.SMTP_PORT, timeout=getattr(st, "SMTP_TIMEOUT", 10))
            if st.SMTP_USE_TLS:
                server.starttls()
        
        if st.SMTP_USER and st.SMTP_PASSWORD:
            server.login(st.SMTP_USER, st.SMTP_PASSWORD)
        
        server.send_message(msg)
        server.quit()
        logger.info(f"Email sent to {to_emails}: {subject}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email to {to_emails}: {e}")
        return False


def query_utmlogs_by_user_and_day(login: str, date_start: datetime, date_end: datetime) -> List[Tuple]:
    try:
        cnx = mysql.connector.connect(**st.mysql_config)
        cursor = cnx.cursor()
        # Select all columns from EXTENDED_COLUMNS
        cols_sql = ", ".join([f"`{c}`" for c in EXTENDED_COLUMNS])
        cursor.execute(
            f"""
            SELECT {cols_sql}
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


def render_html_table(rows: List[Tuple]) -> str:
    if not rows:
        return "<p>No records</p>"
    thead = "".join(f"<th>{h}</th>" for h in EXTENDED_COLUMNS)
    body = "".join(
        "<tr>" + "".join(f"<td>{(c if c is not None else '')}</td>" for c in row) + "</tr>" for row in rows
    )
    return f"<table border='1' cellpadding='4' cellspacing='0'><thead><tr>{thead}</tr></thead><tbody>{body}</tbody></table>"


def gen_csv(rows: List[Tuple]) -> str:
    import csv
    import io

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(EXTENDED_COLUMNS)
    for row in rows:
        writer.writerow([c if c is not None else "" for c in row])
    return output.getvalue()


def calculate_next_run_time() -> datetime:
    """Calculate next scheduled run time based on REPORT_SEND_TIME"""
    try:
        hour, minute = map(int, st.REPORT_SEND_TIME.split(":"))
        target_time = dt_time(hour, minute)
    except Exception:
        logger.error(f"Invalid REPORT_SEND_TIME format: {st.REPORT_SEND_TIME}, using 09:00")
        target_time = dt_time(9, 0)
    
    now = datetime.now()
    next_run = datetime.combine(now.date(), target_time)
    
    # If target time already passed today, schedule for tomorrow
    if next_run <= now:
        next_run += timedelta(days=1)
    
    return next_run


def send_daily_reports() -> Dict:
    """Execute daily report sending (internal function)"""
    yesterday = datetime.utcnow().date() - timedelta(days=1)
    yesterday_str = yesterday.strftime("%Y-%m-%d")
    
    # Placeholder: fetch user list; replace with a real source
    users: List[str] = []
    
    # LDAP lookup
    try:
        ldap_url = f"http://{st.MHE_LDAP_HOST}:{st.MHE_LDAP_PORT}/lookup"
        resp = requests.post(ldap_url, json={"logins": users}, timeout=5)
        mapping = resp.json().get("users", {}) if resp.ok else {}
    except Exception as e:
        logger.error(f"LDAP lookup failed: {e}")
        mapping = {u: [] for u in users}
    
    sent: Dict[str, str] = {}
    for login in users:
        emails = mapping.get(login, [])
        rows = query_utmlogs_by_user_and_day(login, datetime.strptime(yesterday_str, "%Y-%m-%d"), datetime.strptime(yesterday_str, "%Y-%m-%d") + timedelta(days=1))
        if not emails:
            logger.info(f"No emails for {login}; skipping")
            continue
        
        if not rows:
            subject = f"[UTM] Нет логов за {yesterday_str}"
            body = f"Для пользователя {login} логи за {yesterday_str} отсутствуют."
        else:
            token = _sign({"login": login, "date": yesterday_str}, st.API_TOKEN)
            report_url = f"http://{st.MHE_EMAIL_HOST}:{st.MHE_EMAIL_PORT}/report?token={token}"
            subject = f"[UTM] Отчет за {yesterday_str}"
            body = f"Отчет доступен по ссылке: {report_url}\nCSV: {report_url.replace('/report', '/report.csv')}"
        
        # Send email via SMTP
        if send_email_smtp(emails, subject, body):
            sent[login] = subject
        else:
            logger.error(f"Failed to send email to {login}")
    
    return {"date": yesterday_str, "processed": len(users), "sent": sent}


async def daily_report_scheduler():
    """Background task that sends reports daily at scheduled time"""
    logger.info("Daily report scheduler started")
    
    # First run immediately on startup
    logger.info("Sending reports on startup...")
    try:
        result = send_daily_reports()
        logger.info(f"Startup report sent: {result}")
    except Exception as e:
        logger.error(f"Error sending startup reports: {e}")
    
    # Then schedule daily runs
    while True:
        try:
            next_run = calculate_next_run_time()
            wait_seconds = (next_run - datetime.now()).total_seconds()
            logger.info(f"Next report scheduled at {next_run.strftime('%Y-%m-%d %H:%M:%S')} (in {wait_seconds:.0f} seconds)")
            
            await asyncio.sleep(wait_seconds)
            
            logger.info("Sending scheduled daily reports...")
            result = send_daily_reports()
            logger.info(f"Daily reports sent: {result}")
        except Exception as e:
            logger.error(f"Error in daily scheduler: {e}")
            await asyncio.sleep(3600)  # Retry in 1 hour on error


@app.on_event("startup")
async def startup_event():
    """Start background scheduler on app startup"""
    asyncio.create_task(daily_report_scheduler())


@app.get("/report", response_class=HTMLResponse)
def report(token: str = Query(...)):
    payload = _unsign(token, st.API_TOKEN)
    if not payload:
        return HTMLResponse("<h3>Invalid token</h3>", status_code=400)
    login = payload.get("login")
    date_str = payload.get("date")  # YYYY-MM-DD
    try:
        day = datetime.strptime(date_str, "%Y-%m-%d")
    except Exception:
        return HTMLResponse("<h3>Invalid date</h3>", status_code=400)

    rows = query_utmlogs_by_user_and_day(login, day, day + timedelta(days=1))
    html_table = render_html_table(rows)
    return HTMLResponse(f"<h2>Report for {login} ({date_str})</h2>" + html_table)


@app.get("/report.csv")
def report_csv(token: str = Query(...)):
    payload = _unsign(token, st.API_TOKEN)
    if not payload:
        return JSONResponse({"error": "invalid token"}, status_code=400)
    login = payload.get("login")
    date_str = payload.get("date")
    day = datetime.strptime(date_str, "%Y-%m-%d")
    rows = query_utmlogs_by_user_and_day(login, day, day + timedelta(days=1))
    csv_text = gen_csv(rows)
    return StreamingResponse(iter([csv_text.encode("utf-8")]), media_type="text/csv")


# Manual trigger endpoint (can be triggered externally via cron/k8s)
@app.get("/run_daily")
def run_daily():
    """Manual trigger for daily report sending.
    
    Note: Reports are now sent automatically at scheduled time (REPORT_SEND_TIME).
    This endpoint allows manual triggering if needed.
    """
    logger.info("Manual trigger: running daily reports")
    return send_daily_reports()


@app.get("/health")
def health():
    return {"status": "ok", "service": "mhe_email"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8087, log_config=None)


