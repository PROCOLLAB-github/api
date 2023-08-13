import webp
from PIL import Image


def convert_image_to_webp(image, quality: int = 70):
    config = webp.WebPConfig.new(preset=webp.WebPPreset.PHOTO, quality=quality)
    pil_image = Image.open(image.file)
    webp_image = webp.WebPPicture.from_pil(pil_image)
    return webp_image.encode(config)
