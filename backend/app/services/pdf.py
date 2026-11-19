"""PDFs (HTML + WeasyPrint), in the light print version of the design system."""
from app.core.util import fmt_dt

PRINT_CSS = """
@page { size: A4; margin: 22mm 18mm; @bottom-right { content: counter(page) " / " counter(pages); font-size: 9pt; color: #5A5D66; } }
body { font-family: Manrope, 'DejaVu Sans', sans-serif; color: #14151A; font-size: 10.5pt; line-height: 1.55; }
h1, h2 { font-weight: 800; letter-spacing: -0.01em; margin: 0 0 8pt; }
h2 { font-size: 17pt; } h3 { font-size: 11.5pt; margin: 14pt 0 4pt; }
.kicker { font-size: 8pt; letter-spacing: .2em; text-transform: uppercase; color: #8F7635; font-weight: 700; }
.rule { border-top: 1px solid #C9A84C; margin: 14pt 0; }
table { width: 100%; border-collapse: collapse; margin: 8pt 0; }
td, th { border-bottom: 1px solid #E6E1D6; padding: 6pt 4pt; text-align: left; vertical-align: top; }
th { font-size: 8.5pt; color: #5A5D66; text-transform: uppercase; letter-spacing: .08em; }
.num { text-align: right; font-variant-numeric: tabular-nums; }
.sig { display: inline-block; width: 46%; margin-right: 3%; vertical-align: top; border-top: 1px solid #14151A; padding-top: 6pt; margin-top: 28pt; }
.sig .typed { font-family: 'DejaVu Serif', serif; font-style: italic; font-size: 18pt; }
.audit { page-break-before: always; font-size: 9pt; }
.audit td { font-size: 8.5pt; word-break: break-all; }
.muted { color: #5A5D66; }
"""


def render_pdf(body_html: str) -> bytes:
    from weasyprint import HTML
    doc = f"<html><head><meta charset='utf-8'><style>{PRINT_CSS}</style></head><body>{body_html}</body></html>"
    return HTML(string=doc).write_pdf()


def contract_pdf(practice_name, title, contract_html, signatures, doc_hash):
    sigs = ""
    for s in signatures:
        mark = (f"<img src='{s['image']}' style='height:46pt'/>" if s.get("image") else f"<div class='typed'>{s['name']}</div>")
        sigs += (f"<div class='sig'>{mark}<div><b>{s['name']}</b> · {s['role'].title()}</div>"
                 f"<div class='muted'>Signed {fmt_dt(s['signed_at'])}</div></div>")
    rows = "".join(
        f"<tr><td>{s['name']}<br>{s.get('phone') or ''} {s.get('email') or ''}</td><td>{s['role'].title()}</td>"
        f"<td>{fmt_dt(s['signed_at'])}<br>{s['signed_at'].isoformat()} UTC</td><td>{s.get('ip', '')}<br>{(s.get('device') or '')[:80]}</td>"
        f"<td>{'OTP verified ' + (s.get('otp_channel') or '') if s.get('otp_verified') else 'Logged-in consultant'}</td></tr>"
        for s in signatures)
    audit = (f"<div class='audit'><div class='kicker'>Audit trail</div><h2>Signing record</h2>"
             f"<p class='muted'>Document fingerprint (SHA-256 of the exact contract text signed):<br><b>{doc_hash}</b></p>"
             f"<table><tr><th>Signer</th><th>Role</th><th>Time (IST / UTC)</th><th>IP and device</th><th>Check</th></tr>{rows}</table></div>")
    body = (f"<div class='kicker'>{practice_name}</div><div class='rule'></div>{contract_html}"
            f"<div class='rule'></div>{sigs}{audit}")
    return render_pdf(body)


# ---------------- invoices and quotes ----------------

def _e(s):
    import html
    return html.escape(str(s or ""))


async def invoice_html(ctx, inv) -> str:
    """The invoice as the client sees it. Never contains cost or margin."""
    from app.domain.billing.money import line_total, view
    from app.domain.billing.timebill import timesheet_rows
    from app.core.util import fmt_date, inr
    ws = await ctx.ws()
    v = await view(ctx, inv, for_client=True)
    c = await ctx.data.contacts.get(inv.get("contact_id") or "") or {}
    t = inv["totals"]
    lines = "".join(f"<tr><td>{_e(l.get('name'))}<div class='muted'>{_e(l.get('desc'))}</div></td>"
                    f"<td class='num'>{_e(l.get('qty', 1))}</td><td class='num'>{inr(l.get('price_paise', 0))}</td>"
                    f"<td class='num'>{inr(line_total(l))}</td></tr>" for l in inv.get("lines", []))
    tax = "".join(f"<tr><td colspan='3'>{k}</td><td class='num'>{inr(t[x])}</td></tr>"
                  for k, x in (("Discount", "discount"), ("CGST", "cgst"), ("SGST", "sgst"), ("IGST", "igst")) if t.get(x))
    sched = "".join(f"<tr><td>{_e(s['label'])}</td><td>{_e(s.get('due_label'))}</td><td>{_e(s.get('state', '')).replace('_', ' ')}</td>"
                    f"<td class='num'>{inr(s['amount_paise'])}</td></tr>" for s in v.get("schedule", []))
    pay = ws.get("invoice", {})
    bank = pay.get("bank") or {}
    ts = await timesheet_rows(ctx, inv)
    ts_html = ""
    if ts and ts["mode"] == "full":
        head = "".join(f"<th{' class=num' if c == 'hours' else ''}>{c.title()}</th>" for c in ts["columns"])
        body = "".join("<tr>" + "".join(f"<td{' class=num' if c == 'hours' else ''}>{_e(r.get(c, ''))}</td>" for c in ts["columns"]) + "</tr>"
                       for r in ts["rows"])
        ts_html = f"<h3>Timesheet</h3><table><tr>{head}</tr>{body}</table><p class='muted'>Total {ts['total_hours']} hours.</p>"
    return (f"<div class='kicker'>{_e(ws['profile'].get('practice_name') or ws['name'])}</div>"
            f"<h2>{_e(inv.get('doc_title', 'Invoice'))} {_e(inv.get('number') or '(draft)')}</h2>"
            f"<p>Date: {fmt_date(inv.get('sent_at') or inv['created_at'])}<br>Billed to: <b>{_e(c.get('name'))}</b>"
            f"{(' · ' + _e(c.get('company'))) if c.get('company') else ''}</p>"
            + (f"<p class='muted'>GSTIN {_e(pay.get('gstin'))}</p>" if inv.get("gst", {}).get("enabled") and pay.get("gstin") else "")
            + f"<table><tr><th>Item</th><th class='num'>Qty</th><th class='num'>Rate</th><th class='num'>Amount</th></tr>{lines}"
            f"<tr><td colspan='3'>Subtotal</td><td class='num'>{inr(t['subtotal'])}</td></tr>{tax}"
            f"<tr><td colspan='3'><b>Total</b></td><td class='num'><b>{inr(t['total'])}</b></td></tr></table>"
            f"<h3>Payment schedule</h3><table><tr><th>For</th><th>Due</th><th>Status</th><th class='num'>Amount</th></tr>{sched}</table>"
            f"<h3>How to pay</h3><p>{('UPI: <b>' + _e(pay.get('upi_id')) + '</b><br>') if pay.get('upi_id') else ''}"
            + (f"Bank: {_e(bank.get('account_name'))}, A/c {_e(bank.get('account_no'))}, IFSC {_e(bank.get('ifsc'))}" if bank.get("account_no") else "")
            + "</p><p class='muted'>Paid directly to the consultant.</p>" + ts_html)


async def invoice_pdf(ctx, inv) -> bytes:
    return render_pdf(await invoice_html(ctx, inv))
