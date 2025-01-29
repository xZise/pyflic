from PIL import Image
from fli_encode import FlicFile, Color

image_files = ["frame1.png", "frame2.png", "frame3.png"]
palette = []
frames = []
size = None

for image_file in image_files:
    with Image.open(image_file) as im:
        if size is None:
            size = (im.width, im.height)
        elif size != (im.width, im.height):
            raise ValueError("Images must have the same size")

        data = bytearray(b"\0" * im.width * im.height)
        for pixel_index, pixel in enumerate(im.getdata()):
            pixel = pixel[:3]
            for i, color in enumerate(palette):
                if pixel == color:
                    palette_index = i
                    break
            else:
                palette_index = len(palette)
                palette.append(pixel)
            data[pixel_index] = palette_index

        frames.append(bytes(data))


flic = FlicFile(*size, delay=500)
flic.set_palette([Color(*color) for color in palette])
for i, frame in enumerate(frames):
    flic.add_frame(frame)
    flic.add_frame(None)

with open("generated.flc", "wb") as dest:
    flic.write(dest)