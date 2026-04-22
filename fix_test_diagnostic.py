with open("tests/test_diagnostic.py", "r") as f:
    content = f.read()

content = content.replace('patch("requests.get"', 'patch("src.gui.diagnostic_reporter.requests.get"')

with open("tests/test_diagnostic.py", "w") as f:
    f.write(content)
