"""Ask the official Claude client about its account; never read its credentials."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

INSTALL_HINT = "Install Claude Code, then run `claude auth login` in a terminal outside Fusion. Return here and check the connection."
LOGIN_HINT = "Run `claude auth login` in a terminal outside Fusion, then check the connection here."
INSTALL_URL = "https://code.claude.com/docs/en/setup"


# STELLA: subscription model picker. The Claude 5.5 routes need Claude Code >= MIN_CLAUDE_VERSION,
# and STEVE's zero-turn history replay needs a recent CLI, so the newest installed Claude Code wins.
MIN_CLAUDE_VERSION = (2, 1, 280)
SUBSCRIPTION_MODELS = (
    ("claude-opus-5-5", "Opus 5.5"),
    ("claude-sonnet-5-5", "Sonnet 5.5"),
    ("claude-haiku-5-5", "Haiku 5.5"),
)
DEFAULT_MODEL = "claude-sonnet-5-5"
_version_cache = {}


def parse_version(text):
    match = re.match(r"^\s*(\d+)\.(\d+)\.(\d+)", text or "")
    return tuple(int(part) for part in match.groups()) if match else None


def binary_version(path):
    """Version of one claude executable; cached per path and mtime."""
    try:
        key = (str(path), Path(path).stat().st_mtime_ns)
    except OSError:
        return None
    if key not in _version_cache:
        version = None
        try:
            result = subprocess.run([str(path), "--version"], stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=10, **process_options())
            if result.returncode == 0:
                version = parse_version(result.stdout)
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
        _version_cache[key] = version
    return _version_cache[key]


def claude_candidates(env):
    """Windows: the desktop app's bundled CLI, the native installer's, then whatever is on PATH."""
    found = []
    if os.name == "nt":
        appdata = env.get("APPDATA")
        if appdata:
            found += sorted(Path(appdata, "Claude", "claude-code").glob("*/*/claude.exe"))
        found.append(Path.home() / ".local" / "bin" / "claude.exe")
    on_path = shutil.which("claude", path=env.get("PATH") or os.defpath)
    if on_path:
        found.append(Path(on_path))
    unique, seen = [], set()
    for path in found:
        if path.is_file() and str(path).lower() not in seen:
            seen.add(str(path).lower())
            unique.append(path)
    return unique


def resolve_claude(command=None, env=None):
    env = os.environ if env is None else env
    configured = env.get("STEVE_CLAUDE_COMMAND")
    command = list(command) if command else [configured or "claude"]
    head = command[0]
    found = None
    if head == "claude" and not configured:
        versioned = [(binary_version(path), path) for path in claude_candidates(env)]
        versioned = [(version, path) for version, path in versioned if version]
        if versioned:
            found = str(max(versioned, key=lambda item: item[0])[1])
    found = found or shutil.which(head, path=env.get("PATH") or os.defpath)
    if not found and os.path.isabs(head) and Path(head).is_file():
        found = head
    return [found, *command[1:]] if found else None


def checked_environment():
    env = dict(os.environ)
    conflicts = [k for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "ANTHROPIC_FOUNDRY_API_KEY") if env.get(k)]
    conflicts += [k for k in ("CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY")
                  if env.get(k, "").lower() not in ("", "0", "false", "no", "off")]
    if conflicts:
        raise ValueError("Claude subscription mode cannot use these environment overrides: " + ", ".join(conflicts) + ". Remove them from Fusion's launch environment and restart Fusion.")
    config = env.pop("STEVE_CLAUDE_CONFIG_DIR", None)
    if config:
        env["CLAUDE_CONFIG_DIR"] = config
    env.update(CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1", DISABLE_TELEMETRY="1", DISABLE_ERROR_REPORTING="1", DISABLE_AUTOUPDATER="1")
    return env


def process_options():
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def cli_version(command=None):
    """Probe on each connection check so an updated executable is reflected immediately."""
    try:
        env = checked_environment()
        resolved = resolve_claude(command, env)
        if not resolved:
            return ""
        result = subprocess.run([*resolved, "--version"], stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, encoding="utf-8", errors="replace",
                                timeout=10, env=env, **process_options())
        match = re.match(r"^(\d+\.\d+\.\d+(?:[-+][\w.-]+)?)(?:\s|$)", result.stdout.strip())
        return match[1] if result.returncode == 0 and match else ""
    except (OSError, ValueError, subprocess.SubprocessError):
        return ""


def model_label(model, row):
    """Use the resolved route's version, not an unversioned picker alias."""
    native = row.get("displayName") or row.get("description") or model
    match = re.fullmatch(r"claude-([a-z][a-z-]*?)-(\d+(?:-\d{1,2})*)(?:-\d{8})?(\[[^\]]+\])?", model)
    if not match:
        return native if not model.startswith("claude-") or model in native else f"{native} ({model})"
    name = match[1].replace("-", " ").title() + " " + match[2].replace("-", ".")
    if match[3]:
        name += " (" + match[3][1:-1].upper() + " context)"
    if native.lower().startswith("default"):
        name += " (recommended)"
    return name


def account_status(command=None):
    try:
        env = checked_environment()
    except ValueError as exc:
        return {"account": None, "localStatus": str(exc)}
    resolved = resolve_claude(command, env)
    if not resolved:
        return {"account": None, "localStatus": INSTALL_HINT}
    try:
        result = subprocess.run([*resolved, "auth", "status"], stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, encoding="utf-8", errors="replace",
                                timeout=20, env=env, **process_options())
        auth = json.loads(result.stdout)
        if not isinstance(auth, dict):
            raise ValueError("Expected account metadata")
    except (OSError, ValueError, subprocess.SubprocessError):
        return {"account": None, "localStatus": "Claude Code's account check failed. Run `claude auth status` in a terminal, resolve its error, then check again."}
    if result.returncode != 0 or auth.get("loggedIn") is not True:
        return {"account": None, "localStatus": LOGIN_HINT}
    # STELLA: `claude setup-token` logins (CLAUDE_CODE_OAUTH_TOKEN) report authMethod "oauth_token" without a plan type;
    # they are still subscription auth (API keys/base URLs are rejected above), so accept them.
    token_login = auth.get("authMethod") == "oauth_token"
    if auth.get("apiProvider") != "firstParty" or not (token_login or (auth.get("authMethod") == "claude.ai" and auth.get("subscriptionType"))):
        return {"account": None, "localStatus": "Claude Code must use a Claude subscription, not API billing. Run `claude auth login` outside Fusion and choose your Claude account, then check again."}
    return {"account": {"type": "claude", "email": auth.get("email") or "Claude Code account",
                        "id": auth.get("email") or auth.get("orgId") or "claude-cli",
                        "planType": "Claude " + str(auth.get("subscriptionType") or "subscription (token)").replace("_", " ").title()},
            "localStatus": "Connected through Claude Code. Manage sign-in with `claude auth login` or `claude auth logout` outside Fusion."}


def discover_models(command=None):
    """The three subscription routes only (no 1M-context variants, which need usage credits).
    Refuses a Claude Code too old for the Claude 5.5 routes instead of failing later in a request."""
    env = checked_environment()
    resolved = resolve_claude(command, env)
    if not resolved:
        raise RuntimeError(INSTALL_HINT)
    version = binary_version(resolved[0])
    if version is None or version < MIN_CLAUDE_VERSION:
        have = ".".join(map(str, version)) if version else "unknown"
        need = ".".join(map(str, MIN_CLAUDE_VERSION))
        raise RuntimeError(f"Claude Code {have} is too old for Claude 5.5 (needs {need} or newer). Run `claude update` outside Fusion, then check the connection again.")
    efforts = ("low", "medium", "high", "max")
    models = [{"id": model, "model": model, "displayName": label, "isDefault": model == DEFAULT_MODEL,
               "supportsImages": True, "defaultReasoningEffort": "high",
               "supportedReasoningEfforts": [{"reasoningEffort": e, "description": "Claude " + e + " effort"} for e in efforts]}
              for model, label in SUBSCRIPTION_MODELS]
    models.sort(key=lambda row: not row["isDefault"])
    return {"data": models, "nextCursor": None}
