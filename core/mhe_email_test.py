import os
from datetime import datetime, timedelta, time as dt_time
from pathlib import Path
from typing import List, Tuple

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, Response
import uvicorn


# Minimal EXTENDED_COLUMNS identical to core.mhe_log
EXTENDED_COLUMNS = [
    "action", "date", "dstcountry", "dstip", "dstport", 
    "eventtype", "ipaddr", "msg", "srccountry", "srcip",
    "utmtype", "time", "user", "category", "hostname", 
    "service", "url", "httpagent", "level", "threat"
]


def render_html_table(rows: List[Tuple]) -> str:
    if not rows:
        return '<div class="no-records">Записи отсутствуют</div>'
    thead = "".join(f"<th>{h}</th>" for h in EXTENDED_COLUMNS)
    body = "".join(
        "<tr>" + "".join(f"<td>{(c if c is not None else '')}</td>" for c in row) + "</tr>"
        for row in rows
    )
    return f"<table><thead><tr>{thead}</tr></thead><tbody>{body}</tbody></table>"


def gen_csv(rows: List[Tuple]) -> str:
    import csv
    import io

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(EXTENDED_COLUMNS)
    for row in rows:
        writer.writerow([c if c is not None else "" for c in row])
    return output.getvalue()


def gen_excel(rows: List[Tuple]) -> bytes:
    # HTML-based .xls that Excel opens without extra deps
    thead = "".join(f"<th>{h}</th>" for h in EXTENDED_COLUMNS)
    tbody = "".join(
        "<tr>" + "".join(f"<td>{(c if c is not None else '')}</td>" for c in row) + "</tr>"
        for row in rows
    )
    html = f"""<html><head><meta charset='UTF-8'></head>
<body><table border='1'><thead><tr>{thead}</tr></thead><tbody>{tbody}</tbody></table></body></html>"""
    return html.encode("utf-8")


def render_html_page(login: str, date_str: str, rows: List[Tuple]) -> str:
    controls = (
        '<div class="controls">'
        '<a class="btn" href="/download/csv">Скачать CSV</a>'
        '<a class="btn btn-primary" href="/download/excel">Скачать Excel</a>'
        '</div>'
    )
    table_html = render_html_table(rows)
    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset=\"UTF-8\" />
  <title>Отчёт для {login}</title>
  <link rel=\"stylesheet\" href=\"/static/report.css\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <style>body{{font-family:Arial,Helvetica,sans-serif;margin:20px}}</style>
</head>
<body>
  <h2>Отчёт о событиях безопасности для {login} ({date_str})</h2>
  {controls}
  {table_html}
</body>
</html>"""


def build_sample_rows(login: str, date_str: str) -> List[Tuple]:
    return [
        (
            "allow", date_str, "BY", "178.124.200.1", "443", "signature", "10.0.0.5",
            "TLS handshake", "BY", "10.1.2.3", "ips", "08:15:12", login,
            "Category desc", "host.example.com", "https", "https://example.com/page", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/81.0.4044.138 Safari/537.36 OPR/68.0.3618.125", "low", ""
        ),
        (
            "block", date_str, "US", "93.184.216.34", "80", "infected", "10.0.0.5",
            "Blocked URL", "BY", "10.1.2.3", "webfilter", "12:45:33", login,
            "Malicious", "example.org", "http", "http://mal.example.org/", "Wget/1.20.1 (linux-gnu)", "medium", "phishing"
        ),
        (
            "monitor", date_str, "RU", "203.0.113.9", "53", "dns-response", "10.0.0.6",
            "DNS query", "BY", "10.1.2.4", "dns", "19:02:01", login,
            "DNS", "dns.example", "dns", "http://dns.query/", "", "info", ""
        ),
    ]


app = FastAPI(title="MHE Email Demo")


@app.get("/")
def root():
    login = "asya"
    date_str = (datetime.now().date() - timedelta(days=1)).strftime("%Y-%m-%d")
    rows = build_sample_rows(login, date_str)
    html = render_html_page(login, date_str, rows)
    return HTMLResponse(html)


@app.get("/download/csv")
def download_csv():
    login = "asya"
    date_str = (datetime.now().date() - timedelta(days=1)).strftime("%Y-%m-%d")
    rows = build_sample_rows(login, date_str)
    csv_text = gen_csv(rows)
    return Response(
        content=csv_text.encode("utf-8"),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=utm_report_{login}_{date_str}.csv"},
    )


@app.get("/download/excel")
def download_excel():
    login = "asya"
    date_str = (datetime.now().date() - timedelta(days=1)).strftime("%Y-%m-%d")
    rows = build_sample_rows(login, date_str)
    data = gen_excel(rows)
    return Response(
        content=data,
        media_type="application/vnd.ms-excel",
        headers={"Content-Disposition": f"attachment; filename=utm_report_{login}_{date_str}.xls"},
    )


@app.get("/static/report.css")
def serve_css():
    css_path = Path(__file__).resolve().parents[1] / "models" / "report.css"
    try:
        with open(css_path, "r", encoding="utf-8") as f:
            return Response(content=f.read(), media_type="text/css")
    except Exception:
        return Response(content="", media_type="text/css", status_code=404)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=80, log_config=None)


