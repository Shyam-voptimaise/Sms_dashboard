from PIL import Image, ImageDraw
import time

# Define the liquid color and fill level
liquid_color = (255, 165, 0)  # Orange color (RGB)

def ladle_image_gen(liq_color):
    # Calculate the coordinates of the liquid area
    x1, y1 = 425, 1726
    x2, y2 = 1525, 1726
    x3, y3 = 309, 821
    x4, y4 = 1630, 800

    # Load the ladle image
    ladle_image = Image.open("LadleImages/Ladle_Image.jpg")
    # Create a copy of the ladle image to avoid modifying the original
    ladle_with_liquid = ladle_image.copy()

    # Create a drawing context to draw the liquid
    draw = ImageDraw.Draw(ladle_with_liquid)

    taper = x1-x3
    height = y1-y3
    for step in range(100):
        fill_level = step * 0.01
        ya = int(y1 - fill_level * y1)
        xa = int(x1 - (y1-ya) * taper/height)

        yb = int(y1 - fill_level * y1)
        xb = int(x2 + (y1-ya) * taper/height)

        # Draw the liquid based on the fill level
        draw.polygon(
            [(x1, y1), (x2, y2), (xb, yb), (xa, ya)],
            fill=liq_color
        )

        # Save the image with the liquid filling
        ladle_with_liquid.save(f"LadleImages/Ladle_Image_{step}.png")
        time.sleep(0.3)

ladle_image_gen(liquid_color)
# # Display the image (optional)
# ladle_with_liquid.show()