import cv2
import numpy as np
import os


# =====================================================
# Configuration
# =====================================================

TARGET_WIDTH = 2000

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
    """

    height, width = image.shape[:2]

    if width == TARGET_WIDTH:
        return image


    scale = TARGET_WIDTH / width


    resized = cv2.resize(
        image,
        None,
        fx=scale,
        fy=scale,
        interpolation=cv2.INTER_CUBIC
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
    
if __name__ == "__main__":

    img_path = "./receipts/test_receipt.jpg"

    img = cv2.imread(img_path)

    if img is None:
        print("Could not load:", img_path)
        exit()

    print("Loaded image:", img.shape)

    corrected = perspective_correct(img)
    resized = resize_receipt(corrected)
    enhanced = enhanced_receipt(resized)


    cv2.imwrite(
        "debug_warped.jpg",
        enhanced
    )


    print(
        "Saved debug_warped.jpg",
        enhanced.shape
    )
