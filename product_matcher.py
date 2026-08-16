```python
# product_matcher.py
#
# SmartCart product information and normalization helpers.
#
# IMPORTANT:
# This file does NOT compare receipt items to products.
# It does NOT open receipts.db or master.db.
#
# Its job is to:
#   - normalize product information
#   - normalize/validate identifiers
#   - extract possible identifiers from OCR text
#   - build standardized product observations
#
# Product comparison and master database creation will be handled
# separately by compare_products.py.


import re


# ---------------------------------------------------------------------------
# Identifier patterns
# ---------------------------------------------------------------------------

# UPC-A / GTIN-12
UPC_PATTERN = re.compile(
    r"(?<!\d)(\d{12})(?!\d)"
)

# EAN-13 / GTIN-13
EAN_PATTERN = re.compile(
    r"(?<!\d)(\d{13})(?!\d)"
)

# PLU codes are commonly 4 digits and sometimes 5 digits.
#
# NOTE:
# A 4/5 digit number on a receipt is NOT automatically a PLU.
# We return it as a possible PLU and let the comparison stage decide
# whether it is actually useful.
PLU_PATTERN = re.compile(
    r"(?<!\d)(\d{4,5})(?!\d)"
)


# ---------------------------------------------------------------------------
# Text normalization
# ---------------------------------------------------------------------------

def normalize_product_name(name):
    """
    Normalize a product name for comparison.

    This does NOT try to correct OCR errors.

    Example:

        "  COKE   ZERO 12PK  "
            ->
        "COKE ZERO 12PK"
    """

    if name is None:
        return ""

    name = str(name).upper()

    # Replace common separators with spaces.
    name = name.replace("|", " ")
    name = name.replace("{", " ")
    name = name.replace("}", " ")
    name = name.replace("«", " ")
    name = name.replace("»", " ")

    # Normalize whitespace.
    name = re.sub(r"\s+", " ", name)

    return name.strip()


def normalize_brand(brand):
    """
    Normalize a brand name.
    """

    if brand is None:
        return ""

    brand = str(brand).upper()
    brand = re.sub(r"\s+", " ", brand)

    return brand.strip()


def normalize_size(size):
    """
    Normalize a product size.

    This is intentionally conservative.
    We don't try to convert ounces, pounds, etc. yet.
    """

    if size is None:
        return ""

    size = str(size).upper()
    size = re.sub(r"\s+", " ", size)

    return size.strip()


# ---------------------------------------------------------------------------
# Identifier normalization
# ---------------------------------------------------------------------------

def normalize_identifier(identifier):
    """
    Keep only digits from an identifier.

    Examples:

        "0-12345-67890-5" -> "012345678905"
        "049000028904"    -> "049000028904"

    This is appropriate for UPC/EAN/PLU.

    SKU values can be alphanumeric, so use normalize_sku() for SKUs.
    """

    if identifier is None:
        return ""

    return re.sub(r"\D", "", str(identifier))


def normalize_sku(sku):
    """
    Normalize a SKU.

    Unlike UPC/EAN/PLU, SKUs may contain letters.

    Example:

        " SKU-123-A " -> "SKU123A"
    """

    if sku is None:
        return ""

    sku = str(sku).upper()

    # Remove whitespace and punctuation.
    sku = re.sub(r"[^A-Z0-9]", "", sku)

    return sku


# ---------------------------------------------------------------------------
# UPC / EAN validation
# ---------------------------------------------------------------------------

def valid_upc(upc):
    """
    Validate a UPC-A / GTIN-12 check digit.

    Returns True only when the identifier is exactly 12 digits
    and the check digit is correct.
    """

    upc = normalize_identifier(upc)

    if len(upc) != 12:
        return False

    try:
        digits = [int(char) for char in upc]
    except ValueError:
        return False

    # First 11 digits.
    odd_sum = sum(digits[0:11:2])
    even_sum = sum(digits[1:11:2])

    total = (odd_sum * 3) + even_sum

    calculated_check_digit = (
        10 - (total % 10)
    ) % 10

    return calculated_check_digit == digits[11]


def valid_ean13(ean):
    """
    Validate an EAN-13 / GTIN-13 check digit.

    Returns True only when the identifier is exactly 13 digits
    and the check digit is correct.
    """

    ean = normalize_identifier(ean)

    if len(ean) != 13:
        return False

    try:
        digits = [int(char) for char in ean]
    except ValueError:
        return False

    total = (
        sum(digits[0:12:2])
        + sum(digits[1:12:2]) * 3
    )

    calculated_check_digit = (
        10 - (total % 10)
    ) % 10

    return calculated_check_digit == digits[12]


# ---------------------------------------------------------------------------
# Identifier classification
# ---------------------------------------------------------------------------

def identifier_type(identifier):
    """
    Determine the likely identifier type based on length.

    This is only a basic classification.

    A 4/5 digit number is classified as a possible PLU.
    A SKU should normally be supplied separately because SKUs
    can be alphanumeric and vary by retailer.
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
# Identifier extraction from OCR
# ---------------------------------------------------------------------------

def extract_identifiers(line):
    """
    Extract possible UPC, EAN and PLU values from one OCR line.

    Returns a list of dictionaries.

    Example:

        extract_identifiers(
            "COKE ZERO 12PK 049000028904 6.49"
        )

    returns approximately:

        [
            {
                "identifier": "049000028904",
                "type": "UPC",
                "valid": True
            }
        ]

    IMPORTANT:
    This function does not decide whether an identifier is actually
    associated with the product. It only reports candidates.
    """

    if not line:
        return []

    results = []

    # -----------------------------------------------------------------------
    # EAN-13
    # -----------------------------------------------------------------------

    for match in EAN_PATTERN.finditer(str(line)):

        value = match.group(1)

        results.append(
            {
                "identifier": value,
                "type": "EAN",
                "valid": valid_ean13(value),
            }
        )

    # -----------------------------------------------------------------------
    # UPC-A
    # -----------------------------------------------------------------------

    for match in UPC_PATTERN.finditer(str(line)):

        value = match.group(1)

        # Avoid duplicate identifiers.
        if any(
            item["identifier"] == value
            for item in results
        ):
            continue

        results.append(
            {
                "identifier": value,
                "type": "UPC",
                "valid": valid_upc(value),
            }
        )

    # -----------------------------------------------------------------------
    # Possible PLU
    # -----------------------------------------------------------------------

    for match in PLU_PATTERN.finditer(str(line)):

        value = match.group(1)

        # Don't duplicate a value already found as UPC/EAN.
        if any(
            item["identifier"] == value
            for item in results
        ):
            continue

        results.append(
            {
                "identifier": value,
                "type": "PLU",
                "valid": True,
            }
        )

    return results


def extract_identifiers_from_lines(lines):
    """
    Extract possible identifiers from multiple OCR lines.

    Returns:

        [
            {
                "line": "...",
                "identifier": "...",
                "type": "UPC",
                "valid": True
            },
            ...
        ]
    """

    results = []

    if not lines:
        return results

    for line in lines:

        if not line:
            continue

        matches = extract_identifiers(line)

        for match in matches:

            results.append(
                {
                    "line": line,
                    "identifier": match["identifier"],
                    "type": match["type"],
                    "valid": match["valid"],
                }
            )

    return results


# ---------------------------------------------------------------------------
# Identifier selection
# ---------------------------------------------------------------------------

def get_best_identifier(line):
    """
    Return the strongest identifier candidate found in a line.

    Priority:

        1. Valid UPC
        2. Valid EAN
        3. PLU
        4. Invalid UPC/EAN
        5. None

    This does NOT perform product matching.
    """

    identifiers = extract_identifiers(line)

    if not identifiers:
        return None

    # Prefer valid UPC.
    for item in identifiers:
        if item["type"] == "UPC" and item["valid"]:
            return item

    # Then valid EAN.
    for item in identifiers:
        if item["type"] == "EAN" and item["valid"]:
            return item

    # Then PLU.
    for item in identifiers:
        if item["type"] == "PLU":
            return item

    # Finally return an invalid UPC/EAN candidate if one exists.
    return identifiers[0]


# ---------------------------------------------------------------------------
# Product observation
# ---------------------------------------------------------------------------

def build_product_observation(
    raw_name,
    clean_name=None,
    price=None,
    store=None,
    location=None,
    date=None,
):
    """
    Build a standardized product observation from one receipt item.

    This is the main function that compare_products.py can use later.

    Example result:

        {
            "raw_name": "COKE ZER0 12PK",
            "clean_name": "COKE ZER0 12PK",
            "normalized_name": "COKE ZER0 12PK",
            "price": 6.49,
            "store": "Walmart",
            "location": "Nampa, ID",
            "date": "08/15/2026",
            "identifier": None,
            "identifier_type": None,
            "identifier_valid": False
        }

    The original OCR name is preserved.
    """

    raw_name = "" if raw_name is None else str(raw_name)

    if clean_name is None:
        clean_name = raw_name

    normalized_name = normalize_product_name(clean_name)

    identifier = get_best_identifier(raw_name)

    observation = {
        "raw_name": raw_name,
        "clean_name": str(clean_name).strip(),
        "normalized_name": normalized_name,
        "price": price,
        "store": store,
        "location": location,
        "date": date,
        "identifier": None,
        "identifier_type": None,
        "identifier_valid": False,
    }

    if identifier:

        observation["identifier"] = identifier["identifier"]
        observation["identifier_type"] = identifier["type"]
        observation["identifier_valid"] = identifier["valid"]

    return observation


# ---------------------------------------------------------------------------
# Product record normalization
# ---------------------------------------------------------------------------

def normalize_product_record(
    canonical_name,
    brand=None,
    size=None,
    upc=None,
    ean=None,
    sku=None,
    plu=None,
):
    """
    Create a normalized product record.

    This function does not save anything to a database.

    It simply makes product information consistent before another
    module stores it.
    """

    record = {
        "canonical_name": normalize_product_name(canonical_name),
        "brand": normalize_brand(brand),
        "size": normalize_size(size),
        "upc": normalize_identifier(upc) or None,
        "ean": normalize_identifier(ean) or None,
        "sku": normalize_sku(sku) or None,
        "plu": normalize_identifier(plu) or None,
    }

    # Validate UPC/EAN when supplied.
    if record["upc"] and not valid_upc(record["upc"]):
        record["upc_valid"] = False
    else:
        record["upc_valid"] = bool(record["upc"])

    if record["ean"] and not valid_ean13(record["ean"]):
        record["ean_valid"] = False
    else:
        record["ean_valid"] = bool(record["ean"])

    return record


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def identifier_matches(identifier_a, identifier_b):
    """
    Compare two numeric identifiers after normalization.

    Useful later when comparing historical receipt observations.
    """

    a = normalize_identifier(identifier_a)
    b = normalize_identifier(identifier_b)

    if not a or not b:
        return False

    return a == b


def names_are_exact_match(name_a, name_b):
    """
    Exact comparison after product-name normalization.

    This is intentionally NOT fuzzy matching.
    Fuzzy/error matching belongs in compare_products.py.
    """

    a = normalize_product_name(name_a)
    b = normalize_product_name(name_b)

    if not a or not b:
        return False

    return a == b


# ---------------------------------------------------------------------------
# Compatibility helper
# ---------------------------------------------------------------------------

def identify_item(cur, raw_name, clean_name, price, store=None):
    """
    Compatibility placeholder for the old receipts_processor.py.

    The old project expected product_matcher.identify_item() to perform
    database matching.

    We are intentionally removing that behavior.

    New code should use build_product_observation() instead.

    This function is retained temporarily so that replacing this file
    does not immediately cause an ImportError if receipts_processor.py
    still imports identify_item.

    It does NOT query a database and does NOT claim to identify a product.
    """

    observation = build_product_observation(
        raw_name=raw_name,
        clean_name=clean_name,
        price=price,
        store=store,
    )

    return {
        "id": None,
        "identifier": observation["identifier"],
        "identifier_type": observation["identifier_type"],
        "identifier_valid": observation["identifier_valid"],
        "canonical_name": None,
        "brand": None,
        "size": None,
        "store": store,
        "confidence": 0.0,
        "match_method": None,
        "observation": observation,
    }


# ---------------------------------------------------------------------------
# Simple self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    print("SmartCart product_matcher self-test")
    print("-----------------------------------")

    test_lines = [
        "COKE ZERO 12PK 049000028904 6.49",
        "BANANAS 4011 1.29",
        "GV HNY BUNS 078742147420 F 1.98",
        "COKE ZER0 12PK 6.49",
    ]

    for line in test_lines:

        print()
        print(f"OCR: {line}")

        identifiers = extract_identifiers(line)

        for identifier in identifiers:

            print(
                f"  {identifier['type']}: "
                f"{identifier['identifier']} "
                f"(valid={identifier['valid']})"
            )

        observation = build_product_observation(
            raw_name=line,
            clean_name=line,
            price=None,
            store="Example Store",
            location="Example Location",
            date=None,
        )

        print(
            f"  normalized: "
            f"{observation['normalized_name']}"
        )

        print(
            f"  best identifier: "
            f"{observation['identifier'] or '-'} "
            f"({observation['identifier_type'] or '-'})"
        )
```
