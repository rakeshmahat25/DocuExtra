import logging
from PIL import Image, ImageOps, ImageEnhance

logger = logging.getLogger(__name__)

def preprocess_image(image_path, output_path):
    """
    Cleans up and enhances an image for better OCR readability.
    Includes auto-rotation (using EXIF metadata), grayscaling, and contrast enhancement.
    """
    try:
        with Image.open(image_path) as img:
            # 1. Correct rotation based on EXIF tag
            img = ImageOps.exif_transpose(img)
            
            # Convert to RGB if it's in a different mode (like RGBA or Palette)
            if img.mode != "RGB":
                img = img.convert("RGB")
                
            # 2. Enhance contrast slightly to make text pop
            enhancer = ImageEnhance.Contrast(img)
            img = enhancer.enhance(1.4) # Make lines and letters crisper
            
            # 3. Enhance sharpness slightly
            sharpness = ImageEnhance.Sharpness(img)
            img = sharpness.enhance(1.2)
            
            # Save the processed image
            img.save(output_path, "PNG")
            logger.info(f"Successfully preprocessed image: {image_path} -> {output_path}")
            return True
    except Exception as e:
        logger.error(f"Failed to preprocess image {image_path}: {e}")
        # If it fails, copy the original file as output fallback
        try:
            with open(image_path, "rb") as src, open(output_path, "wb") as dst:
                dst.write(src.read())
            return False
        except Exception:
            return False
