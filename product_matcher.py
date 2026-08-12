# product_matcher.py

import re


# ---------------------------------------------------------------------------
# Identifier patterns
# ---------------------------------------------------------------------------

# UPC-A / GTIN-12
UPC_PATTERN = re.compile(r"(?<!\d)(\d{12})(?!\d)")

# EAN-13 / GTIN-13
EAN_PATTERN = re.compile(r"(?<!\d)(\d{13})(?!\d)")

# Common PLU codes used for produce.
# Usually 4 or 5 digits, but we keep this conservative.
PLU_PATTERN = re.compile(r"(?<!\d)(\d{4,5})(?!\d)")


# ---------------------------------------------------------------------------
# Basic normalization
# ---------------------------------------------------------------------------

def normalize_identifier(identifier):
    """Keep only digits."""
    if identifier is None:
        return ""

    return re.sub(r"\D", "", str(identifier))


def identifier_type(identifier):
    """
    Guess the type of identifier based on its length.

    This is intentionally conservative. We can make this smarter later.
    """
    identifier = normalize_identifier(identifier)

    if len(identifier) == 12:
        return "UPC"

    if len(identifier) == 13:
        return "EAN"

    if len(identifier) in (4, 5):
        return "PLU"

    return "UNKNOWN"


# ---------------------------------------------------------------------------
# Extract identifiers from an OCR line
# ---------------------------------------------------------------------------

def extract_identifiers(line):
    """
    Extract possible UPC/EAN/PLU identifiers from one OCR line.

    Returns a list of dictionaries.

    Example:

        "GV HNY BUNS 078742147420 F 1.98"

    becomes approximately:

        [
            {
                "identifier": "078742147420",
                "type": "UPC"
            }
        ]
    """

    if not line:
        return []

    results = []

    # Look for 13-digit identifiers first.
    for match in EAN_PATTERN.finditer(line):
        value = match.group(1)

        results.append(
            {
                "identifier": value,
                "type": "EAN",
            }
        )

    # Then UPC.
    for match in UPC_PATTERN.finditer(line):
        value = match.group(1)

        # Don't duplicate something that was already classified.
        if not any(x["identifier"] == value for x in results):
            results.append(
                {
                    "identifier": value,
                    "type": "UPC",
                }
            )

    # PLU.
    #
    # We only add these when there isn't already a longer identifier
    # containing the same digits.
    for match in PLU_PATTERN.finditer(line):
        value = match.group(1)

        if not any(x["identifier"] == value for x in results):
            results.append(
                {
                    "identifier": value,
                    "type": "PLU",
                }
            )

    return results


# ---------------------------------------------------------------------------
# Extract identifiers from multiple OCR lines
# ---------------------------------------------------------------------------

def extract_identifiers_from_lines(lines):
    """
    Process a list of OCR lines.

    Returns:

        [
            {
                "line": "...",
                "identifier": "...",
                "type": "UPC"
            },
            ...
        ]
    """

    results = []

    for line in lines:
        matches = extract_identifiers(line)

        for match in matches:
            results.append(
                {
                    "line": line,
                    "identifier": match["identifier"],
                    "type": match["type"],
                }
            )

    return results


# ---------------------------------------------------------------------------
# Product matching framework
# ---------------------------------------------------------------------------

def find_product_by_identifier(cur, identifier):
    """
    Look for a known product using its identifier.

    This is intentionally a framework for now.

    It assumes the products table will eventually contain:
        upc
        sku
        plu
    """

    identifier = normalize_identifier(identifier)

    if not identifier:
        return None

    # UPC
    cur.execute(
        """
        SELECT id, canonical_name, brand, size
        FROM products
        WHERE upc = ?
        LIMIT 1
        """,
        (identifier,),
    )

    result = cur.fetchone()

    if result:
        return {
            "product_id": result[0],
            "canonical_name": result[1],
            "brand": result[2],
            "size": result[3],
            "match_method": "UPC",
            "confidence": 1.0,
        }

    # SKU
    cur.execute(
        """
        SELECT id, canonical_name, brand, size
        FROM products
        WHERE sku = ?
        LIMIT 1
        """,
        (identifier,),
    )

    result = cur.fetchone()

    if result:
        return {
            "product_id": result[0],
            "canonical_name": result[1],
            "brand": result[2],
            "size": result[3],
            "match_method": "SKU",
            "confidence": 1.0,
        }

    # PLU
    cur.execute(
        """
        SELECT id, canonical_name, brand, size
        FROM products
        WHERE plu = ?
        LIMIT 1
        """,
        (identifier,),
    )

    result = cur.fetchone()

    if result:
        return {
            "product_id": result[0],
            "canonical_name": result[1],
            "brand": result[2],
            "size": result[3],
            "match_method": "PLU",
            "confidence": 1.0,
        }

    return None


# ---------------------------------------------------------------------------
# Main matching entry point
# ---------------------------------------------------------------------------

def identify_item(cur, raw_name, clean_name, price):
    """
    Attempt to identify one receipt item.

    This currently does identifier matching only.

    Later we can add:
        1. exact name matching
        2. store-specific aliases
        3. fuzzy matching
        4. price validation
        5. brand/size matching
    """

    identifiers = extract_identifiers(raw_name)

    for identifier_info in identifiers:
        result = find_product_by_identifier(
            cur,
            identifier_info["identifier"],
        )

        if result:
            result["identifier"] = identifier_info["identifier"]
            result["identifier_type"] = identifier_info["type"]
            return result

    return {
        "product_id": None,
        "canonical_name": None,
        "brand": None,
        "size": None,
        "identifier": (
            identifiers[0]["identifier"]
            if identifiers
            else None
        ),
        "identifier_type": (
            identifiers[0]["type"]
            if identifiers
            else None
        ),
        "match_method": None,
        "confidence": 0.0,
    }
