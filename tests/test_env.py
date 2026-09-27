import pytest

from nemlig._env import read_env_file


@pytest.mark.parametrize(
    ("line", "value"),
    [
        ("K=plain", "plain"),
        ('K="quoted"', "quoted"),
        ("export K='single'", "single"),
        ('K=ends-with-quote"', 'ends-with-quote"'),
        ("K=\"mixed'", "\"mixed'"),
        ('K="', '"'),
        ("K=a=b # not a comment", "a=b # not a comment"),
    ],
)
def test_values(tmp_path, line, value):
    path = tmp_path / ".env"
    path.write_text(f"# comment\n\n{line}\n")
    assert read_env_file(path) == {"K": value}
