import pytest


def write_config(tmp_path, content: str):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(content)
    return str(config_file)


def test_load_config_returns_api_key(tmp_path):
    path = write_config(tmp_path, 'deepseek_api_key: "sk-test-key"')
    from app.config import load_config
    result = load_config(path)
    assert result["deepseek_api_key"] == "sk-test-key"


def test_load_config_exits_when_file_missing(tmp_path, capsys):
    from app.config import load_config
    missing = str(tmp_path / "nonexistent.yaml")
    with pytest.raises(SystemExit):
        load_config(missing)
    captured = capsys.readouterr()
    assert "config.yaml" in captured.out or "config.yaml" in captured.err


def test_load_config_exits_when_key_is_placeholder(tmp_path, capsys):
    path = write_config(tmp_path, 'deepseek_api_key: "your_api_key_here"')
    from app.config import load_config
    with pytest.raises(SystemExit):
        load_config(path)
    captured = capsys.readouterr()
    assert "deepseek_api_key" in captured.out or "deepseek_api_key" in captured.err


def test_load_config_exits_when_key_is_empty(tmp_path, capsys):
    path = write_config(tmp_path, 'deepseek_api_key: ""')
    from app.config import load_config
    with pytest.raises(SystemExit):
        load_config(path)
