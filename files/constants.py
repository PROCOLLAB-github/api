import mimetypes

SUPPORTED_IMAGES_TYPES = (
    mimetypes.types_map[".jpg"],
    mimetypes.types_map[".png"],
)

SELECTEL_AUTH_TOKEN_URL = "https://api.selcdn.ru/v3/auth/tokens"
