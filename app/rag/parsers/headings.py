import re


def heading_level(text):
    """Conservative headings for plain/un-styled documents, without subject-specific rules."""
    text = text.strip()
    if not text or len(text) > 100:
        return None
    if re.match(r"^(?:第\s*[一二三四五六七八九十百\d]+\s*[章篇]|chapter\s+\d+\b)", text, re.I):
        return 1
    if re.match(r"^第\s*[一二三四五六七八九十百\d]+\s*节", text):
        return 2
    match = re.match(r"^(\d+(?:\.\d+){0,3})[\s、．.]+[^\d\s]", text)
    if match and not re.search(r"[。！？?]", text):
        return match[1].count(".") + 1
    return None
