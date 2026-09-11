"""Validate small explicit inputs before any network request or model invocation."""
import re
import json
from urllib.parse import urlparse


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", value):
        raise ValueError("Identifier must contain lowercase letters, numbers, '-' or '_' (max 64).")
    return value


def text(value, name, limit=20000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{name} must be nonempty text, at most {limit} characters.")
    return value.strip()


def email(value):
    if not isinstance(value, str) or not re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+", value) or len(value) > 254:
        raise ValueError("Invalid email address.")
    return value.lower()


def brief(data):
    if not isinstance(data, dict):
        raise ValueError("Brief must be a JSON object.")
    clean = {"id": identifier(data.get("id")), "topic": text(data.get("topic"), "topic", 300),
             "audience": text(data.get("audience"), "audience", 500),
             "problem": text(data.get("problem"), "problem", 1000),
             "format": data.get("format", "ebook"), "sources": [], "creators": []}
    if clean["format"] not in ("ebook", "workbook", "course", "coaching"):
        raise ValueError("Format must be ebook, workbook, course, or coaching.")
    count = data.get('chapter_count', 3)
    if type(count) is not int or not 3 <= count <= 12:
        raise ValueError('Choose 3-12 chapters.')
    clean['chapter_count'] = count
    if not isinstance(data.get("sources"), list) or not 1 <= len(data["sources"]) <= 20:
        raise ValueError("Supply 1-20 actual research sources; no invented research.")
    for i, source in enumerate(data["sources"], 1):
        url = text(source.get("url"), "source URL", 2048)
        if urlparse(url).scheme not in ("https", "http"):
            raise ValueError("Source URL must be HTTP(S); URLs are citations, never automatically fetched.")
        rights = source.get("rights", "public_reference")
        if rights not in ("owned", "licensed", "permission", "public_reference"):
            raise ValueError("Unknown source rights.")
        clean["sources"].append({"id": f"S{i}", "title": text(source.get("title"), "title", 300),
            "url": url, "text": text(source.get("text"), "source text", 5000), "rights": rights})
    creators = data.get("creators", [])
    if not isinstance(creators, list) or len(creators) > 30:
        raise ValueError("At most 30 supplied creators per project.")
    for creator in creators:
        clean["creators"].append({"name": text(creator.get("name"), "creator name", 150),
            "profile_url": text(creator.get("profile_url"), "profile URL", 2048),
            "niche": text(creator.get("niche"), "creator niche", 500),
            "audience_notes": text(creator.get("audience_notes"), "audience notes", 2000),
            "email": email(creator["email"]) if creator.get("email") else None})
    total_context = sum(len(s["text"]) for s in clean["sources"]) + sum(len(c["audience_notes"]) for c in clean["creators"])
    if total_context > 16000:
        raise ValueError("Combined source text and creator notes exceed 16000 characters; split into focused projects.")
    if len(json.dumps(clean, ensure_ascii=False)) > 22000:
        raise ValueError('Total brief metadata and evidence exceed 22000 characters; shorten the brief.')
    return clean


def artifact(data, source_ids):
    if not isinstance(data, dict):
        raise ValueError("Model must return a JSON object.")
    title = text(data.get("title"), "artifact title", 200)
    body = text(data.get("body"), "artifact body", 40000)
    citations = data.get("citations")
    if not isinstance(citations, list) or not citations or any(not isinstance(s, str) or s not in source_ids for s in citations):
        raise ValueError("Artifact must cite supplied source IDs only.")
    return {"title": title, "body": body, "citations": sorted(set(citations))}
