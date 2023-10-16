import webp
from PIL import Image


def convert_image_to_webp(image, quality: int = 70):
    config = webp.WebPConfig.new(preset=webp.WebPPreset.PHOTO, quality=quality)
    pil_image = Image.open(image.file)
    webp_image = webp.WebPPicture.from_pil(pil_image)
    return webp_image.encode(config)


def resize_image(image, size=(512, 512)):
    pil_image = Image.open(image.file)

    if (
        pil_image.height < pil_image.width
    ):  # Подгонка параметров для горизонтальных изображений
        width, height = pil_image.width, pil_image.width
        x, y = 0, int((pil_image.height - height) // 2)

    elif (
        pil_image.height > pil_image.width
    ):  # Подгонка параметров для вертикальных изображений
        width, height = pil_image.height, pil_image.height
        x, y = int((pil_image.width - width) // 2), 0

    else:
        width, height = (
            pil_image.width,
            pil_image.height,
        )  # Подгонка параметров для квадратных изображений
        x, y = 0, 0

    area = (x, y, x + width, y + height)  # Итоговые размеры до ресайза

    pil_image = pil_image.crop(area)
    pil_image = pil_image.resize(size)

    return pil_image
