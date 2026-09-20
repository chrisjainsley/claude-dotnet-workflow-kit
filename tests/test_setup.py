import json

from conftest import SETUP_PY, import_module_from_path


def setup_module_fresh():
    return import_module_from_path("setup_under_test", SETUP_PY)


def write_package_json(root, deps):
    (root / "ClientApp").mkdir(parents=True, exist_ok=True)
    (root / "ClientApp" / "package.json").write_text(json.dumps({"dependencies": deps}), encoding="utf-8")


def test_given_razor_files_then_detect_blazor(tmp_path):
    (tmp_path / "Components" / "Pages").mkdir(parents=True)
    (tmp_path / "Components" / "Pages" / "Home.razor").write_text("@page \"/\"", encoding="utf-8")
    write_package_json(tmp_path, {"react": "^18"})

    assert setup_module_fresh().detect_frontend(tmp_path) == "blazor"


def test_given_cshtml_only_then_detect_razor(tmp_path):
    (tmp_path / "Pages").mkdir()
    (tmp_path / "Pages" / "Index.cshtml").write_text("@page", encoding="utf-8")
    (tmp_path / "wwwroot" / "js").mkdir(parents=True)
    (tmp_path / "wwwroot" / "js" / "site.js").write_text("", encoding="utf-8")

    assert setup_module_fresh().detect_frontend(tmp_path) == "razor"


def test_given_package_json_react_then_detect_react(tmp_path):
    (tmp_path / "Pages").mkdir()
    (tmp_path / "Pages" / "Index.cshtml").write_text("@page", encoding="utf-8")
    write_package_json(tmp_path, {"react": "^18", "react-dom": "^18"})

    assert setup_module_fresh().detect_frontend(tmp_path) == "react"


def test_given_package_json_angular_core_then_detect_angular(tmp_path):
    write_package_json(tmp_path, {"@angular/core": "^18"})

    assert setup_module_fresh().detect_frontend(tmp_path) == "angular"


def test_given_package_json_vue_then_detect_vue(tmp_path):
    write_package_json(tmp_path, {"vue": "^3"})

    assert setup_module_fresh().detect_frontend(tmp_path) == "vue"


def test_given_wwwroot_js_only_then_detect_javascript(tmp_path):
    (tmp_path / "wwwroot" / "js").mkdir(parents=True)
    (tmp_path / "wwwroot" / "js" / "cart.ts").write_text("", encoding="utf-8")

    assert setup_module_fresh().detect_frontend(tmp_path) == "javascript"


def test_given_node_modules_only_then_ignored(tmp_path):
    (tmp_path / "node_modules" / "react").mkdir(parents=True)
    (tmp_path / "node_modules" / "react" / "package.json").write_text(json.dumps({"name": "react"}), encoding="utf-8")

    assert setup_module_fresh().detect_frontend(tmp_path) == "none"


def test_given_no_frontend_then_none(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "Program.cs").write_text("", encoding="utf-8")

    assert setup_module_fresh().detect_frontend(tmp_path) == "none"
