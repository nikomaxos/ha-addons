from PIL import Image, ImageDraw

def process_icon(img_path):
    # Open image and ensure it has an alpha channel
    img = Image.open(img_path).convert("RGBA")
    
    # Create a circular mask
    mask = Image.new('L', img.size, 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0, img.size[0], img.size[1]), fill=255)
    
    # Apply the mask to the image's alpha channel
    result = img.copy()
    result.putalpha(mask)
    result.save(img_path, format="PNG")
    print(f"Processed: {img_path}")

try:
    process_icon(r"c:\Dev\ha-ai-middleware\gemini_agent\icon.png")
    process_icon(r"c:\Dev\ha-ai-middleware\gemini_agent\logo.png")
    print("Icons successfully made round with transparent corners.")
except Exception as e:
    print(f"Error: {e}")
