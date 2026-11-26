class PrivateNoStoreResponseMixin:
    """Preserve the private cache policy for success and error responses."""

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "private, no-store"
        return response
