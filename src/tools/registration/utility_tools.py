# SPDX-License-Identifier: GPL-3.0-or-later
"""Utility tools registration."""

from src.tools._base import ToolRegistry


def _register_utility_tools(
    registry: ToolRegistry, cfg: dict, global_unload: bool
) -> None:
    from src.tools.calculator import CalculatorTool
    from src.tools.hash_tool import HashTool
    from src.tools.clipboard_tool import ClipboardTool
    from src.tools.password_tool import PasswordGeneratorTool
    from src.tools.base64_tool import Base64Tool
    from src.tools.uuid_tool import UUIDTool
    from src.tools.json_tool import JSONTool
    from src.tools.url_tool import URLEncoderTool
    from src.tools.text_stats_tool import TextStatsTool
    from src.tools.regex_tool import RegexTool
    from src.tools.time_tool import TimeTool
    from src.tools.subnet_tool import SubnetTool
    from src.tools.diff_tool import DiffTool
    from src.tools.jwt_tool import JWTDecoderTool
    from src.tools.encoding_tool import EncodingTool

    calc_cfg = cfg.get("calculator", {})
    calc_enabled = bool(calc_cfg.get("enabled", True))
    calc_unload = bool(calc_cfg.get("unload_after_use", global_unload))

    hash_cfg = cfg.get("hash_tool", {})
    hash_enabled = bool(hash_cfg.get("enabled", True))
    hash_unload = bool(hash_cfg.get("unload_after_use", global_unload))

    clip_cfg = cfg.get("clipboard_tool", {})
    clip_enabled = bool(clip_cfg.get("enabled", True))
    clip_unload = bool(clip_cfg.get("unload_after_use", global_unload))

    pass_cfg = cfg.get("password_generator", {})
    pass_enabled = bool(pass_cfg.get("enabled", True))
    pass_unload = bool(pass_cfg.get("unload_after_use", global_unload))

    b64_cfg = cfg.get("base64", {})
    b64_enabled = bool(b64_cfg.get("enabled", True))
    b64_unload = bool(b64_cfg.get("unload_after_use", global_unload))

    uuid_cfg = cfg.get("generate_uuid", {})
    uuid_enabled = bool(uuid_cfg.get("enabled", True))
    uuid_unload = bool(uuid_cfg.get("unload_after_use", global_unload))

    json_cfg = cfg.get("json_format", {})
    json_enabled = bool(json_cfg.get("enabled", True))
    json_unload = bool(json_cfg.get("unload_after_use", global_unload))

    url_cfg = cfg.get("url_encode", {})
    url_enabled = bool(url_cfg.get("enabled", True))
    url_unload = bool(url_cfg.get("unload_after_use", global_unload))

    ts_cfg = cfg.get("text_stats", {})
    ts_enabled = bool(ts_cfg.get("enabled", True))
    ts_unload = bool(ts_cfg.get("unload_after_use", global_unload))

    re_cfg = cfg.get("regex", {})
    re_enabled = bool(re_cfg.get("enabled", True))
    re_unload = bool(re_cfg.get("unload_after_use", global_unload))

    time_cfg = cfg.get("time_tool", {})
    time_enabled = bool(time_cfg.get("enabled", True))
    time_unload = bool(time_cfg.get("unload_after_use", global_unload))

    sub_cfg = cfg.get("subnet_calc", {})
    sub_enabled = bool(sub_cfg.get("enabled", True))
    sub_unload = bool(sub_cfg.get("unload_after_use", global_unload))

    diff_cfg = cfg.get("diff_text", {})
    diff_enabled = bool(diff_cfg.get("enabled", True))
    diff_unload = bool(diff_cfg.get("unload_after_use", global_unload))

    jwt_cfg = cfg.get("jwt_decode", {})
    jwt_enabled = bool(jwt_cfg.get("enabled", True))
    jwt_unload = bool(jwt_cfg.get("unload_after_use", global_unload))

    enc_cfg = cfg.get("encoding", {})
    enc_enabled = bool(enc_cfg.get("enabled", True))
    enc_unload = bool(enc_cfg.get("unload_after_use", global_unload))

    if calc_enabled:
        registry.register_lazy(
            name=CalculatorTool.name,
            description=CalculatorTool.description,
            schema=CalculatorTool.parameters_schema,
            factory=CalculatorTool,
            unload_after_use=calc_unload,
        )

    if hash_enabled:
        registry.register_lazy(
            name=HashTool.name,
            description=HashTool.description,
            schema=HashTool.parameters_schema,
            factory=HashTool,
            unload_after_use=hash_unload,
        )

    if pass_enabled:
        registry.register_lazy(
            name=PasswordGeneratorTool.name,
            description=PasswordGeneratorTool.description,
            schema=PasswordGeneratorTool.parameters_schema,
            factory=PasswordGeneratorTool,
            unload_after_use=pass_unload,
        )

    if b64_enabled:
        registry.register_lazy(
            name=Base64Tool.name,
            description=Base64Tool.description,
            schema=Base64Tool.parameters_schema,
            factory=Base64Tool,
            unload_after_use=b64_unload,
        )

    if uuid_enabled:
        registry.register_lazy(
            name=UUIDTool.name,
            description=UUIDTool.description,
            schema=UUIDTool.parameters_schema,
            factory=UUIDTool,
            unload_after_use=uuid_unload,
        )

    if json_enabled:
        registry.register_lazy(
            name=JSONTool.name,
            description=JSONTool.description,
            schema=JSONTool.parameters_schema,
            factory=JSONTool,
            unload_after_use=json_unload,
        )

    if url_enabled:
        registry.register_lazy(
            name=URLEncoderTool.name,
            description=URLEncoderTool.description,
            schema=URLEncoderTool.parameters_schema,
            factory=URLEncoderTool,
            unload_after_use=url_unload,
        )

    if ts_enabled:
        registry.register_lazy(
            name=TextStatsTool.name,
            description=TextStatsTool.description,
            schema=TextStatsTool.parameters_schema,
            factory=TextStatsTool,
            unload_after_use=ts_unload,
        )

    if re_enabled:
        registry.register_lazy(
            name=RegexTool.name,
            description=RegexTool.description,
            schema=RegexTool.parameters_schema,
            factory=RegexTool,
            unload_after_use=re_unload,
        )

    if time_enabled:
        registry.register_lazy(
            name=TimeTool.name,
            description=TimeTool.description,
            schema=TimeTool.parameters_schema,
            factory=TimeTool,
            unload_after_use=time_unload,
        )

    if sub_enabled:
        registry.register_lazy(
            name=SubnetTool.name,
            description=SubnetTool.description,
            schema=SubnetTool.parameters_schema,
            factory=SubnetTool,
            unload_after_use=sub_unload,
        )

    if diff_enabled:
        registry.register_lazy(
            name=DiffTool.name,
            description=DiffTool.description,
            schema=DiffTool.parameters_schema,
            factory=DiffTool,
            unload_after_use=diff_unload,
        )

    if jwt_enabled:
        registry.register_lazy(
            name=JWTDecoderTool.name,
            description=JWTDecoderTool.description,
            schema=JWTDecoderTool.parameters_schema,
            factory=JWTDecoderTool,
            unload_after_use=jwt_unload,
        )

    if enc_enabled:
        registry.register_lazy(
            name=EncodingTool.name,
            description=EncodingTool.description,
            schema=EncodingTool.parameters_schema,
            factory=EncodingTool,
            unload_after_use=enc_unload,
        )

    if clip_enabled:
        registry.register_lazy(
            name=ClipboardTool.name,
            description=ClipboardTool.description,
            schema=ClipboardTool.parameters_schema,
            factory=ClipboardTool,
            unload_after_use=clip_unload,
        )

    from src.tools.format_converter import FormatConverterTool
    from src.tools.qrcode_tool import QRCodeTool
    from src.tools.string_case_tool import StringCaseTool

    format_cfg = cfg.get("format_converter", {})
    format_enabled = bool(format_cfg.get("enabled", True))
    format_unload = bool(format_cfg.get("unload_after_use", global_unload))

    qrcode_cfg = cfg.get("qrcode", {})
    qrcode_enabled = bool(qrcode_cfg.get("enabled", True))
    qrcode_unload = bool(qrcode_cfg.get("unload_after_use", global_unload))

    string_case_cfg = cfg.get("string_case", {})
    string_case_enabled = bool(string_case_cfg.get("enabled", True))
    string_case_unload = bool(string_case_cfg.get("unload_after_use", global_unload))

    if format_enabled:
        registry.register_lazy(
            name=FormatConverterTool.name,
            description=FormatConverterTool.description,
            schema=FormatConverterTool.parameters_schema,
            factory=FormatConverterTool,
            unload_after_use=format_unload,
        )

    if qrcode_enabled:
        registry.register_lazy(
            name=QRCodeTool.name,
            description=QRCodeTool.description,
            schema=QRCodeTool.parameters_schema,
            factory=QRCodeTool,
            unload_after_use=qrcode_unload,
        )

    if string_case_enabled:
        registry.register_lazy(
            name=StringCaseTool.name,
            description=StringCaseTool.description,
            schema=StringCaseTool.parameters_schema,
            factory=StringCaseTool,
            unload_after_use=string_case_unload,
        )
