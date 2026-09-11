"""Original portable outputs; public product bundles exclude creator records and private sources."""
import html
import io
import json
import re
import zipfile
from pathlib import Path


def manuscript(job):
    sections = ["transformation", "chapter_1", "chapter_2", "chapter_3"]
    chunks = ["# " + job["brief"]["topic"], "Status: editorial draft. Review accuracy and rights before publication."]
    if job["provider"] == "demo":
        chunks.insert(1, "DEMO FIXTURE - NOT FOR SALE")
    for stage in sections:
        a = job["artifacts"].get(stage)
        if a:
            chunks.extend(["## " + a["title"], a["body"], "References: " + ", ".join(a["citations"])])
    chunks.append("## Sources")
    chunks.extend(f"- [{s['id']}] {s['title']}: {s['url']}" for s in job["brief"]["sources"])
    return "\n\n".join(chunks)


def html_document(title, body):
    paragraphs = []
    for block in body.split("\n\n"):
        heading = re.match(r"^(#{1,3}) (.+)$", block)
        if heading:
            level = len(heading[1])
            paragraphs.append(f"<h{level}>{html.escape(heading[2])}</h{level}>")
        else:
            paragraphs.append("<p>" + html.escape(block).replace("\n", "<br>") + "</p>")
    return '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>' + html.escape(title) + '</title><style>body{max-width:760px;margin:60px auto;padding:0 24px;color:#20382f;background:#fcfaf4;font:18px/1.7 Georgia,serif}h1,h2,h3{font-family:Arial,sans-serif;line-height:1.2}h1{font-size:44px}h2{margin-top:48px}p{overflow-wrap:anywhere}@media print{body{margin:0;max-width:none}h2{break-after:avoid}}</style><main>' + "".join(paragraphs) + "</main></html>"


def bundle(job):
    if job["state"] != "ready":
        raise ValueError("Product generation is not complete.")
    content = manuscript(job)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("product.md", content)
        archive.writestr("product.html", html_document(job["brief"]["topic"], content))
        archive.writestr("README.txt", "Original editorial draft. This bundle contains a readable HTML edition and Markdown source.\n")
    return out.getvalue()


def export_job(store, job_id, destination):
    job = store.job(job_id)
    if job["state"] != "ready":
        raise ValueError("Wait for the job to become ready.")
    dest = Path(destination)
    dest.mkdir(parents=True, exist_ok=True)
    for stage, a in job["artifacts"].items():
        (dest / (stage + ".md")).write_text("# " + a["title"] + "\n\n" + a["body"], encoding="utf-8")
    (dest / "product.zip").write_bytes(bundle(job))
    (dest / "product.html").write_text(html_document(job["brief"]["topic"], manuscript(job)), encoding="utf-8")
    funnel = {"version": 1, "pages": [
        {"id": "sample", "type": "lead-magnet", "next": "offer"},
        {"id": "offer", "type": "sales", "next": "checkout"},
        {"id": "checkout", "type": "provider-checkout", "next": "delivery"},
        {"id": "delivery", "type": "verified-download", "next": "feedback"},
        {"id": "feedback", "type": "feedback", "next": None}],
        "copy": job["artifacts"]["storefront"], "launch": job["artifacts"]["launch"],
        "status": "planning export; pages require implementation and hosting"}
    (dest / "funnel.json").write_text(json.dumps(funnel, indent=2), encoding="utf-8")
    with zipfile.ZipFile(dest / "funnel-brief.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("funnel.json", json.dumps(funnel, indent=2))
        archive.writestr("BUILD-PROMPT.md", "Build an original accessible funnel using this graph and copy. Use verified provider webhooks for delivery. Never unlock downloads from browser success parameters. Ask for real business/refund details before publishing.")
    return str(dest.resolve())


def pdf_export(store, job_id, destination):
    try:
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_LEFT
    except ImportError as exc:
        raise ValueError("Install PDF support: pip install -e .[pdf]") from exc
    job = store.job(job_id)
    if job["state"] != "ready":
        raise ValueError("Wait for the job to become ready.")
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    for name in ("BodyText", "Normal"):
        styles[name].fontSize = 11
        styles[name].leading = 17
        styles[name].alignment = TA_LEFT
    styles["Title"].textColor = colors.HexColor("#214c3b")
    styles["Heading2"].spaceBefore = 18
    flow = [Paragraph("OPEN SERVICE AGENTS / EDITORIAL DRAFT", styles["Heading3"]), Spacer(1, 40),
            Paragraph(html.escape(job["brief"]["topic"]), styles["Title"]), Spacer(1, 24),
            Paragraph(html.escape(job["brief"]["audience"]), styles["BodyText"]), Spacer(1, 36),
            Paragraph("Demonstration fixture - not for sale." if job["provider"] == "demo" else "Review accuracy, attribution, and reader outcomes before publication.", styles["BodyText"]), PageBreak()]
    for line in manuscript(job).splitlines():
        if not line.strip():
            flow.append(Spacer(1, 7))
            continue
        value = line.replace("\u2011", "-").replace("\u2013", "-").replace("\u2014", "-")
        style = "BodyText"
        if value.startswith("# "):
            continue
        if value.startswith("## "):
            style, value = "Heading2", value[3:]
        elif value.startswith("### "):
            style, value = "Heading3", value[4:]
        flow.append(Paragraph(html.escape(value), styles[style]))
    def footer(canvas, doc):
        canvas.setFont("Helvetica", 9)
        canvas.setFillColor(colors.HexColor("#60736b"))
        canvas.drawString(48, 30, "Open Service Agents - draft edition")
        canvas.drawRightString(547, 30, str(doc.page))
    SimpleDocTemplate(str(destination), pagesize=(595, 842), rightMargin=48, leftMargin=48,
                      topMargin=48, bottomMargin=52, title=job["brief"]["topic"], author="Open Service Agents").build(flow, onFirstPage=footer, onLaterPages=footer)
    return str(destination.resolve())
