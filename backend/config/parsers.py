from rest_framework.exceptions import ParseError
from rest_framework.parsers import JSONParser


class ObjectJSONParser(JSONParser):
    """JSON whose top level must be an object: endpoints read ``request.data.get``, so anything else is a 400 here
    (code ``bad_body``, the wording Conformiti Pro's routes use)."""

    def parse(self, stream, media_type=None, parser_context=None):
        data = super().parse(stream, media_type, parser_context)
        if not isinstance(data, dict):
            raise ParseError({"detail": "Send the fields as a JSON object.", "code": "bad_body"})
        return data
