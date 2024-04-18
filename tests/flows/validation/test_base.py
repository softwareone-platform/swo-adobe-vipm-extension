import logging

from adobe_vipm.flows.validation.base import validate_order


def test_validate_purchase_order(mocker, caplog, order_factory, customer_data):
    """Tests the validate order entrypoint function when it validates."""
    order = order_factory()
    m_client = mocker.MagicMock()

    m_prepare_customer_data = mocker.patch(
        "adobe_vipm.flows.validation.base.prepare_customer_data",
        return_value=(order, customer_data),
    )
    m_validate_customer_data = mocker.patch(
        "adobe_vipm.flows.validation.base.validate_customer_data",
        return_value=(False, order),
    )
    m_update_purchase_prices = mocker.patch(
        "adobe_vipm.flows.validation.base.update_purchase_prices",
        return_value=order,
    )
    m_adobe_cli = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.validation.base.get_adobe_client", return_value=m_adobe_cli
    )

    with caplog.at_level(logging.INFO):
        assert validate_order(m_client, order) == order

    assert caplog.records[0].message == (
        f"Validation of order {order['id']} succeeded without errors"
    )

    m_prepare_customer_data.assert_called_once_with(m_client, order)
    m_validate_customer_data.assert_called_once_with(order, customer_data)
    m_update_purchase_prices.assert_called_once_with(
        m_client,
        m_adobe_cli,
        order,
    )


def test_validate_purchase_order_no_validate(mocker, caplog, order_factory):
    """Tests the validate order entrypoint function when doesn't validate."""
    mocker.patch("adobe_vipm.flows.validation.base.get_adobe_client")
    order = order_factory()
    m_client = mocker.MagicMock()

    mocker.patch(
        "adobe_vipm.flows.validation.base.populate_order_info", return_value=order
    )
    mocker.patch(
        "adobe_vipm.flows.validation.base.prepare_customer_data",
        return_value=(order, mocker.MagicMock()),
    )
    mocker.patch(
        "adobe_vipm.flows.validation.base.validate_customer_data",
        return_value=(True, order),
    )

    with caplog.at_level(logging.INFO):
        validate_order(m_client, order)

    assert caplog.records[0].message == (
        f"Validation of order {order['id']} succeeded with errors"
    )


def test_validate_transfer_order(
    mocker,
    caplog,
    order_factory,
    transfer_order_parameters_factory,
):
    """Tests the validate order entrypoint function for transfer orders when it validates."""
    order = order_factory(order_parameters=transfer_order_parameters_factory())
    m_client = mocker.MagicMock()

    m_validate_transfer = mocker.patch(
        "adobe_vipm.flows.validation.base.validate_transfer",
        return_value=(False, order),
    )
    m_update_purchase_prices = mocker.patch(
        "adobe_vipm.flows.validation.base.update_purchase_prices",
        return_value=order,
    )
    m_adobe_cli = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.validation.base.get_adobe_client", return_value=m_adobe_cli
    )

    with caplog.at_level(logging.INFO):
        assert validate_order(m_client, order) == order

    assert caplog.records[0].message == (
        f"Validation of order {order['id']} succeeded without errors"
    )

    m_validate_transfer.assert_called_once_with(
        m_client,
        m_adobe_cli,
        order,
    )
    m_update_purchase_prices.assert_called_once_with(
        m_client,
        m_adobe_cli,
        order,
    )


def test_validate_transfer_order_no_validate(
    mocker,
    caplog,
    order_factory,
    transfer_order_parameters_factory,
):
    """Tests the validate order entrypoint function for transfers when doesn't validate."""
    mocker.patch("adobe_vipm.flows.validation.base.get_adobe_client")
    order = order_factory(order_parameters=transfer_order_parameters_factory())
    m_client = mocker.MagicMock()

    mocker.patch(
        "adobe_vipm.flows.validation.base.populate_order_info", return_value=order
    )
    mocker.patch(
        "adobe_vipm.flows.validation.base.prepare_customer_data",
        return_value=(order, mocker.MagicMock()),
    )

    mocker.patch(
        "adobe_vipm.flows.validation.base.validate_transfer",
        return_value=(True, order),
    )

    with caplog.at_level(logging.INFO):
        validate_order(m_client, order)

    assert caplog.records[0].message == (
        f"Validation of order {order['id']} succeeded with errors"
    )
