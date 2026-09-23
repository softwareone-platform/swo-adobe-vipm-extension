import pytest

from adobe_vipm.adobe.utils import is_flex_discount_applied


@pytest.mark.parametrize(
    ("flex_discount", "expected_result"),
    [
        ({"code": "BLACK_FRIDAY", "result": "SUCCESS"}, True),
        ({"code": "BLACK_FRIDAY"}, True),
        ({"code": "BLACK_FRIDAY", "result": "NOT_APPLICABLE"}, False),
    ],
)
def test_is_flex_discount_applied(flex_discount, expected_result):
    result = is_flex_discount_applied(flex_discount)

    assert result is expected_result
