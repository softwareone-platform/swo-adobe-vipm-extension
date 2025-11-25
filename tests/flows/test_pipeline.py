import pytest

from adobe_vipm.flows.pipeline import Cursor, Pipeline, Step


def test_pipeline_completes(mocker, mock_mpt_client):
    class TestStep(Step):
        def __call__(self, client, context, next_step):
            next_step(client, context)

    # BL
    mocked_context = mocker.MagicMock()
    step1 = TestStep()
    step2 = TestStep()
    spy = mocker.spy(TestStep, "__call__")
    pipeline = Pipeline(step1, step2)

    pipeline.run(mock_mpt_client, mocked_context)  # act

    assert len(pipeline) == 2
    assert spy.call_count == 2
    assert spy.mock_calls[0].args[1] == mock_mpt_client
    assert spy.mock_calls[0].args[2] == mocked_context
    assert isinstance(spy.mock_calls[0].args[3], Cursor)


def test_pipeline_exit_prematurely(mocker, mock_mpt_client):
    class TestStep1(Step):
        def __call__(self, client, context, next_step):
            pass

    # BL
    class TestStep2(Step):
        def __call__(self, client, context, next_step):
            next_step(client, context)

    # BL
    mocked_context = mocker.MagicMock()
    step1 = TestStep1()
    step2 = TestStep2()
    spy1 = mocker.spy(TestStep1, "__call__")
    spy2 = mocker.spy(TestStep2, "__call__")
    pipeline = Pipeline(step1, step2)

    pipeline.run(mock_mpt_client, mocked_context)  # act

    assert len(pipeline) == 2
    assert spy1.call_count == 1
    assert spy2.call_count == 0


def test_pipeline_exception_default_handler(mocker, mock_mpt_client):
    test_exc = Exception("exception!")

    # BL
    class TestStep(Step):
        def __call__(self, client, context, next_step):
            raise test_exc

    # BL
    mocked_context = mocker.MagicMock()
    step1 = TestStep()
    step2 = TestStep()
    pipeline = Pipeline(step1, step2)

    with pytest.raises(Exception, match="exception!"):
        pipeline.run(mock_mpt_client, mocked_context)
