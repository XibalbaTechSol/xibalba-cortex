"""Retrieval evaluation harness (Phase 0).

Measures how well a search backend finds the document a query is about, on our own data, so
"parity with Supermemory" is a number with a confidence interval rather than an impression.
A random-ranking control runs alongside every evaluation: if the control scores close to the
real engines, the dataset is too easy to tell them apart and the result means nothing.
"""
