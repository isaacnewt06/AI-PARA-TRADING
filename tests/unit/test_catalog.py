from src.telegram.catalog import TelegramCatalogClassifier, enrich_payload_for_catalog


def test_catalog_detects_external_link_providers() -> None:
    links = TelegramCatalogClassifier.detect_external_links(
        "Curso completo: https://mega.nz/folder/abc y mirror https://drive.google.com/file/d/123/view"
    )

    assert [link.provider for link in links] == ["mega", "google_drive"]
    assert all(link.status if hasattr(link, "status") else True for link in links)


def test_catalog_prioritizes_documents_over_archives() -> None:
    assert TelegramCatalogClassifier.priority_for_file("modulo_1.pdf", "document") == "high"
    assert TelegramCatalogClassifier.priority_for_file("pack_indicadores.rar", "generic") == "low"


def test_catalog_queues_archives() -> None:
    assert TelegramCatalogClassifier.initial_file_status("curso.zip", "generic", catalog_only=False) == "queued"
    assert TelegramCatalogClassifier.initial_file_status("clase.pdf", "document", catalog_only=True) == "queued"


def test_enrich_payload_for_catalog_serializes_external_links_with_slots_dataclass() -> None:
    payload = {"content_type": "text", "file_name": None}

    enriched = enrich_payload_for_catalog(
        payload,
        "Material: https://mega.nz/folder/abc y espejo https://drive.google.com/file/d/123/view",
    )

    assert len(enriched["external_links"]) == 2
    assert enriched["external_links"][0]["provider"] == "mega"
    assert enriched["external_links"][1]["provider"] == "google_drive"
