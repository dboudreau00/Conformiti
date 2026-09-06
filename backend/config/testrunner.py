"""Test runner that activates the Default workspace for the whole run.

Every tenant row a test creates needs a workspace; activating the one the
migrations create means the existing suite runs unchanged as a single-
workspace installation. Requests made through the test client resolve their
own workspace and restore this one afterwards (see accounts/tenancy.py);
tests that need a second organisation use ``tenancy.scoped(other)``.
"""
from django.test.runner import DiscoverRunner


class Runner(DiscoverRunner):
    def setup_databases(self, **kwargs):
        result = super().setup_databases(**kwargs)
        from accounts import tenancy

        tenancy.activate(tenancy.default_workspace())
        return result

    def teardown_databases(self, old_config, **kwargs):
        from accounts import tenancy

        tenancy.deactivate()
        super().teardown_databases(old_config, **kwargs)
