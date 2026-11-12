# Hybrid Search with BM25 and Dense Vectors

Hybrid search combines lexical retrieval with dense vector retrieval. BM25 is excellent at exact keyword matches such as error codes, function names and rare terms. Dense embeddings capture meaning and paraphrases. Combining both usually beats either one alone.

## BM25

BM25 scores a document by summing, for every query term, the inverse document frequency of the term multiplied by a saturated term frequency. The parameter k1 controls term frequency saturation and b controls document length normalization. Common defaults are k1=1.5 and b=0.75.

## Reciprocal Rank Fusion

Reciprocal rank fusion (RRF) merges ranked lists without needing comparable scores. Each document receives the sum of 1/(k + rank) over every list it appears in, with k typically set to 60. RRF is robust because BM25 scores and cosine similarities live on completely different scales.

## Reranking

After fusion, a reranker reorders the top candidates. Cross-encoders are the most accurate rerankers, while lexical rerankers based on query term coverage and proximity are cheap and need no model.
