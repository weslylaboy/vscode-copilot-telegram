import pytest

from vscode_copilot_telegram.masking import mask_secrets


@pytest.mark.parametrize("secret", [
    "ghp_" + "a1B2" * 9,
    "github_pat_11ABCDEFG0123456789_abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJ",
    "gho_" + "Z" * 36,
    "AKIAIOSFODNN7EXAMPLE",
    "xoxb-123456789012-abcdefghijkl",
    "sk-proj-" + "x" * 40,
    "123456789:AA" + "b" * 33,
])
def test_tokens_masked(secret):
    out = mask_secrets(f"value is {secret} ok")
    assert secret not in out
    assert "***" in out
    assert out.startswith("value is ") and out.endswith(" ok")


def test_bearer():
    out = mask_secrets("curl -H 'Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig' https://x")
    assert "eyJhbGci" not in out and "Bearer ***" in out


@pytest.mark.parametrize("line,leak", [
    ("API_KEY=abc123secret", "abc123secret"),
    ("export DB_PASSWORD='hunter2'", "hunter2"),
    ('STRIPE_SECRET_KEY="sk_live_zzz"', "sk_live_zzz"),
    ("  aws_secret_access_key = wJalrXUtnFEMI", "wJalrXUtnFEMI"),
    ("GITHUB_TOKEN: abcdef", "abcdef"),
    ("$env:OPENAI_API_KEY=xyz987", "xyz987"),
])
def test_env_lines(line, leak):
    out = mask_secrets("first\n" + line + "\nlast")
    assert leak not in out
    assert out.startswith("first\n") and out.endswith("\nlast")


def test_non_secret_env_untouched():
    assert mask_secrets("NODE_ENV=production\nPORT=3000") == "NODE_ENV=production\nPORT=3000"


def test_private_key_block():
    pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIEow\nabc\n-----END RSA PRIVATE KEY-----"
    out = mask_secrets("before\n" + pem + "\nafter")
    assert "MIIEow" not in out and "before" in out and "after" in out


def test_truncated_private_key():
    out = mask_secrets("x\n-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXk")
    assert "b3BlbnNz" not in out


def test_url_credentials():
    out = mask_secrets("git clone https://user:s3cretpw@github.com/a/b")
    assert "s3cretpw" not in out and "github.com/a/b" in out


def test_plain_text_unchanged():
    s = "Ran npm test, 42 passed. See src/app.ts"
    assert mask_secrets(s) == s
