from rest_framework.metadata import SimpleMetadata


class NoDescriptionMetadata(SimpleMetadata):
    """DRF's answer without "description": view docstrings are developer notes OPTIONS must not hand to anyone."""

    def determine_metadata(self, request, view):
        metadata = super().determine_metadata(request, view)
        metadata.pop("description", None)
        return metadata
