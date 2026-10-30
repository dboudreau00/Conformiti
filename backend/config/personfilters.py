import django_filters as filters


def person(field_name):
    """A person filter that never validates membership: an id nobody holds filters to an empty page, not a 400,
    so a collection an external auditor can read does not reveal which accounts exist."""
    return filters.NumberFilter(field_name=field_name)
