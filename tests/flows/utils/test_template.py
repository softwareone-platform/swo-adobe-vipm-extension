from adobe_vipm.flows.utils.template import get_template_data_by_adobe_subscription


def test_get_template_by_adobe_subscription(mocker, mock_mpt_client):
    mock_get_template_name_by_subscription = mocker.patch(
        "adobe_vipm.flows.utils.template.get_template_name_by_subscription",
        return_value="fake_template_name",
    )
    mock_get_template_by_name = mocker.patch(
        "adobe_vipm.flows.utils.template.get_template_by_name",
        return_value={"id": "fake_id", "name": "fake_template_name"},
    )
    mock_adobe_subscription = mocker.Mock()

    result = get_template_data_by_adobe_subscription(mock_adobe_subscription, "fake_product_id")

    assert result == {"id": "fake_id", "name": "fake_template_name"}
    mock_get_template_name_by_subscription.assert_called_once_with(mock_adobe_subscription)
    mock_get_template_by_name.assert_called_once_with(
        mock_mpt_client, "fake_product_id", "fake_template_name"
    )


def test_get_template_by_adobe_subscription_not_found_template(mocker, mock_mpt_client, caplog):
    mock_get_template_name_by_subscription = mocker.patch(
        "adobe_vipm.flows.utils.template.get_template_name_by_subscription",
        return_value="fake_template_name",
    )
    mock_get_template_by_name = mocker.patch(
        "adobe_vipm.flows.utils.template.get_template_by_name", return_value=None
    )
    mock_adobe_subscription = mocker.Mock()

    result = get_template_data_by_adobe_subscription(mock_adobe_subscription, "fake_product_id")

    assert result is None
    assert "Template fake_template_name not found for product fake_product_id" in caplog.messages
    mock_get_template_name_by_subscription.assert_called_once_with(mock_adobe_subscription)
    mock_get_template_by_name.assert_called_once_with(
        mock_mpt_client, "fake_product_id", "fake_template_name"
    )
