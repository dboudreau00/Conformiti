"""Filtering by a person's id without saying whether that person exists.

django-filter generates a ``ModelChoiceFilter`` for a foreign key, and a
ModelChoiceFilter validates membership: an id that belongs to an account
answers 200, an id that belongs to nobody answers 400. On a collection an
external auditor may read, that exposes the staff directory one sequential id
at a time, even with the ``/api/users/`` refusal in place. It discloses less
than the directory itself, because these routes return no names, but it
answers the same question (0.9.5i, L-1).

A number filter avoids this. An id nobody holds filters to nothing and
answers 200 with an empty page, which is what a real person with no rows
answers, so the reply carries no information about who exists. The interface
filters by an id it was already given, so the feature is unchanged.

Only the collections an auditor can reach need this, but it is applied to
every person-valued filter on those collections, and
``EveryAuditorReadableFilterTests`` in ``accounts/tests_review_095i.py`` walks
them so the next collection added to that list cannot reintroduce it.
"""
import django_filters as filters


def person(field_name):
    """A filter on a person foreign key that never validates membership."""
    return filters.NumberFilter(field_name=field_name)
