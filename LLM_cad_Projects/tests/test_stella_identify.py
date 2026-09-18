from stella_cad.identify import is_stella_command_line, parse_listen_pids


ROOT = r"E:\aiwork\Stella_CAD_SYSTEM"


def test_parse_listen_pids_ignores_other_ports():
    text = """
  TCP    127.0.0.1:8630    0.0.0.0:0    LISTENING    40548
  TCP    127.0.0.1:86300   0.0.0.0:0    LISTENING    99
  TCP    127.0.0.1:8630    127.0.0.1:1  ESTABLISHED  40548
"""
    assert parse_listen_pids(text, 8630) == [40548]


def test_stella_command_line_is_this_repo_serve():
    cmd = (
        r'"E:\aiwork\Stella_CAD_SYSTEM\.python\cpython-3.12-windows-x86_64-none\python.exe" '
        r'"E:\aiwork\Stella_CAD_SYSTEM\agentcad-for-windows\.venv\Scripts\agentcad.exe" '
        r"serve --no-open --port 8630"
    )
    assert is_stella_command_line(cmd, ROOT) is True


def test_foreign_python_is_not_stella():
    assert is_stella_command_line(
        r"C:\Python312\python.exe -m http.server 8630", ROOT
    ) is False
    assert is_stella_command_line(None, ROOT) is False
