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
