from adobe_vipm.migrations.parameters_sync import ParameterManager


def test_migrate_parameters_existing_and_new():
    product_parameters = [
        {
            "id": "PRD-1",
            "externalId": "ext-1",
            "name": "Name 1 (updated)",
            "type": "Type 1",
            "phase": "Phase 1",
            "scope": "Scope 1",
            "multiple": False,
            "constraints": {"req": True},
        },
        {
            "id": "PRD-2",
            "externalId": "ext-2",
            "name": "Name 2",
            "type": "Type 2",
            "phase": "Phase 2",
            "scope": "Scope 2",
            "multiple": True,
            "constraints": {"req": False},
        },
    ]
    agreement_parameters = [
        {
            "externalId": "ext-1",
            "value": "Value 1",
            "displayValue": "Display 1",
            "name": "Name 1 (old)",
        },
        {"externalId": "ext-3", "value": "Value 3", "displayValue": "Display 3", "name": "Name 3"},
    ]

    result = ParameterManager.migrate_parameters(product_parameters, agreement_parameters)

    assert len(result) == 2

    # Check updated parameter ext-1
    param_1 = next(p for p in result if p["externalId"] == "ext-1")
    assert param_1["id"] == "PRD-1"
    assert param_1["name"] == "Name 1 (updated)"
    assert param_1["value"] == "Value 1"
    assert param_1["displayValue"] == "Display 1"

    # Check new parameter ext-2
    param_2 = next(p for p in result if p["externalId"] == "ext-2")
    assert param_2["id"] == "PRD-2"
    assert param_2["value"] is None
    assert "displayValue" not in param_2

    # Check that ext-3 is not in result
    assert not any(p["externalId"] == "ext-3" for p in result)


def test_migrate_parameters_empty_product():
    product_parameters = []
    agreement_parameters = [{"externalId": "ext-1", "value": "val"}]

    result = ParameterManager.migrate_parameters(product_parameters, agreement_parameters)

    assert result == []


def test_migrate_parameters_empty_agreement():
    product_parameters = [
        {
            "id": "PRD-1",
            "externalId": "ext-1",
            "name": "Name 1",
            "type": "Type 1",
            "phase": "Phase 1",
            "scope": "Scope 1",
            "multiple": False,
            "constraints": {},
        }
    ]
    agreement_parameters = []

    result = ParameterManager.migrate_parameters(product_parameters, agreement_parameters)

    assert len(result) == 1
    assert result[0]["externalId"] == "ext-1"
    assert result[0]["value"] is None
