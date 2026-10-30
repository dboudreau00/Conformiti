from django.test.runner import DiscoverRunner


class Runner(DiscoverRunner):
    def setup_databases(self, **kwargs):
        result = super().setup_databases(**kwargs)
        # Without a test database (database-free tests only) the lookup would query the developer's own one.
        if result:
            from accounts import tenancy

            tenancy.activate(tenancy.default_workspace())
        return result

    def teardown_databases(self, old_config, **kwargs):
        from accounts import tenancy

        tenancy.deactivate()
        super().teardown_databases(old_config, **kwargs)
