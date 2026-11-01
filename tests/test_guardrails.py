import pytest

from nightshift import BY_ID, Workspace


@pytest.fixture
def ws():
    w = Workspace(BY_ID["INC-102"])
    yield w
    w.close()


def test_cannot_edit_existing_tests(ws):
    out = ws.edit_file("tests/test_orders.py", "def test_line_total", "def _off")
    assert out.startswith("BLOCKED") and not ws.changed_files()


def test_cannot_escape_the_repo(ws):
    assert ws.edit_file("../../etc/passwd", "root", "x").startswith("BLOCKED")
    assert ws.read_file("../../etc/passwd").startswith("ERROR")


def test_cannot_silence_errors(ws):
    out = ws.edit_file("orders/inventory.py", "    if qty >= available:\n        raise OutOfStock",
                       "    try:\n        pass\n    except Exception:\n        pass\n    if False:\n        raise OutOfStock")
    assert "swallowing exceptions" in out


def test_new_tests_must_be_regression_tests_and_cannot_skip(ws):
    assert ws.create_test("test_orders.py", "x = 1").startswith("BLOCKED")
    assert "skipping" in ws.create_test("test_regression_a.py", "import pytest\npytest.skip('x')")


def test_diff_budget_blocks_rewrites(ws):
    big = "\n".join(f"# line {n}" for n in range(60))
    out = ws.edit_file("orders/inventory.py", "class OutOfStock(Exception):", big + "\nclass OutOfStock(Exception):")
    assert "diff budget" in out and not ws.changed_files()


def test_every_violation_is_recorded(ws):
    ws.edit_file("tests/test_orders.py", "a", "b")
    ws.create_test("bad.py", "")
    assert len(ws.violations) == 2


def test_test_names_are_normalized_but_still_restricted(ws):
    assert ws.create_test("tests/test_regression_stock", "def test_x():\n    assert 1 == 1\n") == \
        "created tests/test_regression_stock.py"
    assert ws.create_test("conftest", "x = 1").startswith("BLOCKED")
