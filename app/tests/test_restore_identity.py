from avelren.restore_identity import connection_identity_problems


class _Result:
    def fetchone(self):
        return (
            "restore_test",
            "avelren_api",
            "avelren_api",
            "scram-sha-256:avelren_admin",
        )


class _Connection:
    def execute(self, query):
        assert query == (
            "SELECT current_database(), current_user, session_user, system_user"
        )
        return _Result()


def test_rejects_admin_authentication_after_session_authorization_switch():
    problems = connection_identity_problems(
        _Connection(), "restore_test", "avelren_api"
    )

    assert problems == [
        "system authentication identity mismatch: expected avelren_api, "
        "got scram-sha-256:avelren_admin"
    ]
