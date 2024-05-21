from adobe_vipm.flows.validation.change import validate_duplicate_or_existing_lines


def test_validate_duplicate_lines(order_factory, lines_factory):
    order = order_factory(lines=lines_factory() + lines_factory())

    has_error, order = validate_duplicate_or_existing_lines(order)

    assert has_error is True
    assert order["error"]["id"] == "VIPMV009"


def test_validate_existing_lines(order_factory, lines_factory):
    order = order_factory(lines=lines_factory(line_id=2, item_id=10))

    has_error, order = validate_duplicate_or_existing_lines(order)

    assert has_error is True
    assert order["error"]["id"] == "VIPMV010"
