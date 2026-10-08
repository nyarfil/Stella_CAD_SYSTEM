# Geometry encoder v1 evaluation

Pool: 5924 held-out test cases with annotations; 2000 queries; seed 0. Relevance: test cases linked to any keyword with Qwen cosine >= 0.7 to the query keyword; gain = max cosine.

| system | Recall@10 | Recall@50 | MRR | nDCG@10 |
|---|---|---|---|---|
| encoder | 0.0078 [0.0068, 0.0093] | 0.0329 [0.0308, 0.0352] | 0.4359 [0.4191, 0.4522] | 0.2446 [0.2343, 0.2550] |
| handcrafted_knn | 0.0088 [0.0076, 0.0103] | 0.0318 [0.0298, 0.0340] | 0.4740 [0.4568, 0.4913] | 0.2569 [0.2470, 0.2677] |
| text_search_reference | 0.1190 [0.1086, 0.1301] | 0.2938 [0.2795, 0.3088] | 1.0000 [1.0000, 1.0000] | 1.0000 [1.0000, 1.0000] |
| random | 0.0017 [0.0017, 0.0017] | 0.0084 [0.0084, 0.0084] | 0.2349 [0.2271, 0.2427] | 0.0919 [0.0877, 0.0962] |

Shape-to-shape mean Jaccard (top-10 neighbours): encoder 0.0417 [0.0397, 0.0436]; handcrafted 0.0381 [0.0362, 0.0399]; random 0.0139 [0.0133, 0.0144]

Acceptance (encoder beats handcrafted_knn on nDCG@10 and Recall@50 with non-overlapping 95% CIs): **NOT accepted (experimental)**

text_search_reference uses the test annotations and relevance is defined by the same rule, so it is an upper bound, not a competitor.
