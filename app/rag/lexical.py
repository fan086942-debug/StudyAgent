"""Scoped keyword retrieval for short topics and questions in slide-style documents."""

import math
import re
import unicodedata
from collections import Counter


def normalized(text):
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", text).casefold())


def query_terms(question):
    parts = re.split(
        r"章节(?:中)?(?:的)?|一节(?:中)?(?:的)?|(?:中|里)的|包括|包含|分为|有哪|几个|哪些|"
        r"是什么|什么是|为什么|如何|怎么|请问|请解释|解释一下|说明|总结|概括|简述|"
        r"几个方面|哪些方面|方面|问题|[，,。？?：:；;]", question,
    )
    return list(dict.fromkeys(
        term for part in parts
        if len(term := normalized(part).strip()) >= 2
        and term not in {"操作", "问题", "这个", "一下", "什么", "多少", "的"}
    ))


def keyword_ranking(rows, question):
    terms = query_terms(question)
    texts = [normalized(chunk.text) for chunk, _ in rows]
    frequencies = {term: sum(term in text for text in texts) for term in terms}
    weights = {
        term: math.log(1 + len(rows) / count) ** 2 * math.sqrt(min(len(term), 20))
        for term, count in frequencies.items() if count
    }
    ranked = []
    for row, text in zip(rows, texts):
        score = sum(weight for term, weight in weights.items() if term in text)
        if score:
            ranked.append((score, row))
    return [row for _, row in sorted(ranked, key=lambda item: -item[0])]


def numbered_headings(text):
    return re.findall(r"(?m)^\s*(\d+(?:\.\d+){1,3})\s+([^\r\n]{2,100})", text)


def topic_section(rows, topic):
    """Expand a numbered section outline into its body, excluding repeated chapter TOCs."""
    term = normalized(topic)
    by_doc = {}
    for row in rows:
        by_doc.setdefault(row[1].id, []).append(row)
    result = []
    for own in by_doc.values():
        expanded = False
        for index, (chunk, _) in enumerate(own):
            headings = numbered_headings(chunk.text)
            counts = Counter(number.count(".") for number, _ in headings)
            anchors = [(number, title) for number, title in headings
                       if term in normalized(title) and counts[number.count(".")] == 1]
            if not anchors:
                continue
            number, _ = anchors[0]
            depth = number.count(".")
            end = index + 1
            while end < len(own):
                following = numbered_headings(own[end][0].text)
                if any(n.count(".") <= depth and n != number for n, _ in following):
                    break
                if (own[end][1].id != chunk.document_id
                        or own[end][0].chapter != chunk.chapter):
                    break
                end += 1
            body = [row for row in own[index:end] if len(numbered_headings(row[0].text)) < 3]
            if body:
                result.extend(body)
                expanded = True
                break
        if not expanded:
            # Word headings and slide titles already carry parser-provided scope.
            result.extend(row for row in own if term in normalized(
                row[0].section or row[0].chapter or ""))
    return result
