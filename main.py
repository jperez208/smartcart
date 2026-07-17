import os
import cv2
import pytesseract

RECEIPT_FOLDER = "receipts"

# Ensure the folder exists to avoid crashes
if not os.path.exists(RECEIPT_FOLDER):
    print(f"Error: The folder '{RECEIPT_FOLDER}' does not exist.")
    exit()

for file in os.listdir(RECEIPT_FOLDER):
    if file.lower().endswith((".jpg", ".png", ".jpeg")):
        path = os.path.join(RECEIPT_FOLDER, file)
        
        # 1. Load image natively with OpenCV
        img = cv2.imread(path)
        if img is None:
            print(f"Skipping {file}: Could not read image.")
            continue
            
        # 2. Preprocess for OCR
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)
        
        # 3. Extract text
        text = pytesseract.image_to_string(thresh)
        
        print(f"\n--- {file} (Lines with Numbers) ---")
        lines = text.split("\n")
        for line in lines:
            # FIXED: Checks individual characters inside the current line
            if any(char.isdigit() for char in line):
                # Clean up whitespace before printing
                cleaned_line = line.strip()
                if cleaned_line:
                    print(cleaned_line)
                    
        print(f"\n--- Full Text Raw: {file} ---")
        print(text)
