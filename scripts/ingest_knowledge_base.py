"""Index configured knowledge documents into persistent ChromaDB."""

import argparse
import json
import logging

from app.config import settings
from app.knowledge.service import build_knowledge_service


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", help="Override configured knowledge directory")
    args = parser.parse_args()
    if args.directory:
        settings.knowledge_base_dir = args.directory
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    print(json.dumps(build_knowledge_service(settings).ingest_directory(), indent=2))


if __name__ == "__main__":
    main()
