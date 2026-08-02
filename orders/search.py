"""Product search for the quick-add box.

Matching is word-prefix based: typing "mil" finds "Whole milk", but "ilk"
finds nothing -- people type the start of a word, not the middle of one.
A near-miss still matches, so "nakpins" finds "Napkins".

The catalog is a coffee shop's, not a warehouse's, so ranking happens in
Python. That buys prefix and typo tolerance on plain SQLite with no search
extension. Worth revisiting if the catalog ever reaches a few thousand rows.
"""

import re
from difflib import SequenceMatcher

from .models import Product

WORD_RE = re.compile(r"\w+", re.UNICODE)

# Score tiers, lower is better.
PREFIX = 0.0
FUZZY = 1.0
SELLER_PENALTY = 0.5
NAME_STARTS_BONUS = 0.5

MIN_FUZZY_LEN = 3
MIN_FUZZY_RATIO = 0.72


def _words(text):
    return WORD_RE.findall(text.lower())


def _score_token(token, words):
    """Best score for one typed token against one product's words.

    Returns None when the token does not plausibly start any of them.
    """
    best = None
    for word in words:
        if word.startswith(token):
            # Prefer the tightest match: "oat" should rank "Oat milk" above
            # a hypothetical "Oatmeal biscuit".
            score = PREFIX + (len(word) - len(token)) / 100
        else:
            if len(token) < MIN_FUZZY_LEN:
                continue
            # Compare against the head of the word only, so this stays a
            # forgiving prefix match rather than a substring search.
            ratio = SequenceMatcher(None, token, word[: len(token)]).ratio()
            if ratio < MIN_FUZZY_RATIO:
                continue
            score = FUZZY + (1 - ratio)

        if best is None or score < best:
            best = score
    return best


def search_products(query, limit=8):
    """Active products matching every token in `query`, best match first."""
    tokens = _words(query)
    if not tokens:
        return []

    products = Product.objects.filter(
        is_active=True, seller__is_active=True
    ).select_related("seller")

    scored = []
    for product in products:
        name_words = _words(product.name)
        seller_words = _words(product.seller.name)

        total = 0.0
        for token in tokens:
            score = _score_token(token, name_words)
            if score is None:
                # Fall back to the seller name, ranked below any name match,
                # so typing "bertoli" still surfaces that supplier's products.
                score = _score_token(token, seller_words)
                if score is None:
                    break
                score += SELLER_PENALTY
            total += score
        else:
            if product.name.lower().startswith(query.strip().lower()):
                total -= NAME_STARTS_BONUS
            scored.append((total, product.name.lower(), product))

    scored.sort(key=lambda row: (row[0], row[1]))
    return [product for _, _, product in scored[:limit]]
