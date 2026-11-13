import webp
from PIL import Image


def convert_image_to_webp(image, quality: int = 70):
    config = webp.WebPConfig.new(preset=webp.WebPPreset.PHOTO, quality=quality)
    pil_image = Image.open(image.file)
    webp_image = webp.WebPPicture.from_pil(pil_image)
    return webp_image.encode(config)


def resize_image(image, size=(512, 512)):
    pil_image = Image.open(image.file)

    # Подгонка параметров для горизонтальных изображений
    if pil_image.height < pil_image.width:
        width, height = pil_image.width, pil_image.width
        x, y = 0, int((pil_image.height - height) // 2)

    # Подгонка параметров для вертикальных изображений
    elif pil_image.height > pil_image.width:
        width, height = pil_image.height, pil_image.height
        x, y = int((pil_image.width - width) // 2), 0

    # Подгонка параметров для квадратных изображений
    else:
        width, height = pil_image.width, pil_image.height
        x, y = 0, 0

    # Итоговые размеры до ресайза
    area = (x, y, x + width, y + height)

    pil_image = pil_image.crop(area)
    pil_image = pil_image.resize(size)

    return pil_image
