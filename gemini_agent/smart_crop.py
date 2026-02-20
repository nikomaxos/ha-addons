from PIL import Image, ImageDraw

def process_smart_icon(input_path, output_path):
    print(f"Processing {input_path}...")
    img = Image.open(input_path).convert("RGBA")
    data = img.getdata()
    
    new_data = []
    # Identify background (assuming it's very dark/blackish)
    # We will make pixels that are very dark transparent
    margin = 40 # threshold for dark
    for item in data:
        # item is (R, G, B, A)
        if item[0] < margin and item[1] < margin and item[2] < margin:
            new_data.append((0, 0, 0, 0)) # transparent
        else:
            new_data.append(item)
            
    img.putdata(new_data)
    
    # Get bounding box of the non-transparent pixels
    bbox = img.getbbox()
    if bbox:
        # Crop to the bounding box
        img_cropped = img.crop(bbox)
        
        # We need it to be square for Home Assistant (e.g. 512x512)
        # Find the max dimension
        max_dim = max(img_cropped.width, img_cropped.height)
        
        # Create a new transparent square image
        sq_img = Image.new("RGBA", (max_dim, max_dim), (0, 0, 0, 0))
        
        # Paste the cropped image into the center of the square
        offset_x = (max_dim - img_cropped.width) // 2
        offset_y = (max_dim - img_cropped.height) // 2
        sq_img.paste(img_cropped, (offset_x, offset_y))
        
        # Resize to standard icon size (e.g., 512x512) with a small 5% padding
        target_size = 512
        sq_img = sq_img.resize((target_size, target_size), Image.Resampling.LANCZOS)
        
        # Optional: Add padding inside so it's not strictly edge-to-edge
        padding = 10
        final_img = Image.new("RGBA", (target_size, target_size), (0, 0, 0, 0))
        small_sq = sq_img.resize((target_size - 2*padding, target_size - 2*padding), Image.Resampling.LANCZOS)
        final_img.paste(small_sq, (padding, padding))
        
        final_img.save(output_path, "PNG")
        print(f"Saved optimized logo to {output_path}")
    else:
        print("Could not find bounding box.")

try:
    # We will process the original generated image, which I assume is still roughly in the working dir.
    # But to be safe, we have c:\Dev\ha-ai-middleware\gemini_agent\icon.png
    # Wait, icon.png currently has the circular crop. I will use it, 
    # but the background might still be there inside the circle.
    # Let's process the logo.png which should be the same.
    process_smart_icon(r"c:\Dev\ha-ai-middleware\gemini_agent\icon.png", r"c:\Dev\ha-ai-middleware\gemini_agent\icon.png")
    process_smart_icon(r"c:\Dev\ha-ai-middleware\gemini_agent\logo.png", r"c:\Dev\ha-ai-middleware\gemini_agent\logo.png")
except Exception as e:
    print(f"Error: {e}")
