from src.knowledge.embeddings import LocalHashEmbeddingClient, cosine_similarity


def test_local_hash_embeddings_are_deterministic() -> None:
    client = LocalHashEmbeddingClient(dimension=64)
    first = client.embed(["market structure bos fvg"])[0]
    second = client.embed(["market structure bos fvg"])[0]
    assert first == second
    assert cosine_similarity(first, second) > 0.99
