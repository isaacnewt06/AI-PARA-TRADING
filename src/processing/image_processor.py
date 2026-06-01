"""Image metadata extraction and lightweight categorization."""

from __future__ import annotations

from pathlib import Path

from PIL import Image
from sqlalchemy.orm import Session

from src.core.logging import get_logger
from src.db.models.file_asset import FileAsset

logger = get_logger(__name__)


class ImageProcessor:
    """Basic image inspection for future CV and OCR pipelines."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def process(self, file_asset: FileAsset) -> str:
        with Image.open(Path(file_asset.stored_path)) as image:
            width, height = image.size
        label = self._classify(width=width, height=height, file_name=file_asset.file_name)
        file_asset.status = f"image:{label}"
        self.session.add(file_asset)
        self.session.flush()
        logger.info("Processed image %s classified as %s", file_asset.file_name, label)
        return label

    @staticmethod
    def _classify(*, width: int, height: int, file_name: str) -> str:
        lower = file_name.lower()
        if "chart" in lower or "setup" in lower:
            return "grafico"
        if "promo" in lower or "vip" in lower:
            return "flyer_promocional"
        if width > height * 1.7:
            return "tabla"
        if height > width:
            return "captura_trading"
        return "texto"
