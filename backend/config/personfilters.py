"""Filtering by a person's id without saying whether that person exists.

django-filter generates a ``ModelChoiceFilter`` for a foreign key, and a
ModelChoiceFilter validates membership: an id that belongs to an account
answers 200, an id that belongs to nobody answers 400. On a collection an
external auditor may read, that is the staff directory again, one sequential
id at a time, with the ``/api/users/`` refusal intact and useless. It is
narrower than the disclosure it replaced in 0.9.5h, because these routes
return no names, but it is the same question answered by a different door
(0.9.5i).

A number instead. An id nobody holds filters to nothing and answers 200 with
an empty page, which is exactly what a real person with no rows answers, so
the reply carries no information about who exists. The feature is unchanged
for everyone who uses it: the interface filters by an id it was already given.

Only the collections an auditor can reach need this, but it is applied to
every person-valued filter on those collections rather than to the ones a
reviewer happened to name, and ``accounts/tests_auditor_surface.py`` walks
them so the next collection added to that list cannot quietly reintroduce it.
"""
import django_filters as filters


def person(field_name):
    """A filter on a person foreign key that never validates membership."""
    return filters.NumberFilter(field_name=field_name)
