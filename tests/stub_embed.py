"""Stand-in embedder for tests.

Production search uses a local fastembed model. This double only has to place
a paraphrase and its source chunk on the same vector, and an unrelated chunk
on another, so the vector lane can be tested without downloading weights.
"""

import numpy as np

_TOPICS = (
    (("subscription", "invoic", "charged", "billing", "bill", "annual", "customer"), 0),
    (("button", "rounded", "color", "css", "blue"), 1),
)


class LexiconEmbedder:
    name = "lexicon-stub"
    dim = 4

    def embed(self, texts: list[str]) -> np.ndarray:
        rows = []
        for text in texts:
            vector = np.zeros(self.dim, dtype=np.float32)
            lowered = text.lower()
            for words, index in _TOPICS:
                if any(word in lowered for word in words):
                    vector[index] = 1.0
            if not vector.any():
                vector[2] = 1.0
            rows.append(vector)
        matrix = np.vstack(rows)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return matrix / norms
