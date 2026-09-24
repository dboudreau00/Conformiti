"""What an OPTIONS request to the API answers."""
from rest_framework.metadata import SimpleMetadata


class NoDescriptionMetadata(SimpleMetadata):
    """DRF's default answer without the "description" key.

    SimpleMetadata puts the view's docstring there, and the docstrings in
    this codebase are notes for its developers (how the login throttle and
    the CSRF check work, which release fixed what), answered to anyone who
    asks, signed in or not. The name, the renderers and parsers and the
    field list for a form stay; OPTIONS keeps answering 200 rather than 405.
    """

    def determine_metadata(self, request, view):
        metadata = super().determine_metadata(request, view)
        metadata.pop("description", None)
        return metadata
