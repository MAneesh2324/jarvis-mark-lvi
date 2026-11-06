import os
import subprocess
import sys
import json
import re
import time
from pathlib import Path


def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

BASE_DIR           = get_base_dir()
API_CONFIG_PATH    = BASE_DIR / "config" / "api_keys.json"
DESKTOP            = Path.home() / "Desktop"
MAX_BUILD_ATTEMPTS = 3
# Model choice lives in core/gemini.py, and so does the timeout and the
# fallback ladder. Writing a model name here is what left this file hanging
# forever whenever that one alias was unwell.
from core import gemini


def _get_api_key() -> str:
    with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["gemini_api_key"]


def _get_gemini(tier: str = gemini.SMART):
    """Writing and fixing code is the reasoning tier; a 60s deadline because a
    whole file can come back."""
    class _W:
        def generate_content(self, contents):
            resp = gemini.call(contents, tier=tier, timeout_ms=60000)
            if resp is None:
                raise RuntimeError("every Gemini model on the ladder failed")
            return resp

    return _W()


def _clean_code(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    return text.strip()


def _resolve_save_path(output_path: str, language: str, description: str = "") -> Path:
    ext_map = {
        "python": ".py", "py": ".py",
        "javascript": ".js", "js": ".js",
        "typescript": ".ts", "ts": ".ts",
        "html": ".html", "css": ".css",
        "java": ".java", "cpp": ".cpp", "c": ".c",
        "bash": ".sh", "shell": ".sh", "powershell": ".ps1",
        "sql": ".sql", "json": ".json", "rust": ".rs", "go": ".go",
    }
    if output_path:
        p = Path(output_path).expanduser()
        return p if p.is_absolute() else DESKTOP / p
    from core import code_quality as cq
    ext = ext_map.get((language or "python").lower()) or cq.EXT.get(cq.norm_lang(language), ".txt")
    stem = re.sub(r"[^a-z0-9]+", "_", (description or "jarvis code").lower()).strip("_")[:40] or "jarvis_code"
    folder = DESKTOP / "JARVIS Code"
    path = folder / f"{stem}{ext}"
    n = 2
    while path.exists():
        path = folder / f"{stem}_{n}{ext}"; n += 1
    return path


def _read_file(file_path: str) -> tuple[str, str]:
    if not file_path:
        return "", "No file path provided."
    p = Path(file_path)
    if not p.exists():
        return "", f"File not found: {file_path}"
    try:
        return p.read_text(encoding="utf-8"), ""
    except Exception as e:
        return "", f"Could not read file: {e}"


def _save_file(path: Path, content: str) -> str:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return f"Saved to: {path}"
    except Exception as e:
        return f"Could not save: {e}"


def _preview(code: str, lines: int = 10) -> str:
    all_lines = code.splitlines()
    preview   = "\n".join(all_lines[:lines])
    suffix    = f"\n... ({len(all_lines) - lines} more lines)" if len(all_lines) > lines else ""
    return preview + suffix


def _has_error(output: str) -> bool:
    """Judged by the exit code _run_file reports, not by words a program happens to print."""
    return output.startswith("Exit code:") or output.startswith("No interpreter") or output.startswith("Interpreter not found")


def _take_screenshot() -> Path | None:
    try:
        import pyautogui
        screenshot_path = Path.home() / "Desktop" / f"jarvis_debug_{int(time.time())}.png"
        screenshot = pyautogui.screenshot()
        screenshot.save(str(screenshot_path))
        print(f"[Code] 📸 Screenshot: {screenshot_path}")
        return screenshot_path
    except Exception as e:
        print(f"[Code] ⚠️ Screenshot failed: {e}")
        return None


def _image_to_base64(path: Path) -> str:
    import base64
    return base64.b64encode(path.read_bytes()).decode("utf-8")


_VALID_INTENTS = {"write", "edit", "explain", "run", "build", "screen_debug", "optimize"}


def _detect_intent(description: str, file_path: str, code: str) -> str:
    """
    Language-independent intent detection — NO fixed keyword list.
    Whatever language the user speaks, the description is classified by
    Gemini. If the API is unreachable, it falls back to language-agnostic
    structural hints (does the file exist on disk, was code provided).
    """
    desc        = (description or "").strip()
    file_exists = bool(file_path) and Path(file_path).exists()

    if desc:
        try:
            ctx = []
            if file_path:
                ctx.append(f"a file path is provided (exists on disk: {file_exists})")
            if code:
                ctx.append("an inline code snippet is provided")
            prompt = (
                "Classify a coding assistant request into exactly ONE intent word.\n"
                "The request may be written in ANY language.\n\n"
                f"Request: {desc}\n"
                + (f"Context: {'; '.join(ctx)}\n" if ctx else "")
                + "\nIntents:\n"
                "  write        = create new code from scratch\n"
                "  edit         = modify an existing file\n"
                "  explain      = describe what given code/file does\n"
                "  run          = execute an existing file\n"
                "  build        = write code, run it, and iterate until it works\n"
                "  screen_debug = analyze an error currently visible on the user's screen\n"
                "  optimize     = refactor / clean up / speed up existing code\n\n"
                "Reply with ONLY the intent word, nothing else."
            )
            ans = _get_gemini().generate_content(prompt).text.strip().lower()
            ans = ans.strip("`'\". \n")
            if ans in _VALID_INTENTS:
                return ans
        except Exception as e:
            print(f"[Code] Intent classification failed ({e}) — structural fallback")

    # Structural fallback — not tied to any language
    if file_exists:
        return "edit" if desc else "explain"
    if code:
        return "explain"
    return "write"

def _write(description: str, language: str, output_path: str, player=None, runner=None) -> tuple[str, Path]:
    """Write → static check → repair loop (core.code_quality). The report lands in _LAST_REPORT."""
    global _LAST_REPORT
    from core import code_quality as cq
    lang = cq.norm_lang(language or "python")
    path = _resolve_save_path(output_path, lang, description)
    log = (lambda m: (print(m), player.write_log(m))) if player else print
    code, report = cq.generate(description, lang, runner=runner(path) if runner else None, log=log)
    _save_file(path, code)
    _LAST_REPORT = report
    return code, path


_LAST_REPORT: dict = {}


def _report_line(report: dict) -> str:
    if not report:
        return ""
    if report.get("ok"):
        ran = report.get("run") or {}
        return (f"Checked: {report['checker']}"
                + (" and a test run" if ran.get("ok") else "")
                + f", clean after {report['rounds']} round(s).")
    bits = report.get("remaining_errors") or []
    miss = report.get("missing_modules") or []
    return ("Not fully verified. "
            + (f"Remaining issues: {'; '.join(bits[:3])}. " if bits else "")
            + (f"Needs: pip install {' '.join(miss)}. " if miss else ""))


def _fix_code(code: str, error_output: str, description: str, language: str = "python") -> str:
    from core import code_quality as cq
    fixed = cq.extract_code(cq.ask_model(cq.repair_prompt(description, language, code, [error_output[:2500]])))
    fixed, _ = cq.repair(fixed, language, description)
    return fixed


def _run_file(path: Path, args: list, timeout: int) -> str:
    from core import code_quality as cq
    res = cq.run_file(path, args or [], timeout)
    status = ("" if res.get("ok") else
              f"Exit code: {res.get('exit_code')}\n" if res.get("ran") else "")
    return status + res["output"]


def _build(description, language, output_path, args, timeout, speak=None, player=None) -> str:
    """Write, check, run and repair until the program runs cleanly (or rounds run out)."""
    if not description:
        return "Please describe what you want me to build, sir."
    if player:
        player.write_log("[Code] Build started...")
    from core import code_quality as cq
    lang = cq.norm_lang(language or "python")

    def runner(path):
        def run(code):
            _save_file(path, code)
            return cq.run_file(path, args or [], timeout)
        return run

    runnable = cq.EXT.get(lang, "") in cq.INTERPRETERS
    try:
        code, path = _write(description, lang, output_path, player, runner=runner if runnable else None)
    except Exception as e:
        msg = f"Could not write the code: {e}"
        if speak: speak(msg)
        return msg
    report = _LAST_REPORT
    run = report.get("run") or {}
    if report.get("ok"):
        msg = (f"Build complete, sir. It passed {report['checker']}"
               + (" and ran successfully" if run.get("ok") else "")
               + f" after {report['rounds']} round{'s' if report['rounds'] > 1 else ''}. Saved to {path}.")
        if speak: speak(msg)
        return f"{msg}\n\n{run.get('output', '')}".strip()
    msg = f"I could not get it fully working, sir. {_report_line(report)} Last version saved to {path}."
    if speak: speak(msg)
    return f"{msg}\n\n{run.get('output', '')}".strip()


def _expand(path) -> str:
    """'~/Desktop/x.py' → '/Users/<you>/Desktop/x.py'. Without this a folder literally named '~' was created."""
    path = str(path or "").strip().strip('"').strip("'")
    return os.path.expandvars(os.path.expanduser(path)) if path else ""


def _save_code_action(code, language, output_path, description, player) -> str:
    """The model already wrote the code: save it as given, check it, and say where it is."""
    from core import code_quality as cq
    code = cq.extract_code(code) or code
    path = _resolve_save_path(output_path, language, description or "jarvis code")
    saved = _save_file(path, code)
    if saved.startswith("Could not save"):
        return saved
    print(f"[Code] ✅ Saved: {path}")
    if player:
        player.write_log(f"[Code] Saved: {path}")
    try:
        report = cq.static_check(language, code)
    except Exception:
        report = {}
    problems = (report.get("errors") or []) + [f"not installed: {m}" for m in report.get("missing_modules") or []]
    note = (f"Problems found: {'; '.join(problems[:3])}." if problems
            else f"Checked: {report.get('checker')}, clean." if report.get("checker") not in (None, "-", "none available")
            else "")
    return f"Code saved to: {path}\n{note}".strip()


def _write_action(description, language, output_path, player) -> str:
    if not description:
        return "Please describe what you want me to write, sir."
    if player:
        player.write_log("[Code] Writing code...")
    try:
        code, path = _write(description, language, output_path, player)
        print(f"[Code] ✅ Written: {path}")
        return (f"Code written. Saved to: {path}\n{_report_line(_LAST_REPORT)}\n\n"
                f"Preview:\n{_preview(code)}")
    except Exception as e:
        return f"Could not generate code: {e}"


def _edit_action(file_path, instruction, player) -> str:
    if not file_path:
        return "Please provide a file path to edit, sir."
    if not instruction:
        return "Please describe what change to make, sir."

    content, err = _read_file(file_path)
    if err:
        return err

    if player:
        player.write_log("[Code] Editing file...")

    from core import code_quality as cq
    path = Path(file_path)
    lang = next((k for k, v in cq.EXT.items() if v == path.suffix.lower()), "text")
    before = cq.static_check(lang, content)
    log = (lambda m: (print(m), player.write_log(m))) if player else print
    try:
        edited, report = cq.generate(f"Apply this change to the file {path.name}: {instruction}", lang,
                                     existing=content, log=log)
    except Exception as e:
        return f"Could not edit code: {e}"
    if not report["ok"] and before["ok"]:
        # Never replace a file that passed its checks with one that does not.
        draft = path.with_name(path.stem + ".jarvis-draft" + path.suffix)
        _save_file(draft, edited)
        return (f"The edited version did not pass checks, so {path.name} was left unchanged. "
                f"{_report_line(report)} Draft saved to {draft}.")
    backup = path.with_name(path.name + ".bak")
    _save_file(backup, content)
    status = _save_file(path, edited)
    print(f"[Code] ✅ Edited: {file_path}")
    return (f"File edited. {status} Backup of the original: {backup}.\n{_report_line(report)}\n\n"
            f"Preview:\n{_preview(edited)}")


def _explain_action(file_path, code, player) -> str:
    if file_path and not code:
        code, err = _read_file(file_path)
        if err:
            return err
    if not code:
        return "Please provide code or a file path to explain, sir."

    if player:
        player.write_log("[Code] Analyzing code...")

    model  = _get_gemini()
    prompt = f"""Explain what this code does in simple, clear language.
Focus on: what it does, how it works, and any important details.
Be concise — 3 to 6 sentences maximum.

Code:
{code[:4000]}

Explanation:"""

    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        return f"Could not explain code: {e}"


def _run_action(file_path, args, timeout, player) -> str:
    if not file_path:
        return "Please provide a file path to run, sir."
    p = Path(file_path)
    if not p.exists():
        return f"File not found: {file_path}"
    if player:
        player.write_log(f"[Code] Running {p.name}...")
    return _run_file(p, args, timeout)


def _optimize_action(file_path, code, language, output_path, player) -> str:

    if file_path and not code:
        code, err = _read_file(file_path)
        if err:
            return err
    if not code:
        return "Please provide code or a file path to optimize, sir."

    if player:
        player.write_log("[Code] Optimizing code...")

    lang  = language or "python"
    model = _get_gemini()

    prompt = f"""You are an expert {lang} developer and code reviewer.
Optimize the following code for:
1. Performance — eliminate unnecessary operations, use efficient data structures
2. Readability — clear variable names, proper formatting, logical structure
3. Best practices — modern {lang} patterns, error handling, type hints if applicable
4. Remove dead code, redundant comments, and unnecessary complexity

Return ONLY the optimized code — no explanation, no markdown, no backticks.

Original code:
{code[:6000]}

Optimized code:"""

    try:
        response  = model.generate_content(prompt)
        optimized = _clean_code(response.text)
        from core import code_quality as cq
        optimized, _ = cq.repair(optimized, lang, "Optimise this code without changing its behaviour.")
    except Exception as e:
        return f"Could not optimize code: {e}"

    # Kaydet
    if file_path:
        save_path = Path(file_path)
    else:
        save_path = _resolve_save_path(output_path, lang)

    status = _save_file(save_path, optimized)
    print(f"[Code] ✅ Optimized: {save_path}")

    original_lines  = len(code.splitlines())
    optimized_lines = len(optimized.splitlines())
    diff = original_lines - optimized_lines

    return (
        f"Code optimized. {status}\n"
        f"Lines: {original_lines} → {optimized_lines} "
        f"({'−' if diff > 0 else '+'}{abs(diff)} lines)\n\n"
        f"Preview:\n{_preview(optimized)}"
    )


def _screen_debug_action(description, file_path, player, speak=None) -> str:

    if player:
        player.write_log("[Code] Taking screenshot for analysis...")

    print("[Code] 📸 Capturing screen for debug...")


    screenshot_path = _take_screenshot()
    if not screenshot_path:
        return "Could not take screenshot, sir. Please make sure PyAutoGUI is installed."


    file_content = ""
    if file_path:
        file_content, err = _read_file(file_path)
        if err:
            print(f"[Code] ⚠️ Could not read file: {err}")

    try:
        from google.genai import types

        image_bytes  = screenshot_path.read_bytes()
        image_base64 = _image_to_base64(screenshot_path)

        user_question = description or "What error or problem do you see on the screen? How can it be fixed?"

        context = ""
        if file_content:
            context = f"\n\nAdditionally, here is the related file content:\n```\n{file_content[:4000]}\n```"

        analysis_prompt = f"""You are an expert programmer and debugger analyzing a screenshot.

User's question: {user_question}{context}

Please:
1. Identify any errors, exceptions, or problems visible on the screen
2. Explain what is causing the problem in simple terms
3. Provide a concrete fix or solution
4. If there's code visible, show the corrected version

Be specific and actionable. If you see an error message, quote it exactly."""

        contents = [
            types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
            analysis_prompt,
        ]

        response = gemini.call(contents, tier=gemini.SMART, timeout_ms=45_000)
        if response is None:
            return "Sir, I couldn't reach Gemini to analyse that screenshot."

        analysis = (response.text or "").strip()
        print(f"[Code] ✅ Screen analysis complete")

        try:
            screenshot_path.unlink()
        except Exception:
            pass

        if file_path and file_content:

            code_match = re.search(r"```[a-zA-Z]*\n(.*?)```", analysis, re.DOTALL)
            if code_match:
                fixed_code = code_match.group(1).strip()
                save_path  = Path(file_path)
                _save_file(save_path, fixed_code)
                analysis += f"\n\n✅ Fixed code has been saved to: {file_path}"
                print(f"[Code] ✅ Fixed code saved: {file_path}")

        return analysis

    except Exception as e:

        try:
            screenshot_path.unlink()
        except Exception:
            pass
        return f"Screen analysis failed: {e}"


def code_helper(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
    speak=None
) -> str:
    """
    Called from main.py.

    parameters:
        action      : write | edit | explain | run | build | screen_debug | optimize | auto
        description : What the code should do / what change to make / what problem to analyze
        language    : Programming language (default: python)
        output_path : Where to save — user specifies full path or filename
        file_path   : Path to existing file (edit / explain / run / build / optimize)
        code        : Raw code string (explain/optimize without a file)
        args        : CLI argument list for run/build
        timeout     : Execution timeout in seconds (default: 30)
    """
    p           = parameters or {}
    action      = p.get("action", "auto").lower().strip()
    description = p.get("description", "").strip()
    language    = p.get("language", "python").strip()
    output_path = _expand(p.get("output_path", ""))
    file_path   = _expand(p.get("file_path", ""))
    if file_path and not Path(file_path).exists():
        from core import paths
        file_path = str(paths.resolve(p.get("file_path", "")))   # "solve.py", "Desktop/x.py": find it
    code        = p.get("code", "").strip()
    args        = p.get("args", [])
    timeout     = int(p.get("timeout", 30))

    if action == "auto":
        action = _detect_intent(description, file_path, code)
        print(f"[Code] 🤖 Auto-detected: {action}")

    if action == "write":
        if code:
            return _save_code_action(code, language, output_path, description, player)
        return _write_action(description, language, output_path, player)

    elif action == "edit":
        return _edit_action(
            file_path,
            description or p.get("instruction", ""),
            player
        )

    elif action == "explain":
        return _explain_action(file_path, code, player)

    elif action == "run":
        return _run_action(file_path, args, timeout, player)

    elif action == "build":
        return _build(description, language, output_path, args, timeout, speak, player)

    elif action == "optimize":
        return _optimize_action(file_path, code, language, output_path, player)

    elif action == "screen_debug":
        return _screen_debug_action(description, file_path, player, speak)

    else:
        return f"Unknown action: '{action}'. Use write, edit, explain, run, build, optimize, or screen_debug."


# ── Tool declaration (auto-discovered by core/action_loader.py) ──────────────
TOOL = {
    "name": "code_helper",
    "description": "Writes, edits, explains, runs, or builds code files.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "write | edit | explain | run | build | auto (default: auto)"
            },
            "description": {
                "type": "STRING",
                "description": "What the code should do or what change to make"
            },
            "language": {
                "type": "STRING",
                "description": "Programming language (default: python)"
            },
            "output_path": {
                "type": "STRING",
                "description": "Where to save the file"
            },
            "file_path": {
                "type": "STRING",
                "description": "Path to existing file for edit/explain/run/build"
            },
            "code": {
                "type": "STRING",
                "description": "Raw code: for explain/optimize, or with write to save code you already wrote as-is (no description needed)"
            },
            "args": {
                "type": "STRING",
                "description": "CLI arguments for run/build"
            },
            "timeout": {
                "type": "INTEGER",
                "description": "Execution timeout in seconds (default: 30)"
            }
        },
        "required": [
            "action"
        ]
    },
    "handler": code_helper,
}
