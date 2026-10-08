"""Windows workaround (trial only): build123d 0.11.x registers every font in C:/Windows/Fonts at
import time and crashes on a corrupt system font (e.g. mstmc.ttf, 4096 bytes). This shim makes
font registration skip unreadable fonts. Loaded only via PYTHONPATH=<this dir>; it changes no
upstream package and no system file."""
import importlib.abc, importlib.util, sys

class _Finder(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path, target=None):
        if name != "build123d.text":
            return None
        sys.meta_path.remove(self)
        try:
            spec = importlib.util.find_spec(name)
        finally:
            sys.meta_path.insert(0, self)
        loader = spec.loader
        orig_exec = loader.exec_module
        def exec_module(module):
            src = loader.get_source(name)
            src = src.replace(
                "                font_faces += self.register_font(result, override, single_stroke)",
                "                try:\n                    font_faces += self.register_font(result, override, single_stroke)\n                except Exception:\n                    pass")
            exec(compile(src, spec.origin, "exec"), module.__dict__)
        loader.exec_module = exec_module
        return spec

sys.meta_path.insert(0, _Finder())
