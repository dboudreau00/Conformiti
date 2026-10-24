"""The JSON parser every API endpoint reads its body with."""
from rest_framework.exceptions import ParseError
from rest_framework.parsers import JSONParser


class ObjectJSONParser(JSONParser):
    """JSON whose top level is an object.

    Every endpoint reads its body as named fields (``request.data.get``). A
    list, a string or a number parses as valid JSON but has no fields, and on
    the 37 views that read it that way it answered 500, several of them open
    to anonymous callers (the public questionnaire, the sign-in ticket). It is
    refused here, once, as a 400 in the shape the API's other refusals take,
    with the code and wording Conformiti Pro's routes already used for it, so
    one mistake gets one answer everywhere.
    """

    def parse(self, stream, media_type=None, parser_context=None):
        data = super().parse(stream, media_type, parser_context)
        if not isinstance(data, dict):
            raise ParseError({"detail": "Send the fields as a JSON object.", "code": "bad_body"})
        return data
