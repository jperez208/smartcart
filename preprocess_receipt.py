import cv2
import numpy as np
import os


# =====================================================
# Configuration
# =====================================================

TARGET_WIDTH = 1600
MAX_WIDTH_BEFORE_DOWNSCALE = 2200

DEBUG_DIR = "debug_preprocess"


# =====================================================
# Order 4 corner points
# =====================================================

def order_points(pts):
    """
    Orders points as:
    
    top-left
    top-right
    bottom-right
    bottom-left
    """

    rect = np.zeros((4, 2), dtype="float32")

    # top-left has smallest sum
    # bottom-right has largest sum
    s = pts.sum(axis=1)

    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]

    # top-right has smallest difference
    # bottom-left has largest difference
    diff = np.diff(pts, axis=1)

    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]

    return rect



# =====================================================
# Perspective transform helper
# =====================================================

def four_point_transform(image, pts):
    """
    Takes four receipt corners and returns
    a flattened top-down receipt image.
    """

    rect = order_points(pts)

    (tl, tr, br, bl) = rect


    # Calculate new width

    width_a = np.linalg.norm(br - bl)
    width_b = np.linalg.norm(tr - tl)

    max_width = int(max(width_a, width_b))


    # Calculate new height

    height_a = np.linalg.norm(tr - br)
    height_b = np.linalg.norm(tl - bl)

    max_height = int(max(height_a, height_b))


    # Destination rectangle

    dst = np.array([
        [0, 0],
        [max_width - 1, 0],
        [max_width - 1, max_height - 1],
        [0, max_height - 1]
    ], dtype="float32")


    # Perspective matrix

    matrix = cv2.getPerspectiveTransform(
        rect,
        dst
    )


    warped = cv2.warpPerspective(
        image,
        matrix,
        (max_width, max_height)
    )


    return warped
    
# =====================================================
# Receipt Detection
# =====================================================

def detect_receipt(image):

    gray = cv2.cvtColor(
        image,
        cv2.COLOR_BGR2GRAY
    )


    # Improve contrast

    blur = cv2.GaussianBlur(
        gray,
        (5,5),
        0
    )


    # Separate receipt from background

    thresh = cv2.threshold(
        blur,
        0,
        255,
        cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )[1]


    # Make receipt edges stronger

    kernel = np.ones(
        (7,7),
        np.uint8
    )

    thresh = cv2.morphologyEx(
        thresh,
        cv2.MORPH_CLOSE,
        kernel,
        iterations=3
    )


    cv2.imwrite(
        "debug_threshold.jpg",
        thresh
    )


    contours, _ = cv2.findContours(
        thresh,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE
    )


    if not contours:
        return None


    contours = sorted(
        contours,
        key=cv2.contourArea,
        reverse=True
    )


    image_area = (
        image.shape[0] *
        image.shape[1]
    )


    print("Contours found:", len(contours))


    for i, contour in enumerate(contours[:10]):

        area = cv2.contourArea(contour)

        print(
            "Contour",
            i,
            "area:",
            area
        )


        if area < image_area * 0.10:
            continue


        perimeter = cv2.arcLength(
            contour,
            True
        )


        approx = cv2.approxPolyDP(
            contour,
            0.02 * perimeter,
            True
        )


        print(
            "points:",
            len(approx)
        )


        if len(approx) == 4:

            x, y, w, h = cv2.boundingRect(approx)

        # Reject full image border
            if (
                x <= 2
                and y <= 2
                and w >= image.shape[1] - 5
                and h >= image.shape[0] - 5
            ):
                print("Ignoring full image contour")
                continue


            print("FOUND RECEIPT")

            return approx.reshape(4,2)

    return None
# =====================================================
# Perspective Correction
# =====================================================

def perspective_correct(image):
    """
    Detects receipt and flattens it.
    
    If no receipt is detected,
    returns the original image.
    """

    corners = detect_receipt(image)


    if corners is None:

        print("No receipt boundary found. Using original image.")

        return image


    print("Receipt corners:")
    print(corners)


    corrected = four_point_transform(
        image,
        corners
    )


    return corrected

def resize_receipt(image):
    """
    Normalize receipt size for OCR.
    Only downscale huge images; leave smaller ones alone
    (upscaling for tiny text is handled in receipts_processor).
    """
    height, width = image.shape[:2]

    if width <= MAX_WIDTH_BEFORE_DOWNSCALE:
        return image

    scale = TARGET_WIDTH / width
    resized = cv2.resize(
        image,
        None,
        fx=scale,
        fy=scale,
        interpolation=cv2.INTER_AREA,
    )
    return resized


def enhance_receipt(image):
    """
    Improve contrast and text clarity.
    """

    gray = cv2.cvtColor(
        image,
        cv2.COLOR_BGR2GRAY
    )


    # Contrast enhancement

    clahe = cv2.createCLAHE(
        clipLimit=2.5,
        tileGridSize=(8,8)
    )

    enhanced = clahe.apply(gray)


    # Remove noise

    enhanced = cv2.fastNlMeansDenoising(
        enhanced,
        None,
        10,
        7,
        21
    )


    # Sharpen text

    kernel = np.array([
        [-1,-1,-1],
        [-1, 9,-1],
        [-1,-1,-1]
    ])

    enhanced = cv2.filter2D(
        enhanced,
        -1,
        kernel
    )


    return enhanced

# =====================================================
# Deskew Receipt
# =====================================================

def deskew_receipt(image):
    """
    Detects text angle and rotates image
    to make text horizontal.
    """

    # Make sure we are working with grayscale

    if len(image.shape) == 3:
        gray = cv2.cvtColor(
            image,
            cv2.COLOR_BGR2GRAY
        )
    else:
        gray = image.copy()


    # Threshold text

    thresh = cv2.threshold(
        gray,
        0,
        255,
        cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
    )[1]


    # Find text pixel locations

    coords = np.column_stack(
        np.where(thresh > 0)
    )


    if len(coords) < 20:
        print("Not enough text for deskew.")
        return image


    # Calculate angle

    angle = cv2.minAreaRect(coords)[-1]


    if angle < -45:
        angle = -(90 + angle)
    else:
        angle = -angle


    print("Detected deskew angle:", angle)


    # Ignore unrealistic rotations

    if abs(angle) < 0.5:
        return image


    if abs(angle) > 15:
        print("Ignoring extreme angle")
        return image


    height, width = image.shape[:2]


    center = (
        width // 2,
        height // 2
    )


    matrix = cv2.getRotationMatrix2D(
        center,
        angle,
        1.0
    )


    rotated = cv2.warpAffine(
        image,
        matrix,
        (width, height),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE
    )


    return rotated

# =====================================================
# Crop Empty Borders
# =====================================================

def crop_borders(image, padding=30):
    """
    Removes large empty areas around text.
    Keeps a small border for OCR.
    """

    if len(image.shape) == 3:

        gray = cv2.cvtColor(
            image,
            cv2.COLOR_BGR2GRAY
        )

    else:

        gray = image.copy()


    # Find text

    thresh = cv2.threshold(
        gray,
        0,
        255,
        cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
    )[1]


    coords = cv2.findNonZero(
        thresh
    )


    if coords is None:
        print("No text found for cropping.")
        return image


    x, y, w, h = cv2.boundingRect(
        coords
    )


    height, width = gray.shape


    # Add padding

    x1 = max(
        x - padding,
        0
    )

    y1 = max(
        y - padding,
        0
    )

    x2 = min(
        x + w + padding,
        width
    )

    y2 = min(
        y + h + padding,
        height
    )


    cropped = image[
        y1:y2,
        x1:x2
    ]


    print(
        "Crop:",
        cropped.shape
    )


    return cropped

# =====================================================
# Generate OCR Variants
# =====================================================

def generate_variants(image):
    """
    Creates multiple OCR-ready images.

    Returns:
        [
            ("Gray", image),
            ("CLAHE", image),
            ("Otsu", image),
            ("Adaptive", image),
            ...
        ]
    """

    variants = []


    # Ensure grayscale

    if len(image.shape) == 3:

        gray = cv2.cvtColor(
            image,
            cv2.COLOR_BGR2GRAY
        )

    else:

        gray = image.copy()


    # -------------------------
    # Raw grayscale
    # -------------------------

    variants.append(
        (
            "Gray",
            gray
        )
    )


    # -------------------------
    # CLAHE
    # -------------------------

    clahe = cv2.createCLAHE(
        clipLimit=2.5,
        tileGridSize=(8,8)
    )

    clahe_img = clahe.apply(
        gray
    )


    variants.append(
        (
            "CLAHE",
            clahe_img
        )
    )


    # -------------------------
    # OTSU
    # -------------------------

    otsu = cv2.threshold(
        gray,
        0,
        255,
        cv2.THRESH_BINARY +
        cv2.THRESH_OTSU
    )[1]


    variants.append(
        (
            "Otsu",
            otsu
        )
    )


    # -------------------------
    # Adaptive threshold
    # -------------------------

    adaptive = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31,
        10
    )


    variants.append(
        (
            "Adaptive",
            adaptive
        )
    )


    # -------------------------
    # Adaptive inverted
    # -------------------------

    adaptive_inv = cv2.bitwise_not(
        adaptive
    )


   # variants.append(
   #     (
    #       "AdaptiveInv",
    #       adaptive_inv
    #    )
   # )


    # -------------------------
    # Morphological cleanup
    # -------------------------

    kernel = np.ones(
        (2,2),
        np.uint8
    )


    morph = cv2.morphologyEx(
        otsu,
        cv2.MORPH_CLOSE,
        kernel
    )


#    variants.append(
#        (
#            "Morph",
 #           morph
 #       )
  #  )


    return variants

# =====================================================
# Main Preprocessing Pipeline
# =====================================================

def preprocess_receipt(
    image,
    debug=False,
    debug_dir=DEBUG_DIR
):
    """
    Complete receipt preprocessing pipeline.

    Returns:
        [
            ("Gray", image),
            ("CLAHE", image),
            ("Otsu", image),
            ("Adaptive", image),
            ("AdaptiveInv", image),
            ("Morph", image)
        ]
    """


    if image is None:
        raise ValueError(
            "Invalid image supplied"
        )


    # ---------------------------------
    # Step 1: Perspective correction
    # ---------------------------------

    processed = perspective_correct(
        image
    )


    if debug:
        os.makedirs(
            debug_dir,
            exist_ok=True
        )

        cv2.imwrite(
            os.path.join(
                debug_dir,
                "01_perspective.jpg"
            ),
            processed
        )


    # ---------------------------------
    # Step 2: Resize
    # ---------------------------------

    processed = resize_receipt(
        processed
    )


    if debug:

        cv2.imwrite(
            os.path.join(
                debug_dir,
                "02_resize.jpg"
            ),
            processed
        )


    # ---------------------------------
    # Step 3: Enhance
    # ---------------------------------

    processed = enhance_receipt(
        processed
    )


    if debug:

        cv2.imwrite(
            os.path.join(
                debug_dir,
                "03_enhanced.jpg"
            ),
            processed
        )


    # ---------------------------------
    # Step 4: Deskew
    # ---------------------------------

    processed = deskew_receipt(
        processed
    )


    if debug:

        cv2.imwrite(
            os.path.join(
                debug_dir,
                "04_deskew.jpg"
            ),
            processed
        )


    # ---------------------------------
    # Step 5: Crop borders
    # ---------------------------------

    #processed = crop_borders(
   #     processed
    #)


    if debug:

        cv2.imwrite(
            os.path.join(
                debug_dir,
                "05_crop.jpg"
            ),
            processed
        )


    # ---------------------------------
    # Step 6: OCR variants
    # ---------------------------------

    variants = generate_variants(
        processed
    )


    if debug:

        for name, img in variants:

            cv2.imwrite(
                os.path.join(
                    debug_dir,
                    f"06_{name}.jpg"
                ),
                img
            )


    return variants
    
if __name__ == "__main__":

    img_path = "./receipts/test_receipt.jpg"


    img = cv2.imread(
        img_path
    )


    if img is None:

        print(
            "Could not load:",
            img_path
        )

        exit()


    print(
        "Loaded:",
        img.shape
    )


    variants = preprocess_receipt(
        img,
        debug=True
    )


    print("\nOCR Variants:")

    for name, image in variants:

        print(
            name,
            image.shape
        )
