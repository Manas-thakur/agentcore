# HNSW Vector Index

Hierarchical Navigable Small World (HNSW) is a graph-based approximate nearest neighbor index published by Malkov and Yashunin in 2016. It is the default index in many vector databases because it offers high recall with logarithmic search complexity.

## How it works

HNSW builds a multi-layer proximity graph. Every vector is inserted at a random maximum layer drawn from an exponentially decaying distribution, so upper layers are sparse and act like express lanes. Search starts at the entry point on the top layer, greedily descends layer by layer, and runs a beam search with width ef on the bottom layer.

## Parameters

The parameter M controls how many neighbors each node keeps; layer zero keeps 2*M. A larger ef_construction builds a better graph more slowly. A larger ef_search increases recall at the cost of latency. Typical values are M=16, ef_construction=200 and ef_search=64.

## Trade-offs

HNSW uses more memory than IVF because it stores the graph links, and deletions are usually implemented as tombstones. IVF indexes train k-means centroids and only scan the nprobe closest clusters, which uses less memory but needs a training step.
