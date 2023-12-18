from adobe_vipm.adobe import function_under_test


def test_function_under_test():
    assert function_under_test() == 1
