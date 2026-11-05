from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re


class DocumentLoadError(ValueError):
    """A document could not be read or did not contain usable text."""


@dataclass
class Document:
    id: str
    name: str
    document_type: str
    source_path: str
    category: str
    text: str
    ingested_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict[str, str] = field(default_factory=dict)


def normalize_text(text: str) -> str:
    text = text.replace("\x00", " ").replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(re.sub(r"[\t\f\v ]+", " ", line).strip() for line in text.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _category(path: Path) -> str:
    return re.sub(r"[^a-z0-9_-]+", "_", path.parent.name.lower()).strip("_") or "general_faq"


def load_document(path: Path, root: Path | None = None) -> Document:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix not in {".pdf", ".md", ".txt"}:
        raise DocumentLoadError(f"Unsupported document type: {suffix or '(none)'}")
    try:
        if suffix == ".pdf":
            try:
                from pypdf import PdfReader
            except ImportError as exc:
                raise DocumentLoadError("PDF support requires the pypdf dependency.") from exc
            reader = PdfReader(str(path), strict=False)
            text = "\n\n".join(page.extract_text() or "" for page in reader.pages)
        else:
            text = path.read_text(encoding="utf-8-sig")
    except DocumentLoadError:
        raise
    except Exception as exc:
        raise DocumentLoadError(f"Could not read {path.name}: {exc}") from exc
    text = normalize_text(text)
    if not text:
        raise DocumentLoadError(f"Document contains no extractable text: {path.name}")
    try:
        source = path.resolve().relative_to(root.resolve()).as_posix() if root else path.name
    except ValueError:
        source = path.name
    document_id = hashlib.sha256(source.encode("utf-8")).hexdigest()[:24]
    return Document(document_id, path.name, suffix[1:], source, _category(path), text)


def load_directory(directory: Path) -> tuple[list[Document], list[dict[str, str]]]:
    directory = Path(directory)
    documents: list[Document] = []
    errors: list[dict[str, str]] = []
    if not directory.exists():
        return documents, [{"file": directory.name, "error": "Knowledge directory does not exist."}]
    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue
        try:
            documents.append(load_document(path, directory))
        except DocumentLoadError as exc:
            errors.append({"file": path.name, "error": str(exc)})
    return documents, errors
