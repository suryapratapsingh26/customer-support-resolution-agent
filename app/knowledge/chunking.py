from dataclasses import dataclass
import hashlib
import re

from app.knowledge.loaders import Document


@dataclass
class Chunk:
    id: str
    document_id: str
    text: str
    metadata: dict[str, str | int]


class TextChunker:
    def __init__(self, chunk_size: int = 900, overlap: int = 120):
        if chunk_size < 1 or overlap < 0 or overlap >= chunk_size:
            raise ValueError("Require chunk_size > 0 and 0 <= overlap < chunk_size.")
        self.chunk_size, self.overlap = chunk_size, overlap

    def split(self, document: Document) -> list[Chunk]:
        text = document.text.strip()
        if not text:
            return []
        pieces: list[str] = []
        start = 0
        while start < len(text):
            end = min(start + self.chunk_size, len(text))
            if end < len(text):
                boundary = max(text.rfind("\n", start + self.chunk_size // 2, end), text.rfind(". ", start + self.chunk_size // 2, end))
                if boundary > start:
                    end = boundary + (1 if text[boundary] == "\n" else 2)
            piece = text[start:end].strip()
            if piece and (not pieces or piece != pieces[-1]):
                pieces.append(piece)
            if end >= len(text):
                break
            start = max(start + 1, end - self.overlap)
        result = []
        for index, piece in enumerate(pieces):
            chunk_id = hashlib.sha256(f"{document.id}:{index}:{piece}".encode()).hexdigest()[:32]
            result.append(Chunk(chunk_id, document.id, piece, {
                "document_id": document.id, "document_name": document.name,
                "document_type": document.document_type, "source_path": document.source_path,
                "category": document.category, "ingested_at": document.ingested_at,
                "chunk_index": index,
            }))
        return result
