from collections.abc import Sequence


def assemble_context(chunks: Sequence[dict], max_chars: int = 12000) -> str:
    """Format source-labelled evidence, preserving full selected chunks up to a cap."""
    if max_chars < 1:
        return ""
    sections: list[str] = []
    used = 0
    seen: set[str] = set()
    for chunk in chunks:
        metadata = chunk.get("metadata", {})
        key = chunk.get("id") or f"{metadata.get('document_id')}:{chunk.get('text')}"
        if key in seen:
            continue
        seen.add(key)
        source = metadata.get("source_path") or metadata.get("document_name", "Unknown document")
        name = metadata.get("document_name", "Unknown document")
        category = metadata.get("category", "general")
        heading = f"[Source: {source} | Document: {name} | Category: {category}]\n"
        body = str(chunk.get("text", "")).strip()
        if not body:
            continue
        section = heading + body
        remaining = max_chars - used - (2 if sections else 0)
        if remaining <= len(heading):
            break
        if len(section) > remaining:
            if not sections:
                section = heading + body[:remaining - len(heading)].rstrip()
            else:
                break
        sections.append(section)
        used += len(section) + (2 if len(sections) > 1 else 0)
    return "\n\n".join(sections)
