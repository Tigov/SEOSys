"""Password rules (NIST SP 800-63B style) and hashing."""
from seo_platform.auth import passwords, tokens


def test_short_password_rejected():
    assert "12 characters" in passwords.problem("plum tree 1")  # 11 characters
    assert passwords.problem("plum tree 12") is None  # exactly 12 is allowed


def test_129_chars_rejected():
    assert "128" in passwords.problem("correct horse " * 10)


def test_common_password_rejected():
    assert "common" in passwords.problem("password1234")
    assert "common" in passwords.problem("Qwertyuiop!!")
    assert "common" in passwords.problem("aaaaaaaaaaaaaa")


def test_contains_email_name_rejected():
    assert "email" in passwords.problem("viktorsecurehouse", "viktor@example.com")


def test_good_password_ok():
    assert passwords.problem("purple tractor sings loudly", "viktor@example.com") is None


def test_hash_and_verify():
    h = passwords.hash("purple tractor sings loudly")
    assert h.startswith("$argon2id$")
    assert passwords.verify(h, "purple tractor sings loudly")
    assert not passwords.verify(h, "purple tractor sings quietly")
    assert not passwords.verify(None, "anything")
    assert not passwords.verify("not-a-hash", "anything")


def test_tokens_are_random_and_digested():
    a, b = tokens.new(), tokens.new()
    assert a != b and len(a) >= 40
    assert tokens.digest(a) == tokens.digest(a) and len(tokens.digest(a)) == 64


def test_recovery_codes_normalise():
    code = tokens.recovery_code()
    assert tokens.normalise_recovery_code(code.upper().replace("-", " ")) == code
