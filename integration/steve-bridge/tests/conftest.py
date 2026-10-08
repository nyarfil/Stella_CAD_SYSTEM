import os
import sys
import json
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, "fake_adsk"))            # fake adsk
sys.path.insert(0, os.path.join(ROOT, "addin", "STEVE"))       # vendored STEVE package: steve.*
sys.path.insert(0, os.path.join(ROOT, "server"))               # Stella-side package
sys.path.insert(0, HERE)

import fakes  # noqa: E402
from steve import stella_seam  # noqa: E402
from steve.fusion_tools import FusionTools  # noqa: E402
from stella_steve_bridge.gateway import Config, Gateway  # noqa: E402


class Env:
    pass


@pytest.fixture
def env(tmp_path):
    """Real seam + real vendored FusionTools + fake Fusion. Seam is enabled in a temp home."""
    e = Env()
    e.doc = fakes.Document("SANDBOX")
    e.other = fakes.Document("PRODUCTION")
    e.app = fakes.FakeApp([e.doc, e.other])
    e.home = tmp_path / "seam"
    e.home.mkdir()
    (e.home / "config.json").write_text(json.dumps({"enabled": True}), encoding="utf-8")
    stella_seam.stop()
    e.tools = FusionTools(e.app, home=tmp_path / "steve-data")
    e.server = stella_seam.start(e.tools, home=e.home)
    e.port = e.server.server_address[1]
    e.token = (e.home / "token").read_text(encoding="utf-8").strip()

    def make_gateway(**kw):
        kw.setdefault("allow_documents", ["SANDBOX"])
        cfg = Config(home=str(e.home), port=e.port, scratch_dir=str(tmp_path / "scratch"), **kw)
        return Gateway(cfg)

    e.gateway = make_gateway
    yield e
    e.tools.close()
    stella_seam.stop()
    e.app.stop()
