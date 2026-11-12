# Citations in Retrieval-Augmented Generation

Retrieval-augmented generation (RAG) grounds model answers in retrieved documents. Good RAG systems number every retrieved passage and instruct the model to cite passages with markers such as [1] or [2].

## Verifying citations

Citations can be checked after generation. A citation is invalid when it points to a passage number that was never provided. A citation is unsupported when the cited passage shares too few content words with the claim. Flagging unsupported citations reduces hallucinated references.

## Chunking

Documents are split into chunks before indexing. Fixed-size chunking is simple, recursive chunking respects paragraphs and sentences, and markdown-aware chunking keeps sections together and records the heading path of every chunk. Chunks of 500 to 1000 characters with some overlap work well for most corpora.
