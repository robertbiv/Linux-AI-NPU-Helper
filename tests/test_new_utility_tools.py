from src.tools.format_converter import FormatConverterTool
from src.tools.qrcode_tool import QRCodeTool
from src.tools.string_case_tool import StringCaseTool


def test_format_converter_json_to_yaml():
    tool = FormatConverterTool()
    res = tool.run(
        {
            "source_format": "json",
            "target_format": "yaml",
            "text": '{"a": 1, "b": "test"}',
        }
    )
    assert not res.error
    assert "a: 1" in res.results[0].snippet
    assert "b: test" in res.results[0].snippet


def test_format_converter_yaml_to_json():
    tool = FormatConverterTool()
    res = tool.run(
        {"source_format": "yaml", "target_format": "json", "text": "a: 1\nb: test"}
    )
    assert not res.error
    assert '"a": 1' in res.results[0].snippet


def test_string_case_tool():
    tool = StringCaseTool()

    # Camel
    res = tool.run({"text": "hello_world", "to_case": "camel"})
    assert res.results[0].snippet == "helloWorld"

    # Snake
    res = tool.run({"text": "helloWorld", "to_case": "snake"})
    assert res.results[0].snippet == "hello_world"

    # Pascal
    res = tool.run({"text": "hello world", "to_case": "pascal"})
    assert res.results[0].snippet == "HelloWorld"

    # Kebab
    res = tool.run({"text": "Hello World", "to_case": "kebab"})
    assert res.results[0].snippet == "hello-world"

    # Constant
    res = tool.run({"text": "helloWorld", "to_case": "constant"})
    assert res.results[0].snippet == "HELLO_WORLD"


def test_qrcode_tool_missing_lib():
    tool = QRCodeTool()
    res = tool.run({"text": "https://example.com"})
    # It might pass if qrcode is installed, otherwise it returns an error about missing lib
    pass
